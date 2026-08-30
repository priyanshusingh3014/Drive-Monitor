import json
from datetime import timedelta, timezone as datetime_timezone

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ArchivedFile, EndpointDevice


ONLINE_WINDOW = timedelta(minutes=10)


def format_size(size_bytes):
    size = float(size_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            if unit == 'B':
                return f'{int(size)} B'
            return f'{size:.1f} {unit}'.replace('.0 ', ' ')
        size /= 1024


def format_storage_pair(used_bytes, total_bytes):
    if not total_bytes:
        return '0 GB / 0 GB'
    return f'{format_size(used_bytes)} / {format_size(total_bytes)}'


def storage_status(used_bytes, total_bytes):
    if not total_bytes:
        return 'Unknown'

    usage_percent = (used_bytes / total_bytes) * 100
    if usage_percent >= 90:
        return 'Critical'
    if usage_percent >= 80:
        return 'Warning'
    return 'Optimal'


def non_negative_int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def online_devices():
    return EndpointDevice.objects.filter(last_seen__gte=timezone.now() - ONLINE_WINDOW)


def device_storage_totals():
    totals = EndpointDevice.objects.aggregate(
        c_used=Sum('c_drive_used_bytes'),
        c_total=Sum('c_drive_total_bytes'),
        secondary_used=Sum('secondary_used_bytes'),
        secondary_total=Sum('secondary_total_bytes'),
    )
    used_bytes = (totals['c_used'] or 0) + (totals['secondary_used'] or 0)
    total_bytes = (totals['c_total'] or 0) + (totals['secondary_total'] or 0)
    return used_bytes, total_bytes


def dashboard_file_rows(device):
    if not device:
        return []

    rows = []
    for archived_file in device.files.all():
        rows.append({
            'file': archived_file,
            'size': format_size(archived_file.size_bytes),
        })
    return rows


def home(request):
    devices = list(EndpointDevice.objects.all())
    selected_device = None
    selected_device_id = request.GET.get('device', '')

    if devices:
        selected_device = next(
            (device for device in devices if str(device.device_id) == selected_device_id),
            devices[0],
        )
        selected_device_id = selected_device.device_id

    storage_used, storage_total = device_storage_totals()
    context = {
        'active_page': 'dashboard',
        'active_agents': online_devices().count(),
        'total_storage': format_storage_pair(storage_used, storage_total),
        'devices': devices,
        'selected_device': selected_device,
        'selected_device_id': selected_device_id,
        'monitored_files': dashboard_file_rows(selected_device),
    }
    return render(request, 'core/home.html', context)


def healthz(request):
    return JsonResponse({'ok': True})


def devices(request):
    active_devices = online_devices()
    all_devices = EndpointDevice.objects.all()
    context = {
        'active_page': 'devices',
        'active_devices': active_devices.count(),
        'offline_devices': all_devices.count() - active_devices.count(),
        'devices': all_devices,
    }
    return render(request, 'core/devices.html', context)


def storage(request):
    rows = []
    for device in EndpointDevice.objects.all():
        total_used = device.c_drive_used_bytes + device.secondary_used_bytes
        total_capacity = device.c_drive_total_bytes + device.secondary_total_bytes
        status = storage_status(total_used, total_capacity)
        rows.append({
            'device': device,
            'c_drive': format_storage_pair(device.c_drive_used_bytes, device.c_drive_total_bytes),
            'secondary_drives': format_storage_pair(device.secondary_used_bytes, device.secondary_total_bytes),
            'status': status,
            'status_class': status.lower(),
        })

    return render(request, 'core/storage.html', {
        'active_page': 'storage',
        'storage_rows': rows,
    })


def files(request):
    selected_device = request.GET.get('device', '')
    selected_drive = request.GET.get('drive', '')

    devices_qs = EndpointDevice.objects.all()
    files_qs = ArchivedFile.objects.select_related('device').all()

    if selected_device:
        files_qs = files_qs.filter(device_id=selected_device)

    drive_options_qs = files_qs.values_list('drive', flat=True).distinct().order_by('drive')

    if selected_drive:
        files_qs = files_qs.filter(drive=selected_drive)

    file_count = files_qs.count()
    total_size = files_qs.aggregate(total=Sum('size_bytes'))['total'] or 0
    files_list = list(files_qs[:500])

    context = {
        'active_page': 'files',
        'devices': devices_qs,
        'drive_options': drive_options_qs,
        'selected_device': selected_device,
        'selected_drive': selected_drive,
        'file_count': file_count,
        'total_size': format_size(total_size),
        'archived_files': files_list,
        'shown_file_count': len(files_list),
    }
    return render(request, 'core/files.html', context)


@csrf_exempt
@require_POST
def agent_sync(request):
    if settings.AGENT_API_TOKEN:
        expected = f'Bearer {settings.AGENT_API_TOKEN}'
        if request.headers.get('Authorization') != expected:
            return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    device_id = str(payload.get('device_id', '')).strip()
    hostname = str(payload.get('hostname', '')).strip()
    files = payload.get('files', [])
    replace_files = payload.get('replace_files', True)

    if not device_id or not hostname or not isinstance(files, list):
        return JsonResponse({'ok': False, 'error': 'device_id, hostname, and files are required'}, status=400)

    now = timezone.now()
    records = []
    total_size = 0

    for item in files:
        if not isinstance(item, dict):
            continue

        path = str(item.get('path', '')).strip()
        if not path:
            continue

        size_bytes = non_negative_int(item.get('size_bytes'))
        modified_at = parse_datetime(str(item.get('modified_at') or '')) if item.get('modified_at') else None
        if modified_at and timezone.is_naive(modified_at):
            modified_at = timezone.make_aware(modified_at, datetime_timezone.utc)

        total_size += size_bytes
        records.append(ArchivedFile(
            drive=str(item.get('drive', ''))[:8],
            path=path,
            name=str(item.get('name') or path.split('\\')[-1])[:512],
            extension=str(item.get('extension') or '')[:64],
            size_bytes=size_bytes,
            modified_at=modified_at,
        ))

    drives = payload.get('drives', [])
    if not isinstance(drives, list):
        drives = []

    storage = payload.get('storage', {})
    if not isinstance(storage, dict):
        storage = {}

    c_drive = storage.get('c_drive', {})
    if not isinstance(c_drive, dict):
        c_drive = {}

    secondary_drives = storage.get('secondary_drives', [])
    if not isinstance(secondary_drives, list):
        secondary_drives = []

    c_total = non_negative_int(c_drive.get('total_bytes'))
    c_used = non_negative_int(c_drive.get('used_bytes'))
    secondary_total = 0
    secondary_used = 0
    for drive_info in secondary_drives:
        if not isinstance(drive_info, dict):
            continue
        secondary_total += non_negative_int(drive_info.get('total_bytes'))
        secondary_used += non_negative_int(drive_info.get('used_bytes'))

    with transaction.atomic():
        defaults = {
            'hostname': hostname[:255],
            'username': str(payload.get('username') or '')[:255],
            'platform': str(payload.get('platform') or '')[:255],
            'drives': drives,
            'c_drive_total_bytes': c_total,
            'c_drive_used_bytes': c_used,
            'secondary_total_bytes': secondary_total,
            'secondary_used_bytes': secondary_used,
            'storage_status': storage_status(c_used + secondary_used, c_total + secondary_total),
            'last_seen': now,
        }

        if replace_files:
            defaults['total_files'] = len(records)
            defaults['total_size_bytes'] = total_size

        device, _created = EndpointDevice.objects.update_or_create(
            device_id=device_id,
            defaults=defaults,
        )

        if replace_files:
            ArchivedFile.objects.filter(device=device).delete()
            for record in records:
                record.device = device
            ArchivedFile.objects.bulk_create(records, batch_size=1000)

    return JsonResponse({
        'ok': True,
        'device_id': device.device_id,
        'file_count': len(records),
        'total_size_bytes': total_size,
    })
