import base64
import hashlib
import argparse
import getpass
import json
import mimetypes
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SERVER_URL = 'https://drive-monitor.onrender.com/api/agent/sync/'
DEFAULT_EXCLUDED_DRIVES = 'C:'
DEFAULT_AGENT_TOKEN = ''
DEFAULT_UPLOAD_CONTENT = True
DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
APP_DISPLAY_NAME = 'Drive Agent'
INSTALL_DIR_NAME = 'SystemMonitorDriveAgent'
TASK_NAME = 'SystemMonitorDriveAgent'
CONFIG_FILE_NAME = 'agent_config.json'
DEVICE_FILE = 'device.json'
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20
MB_ICONERROR = 0x10
IDYES = 6
SW_HIDE = 0


def is_windows():
    return os.name == 'nt'


def write_output(message, error=False):
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return

    try:
        print(message, file=stream)
    except OSError:
        pass


def hidden_process_kwargs():
    if is_windows():
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


def run_hidden_process(command, check=False):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check,
        **hidden_process_kwargs(),
    )


def current_program_path():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def load_app_config():
    candidates = [
        current_program_path().with_name(CONFIG_FILE_NAME),
        Path.cwd() / CONFIG_FILE_NAME,
    ]
    for config_path in candidates:
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def get_install_dir():
    base = os.environ.get('ProgramFiles') or 'C:\\Program Files'
    return Path(base) / INSTALL_DIR_NAME


def get_installed_exe_path():
    return get_install_dir() / 'agent_client.exe'


def get_known_config_dirs():
    candidates = []
    if os.environ.get('PROGRAMDATA'):
        candidates.append(Path(os.environ['PROGRAMDATA']) / 'SystemMonitorAgent')
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA']) / 'SystemMonitorAgent')
    candidates.append(Path.home() / '.system-monitor-agent')
    candidates.append(Path.cwd() / '.agent')
    return candidates


def show_message(message, title=APP_DISPLAY_NAME, flags=MB_OK | MB_ICONINFORMATION):
    if is_windows():
        import ctypes

        return ctypes.windll.user32.MessageBoxW(None, message, title, flags)

    write_output(message)
    return IDYES


def is_admin():
    if not is_windows():
        return os.geteuid() == 0 if hasattr(os, 'geteuid') else False

    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args):
    if not is_windows():
        return False

    import ctypes

    if getattr(sys, 'frozen', False):
        executable = str(Path(sys.executable).resolve())
        params = subprocess.list2cmdline(extra_args)
    else:
        executable = str(Path(sys.executable).resolve())
        params = subprocess.list2cmdline([str(Path(__file__).resolve()), *extra_args])

    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', executable, params, None, SW_HIDE)
    return result > 32


def scheduled_task_exists():
    if not is_windows():
        return False

    try:
        result = run_hidden_process(['schtasks', '/Query', '/TN', TASK_NAME])
    except OSError:
        return False
    return result.returncode == 0


def is_installed():
    return (
        get_installed_exe_path().exists()
        or (get_install_dir() / CONFIG_FILE_NAME).exists()
        or scheduled_task_exists()
    )


def path_is_inside(child, parent):
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_watch_args(args):
    watch_args = ['--watch']
    if args.exclude_drives:
        watch_args.extend(['--exclude-drives', args.exclude_drives])
    if not args.upload_content:
        watch_args.append('--no-upload-content')
    if args.max_upload_bytes != DEFAULT_MAX_UPLOAD_BYTES:
        watch_args.extend(['--max-upload-bytes', str(args.max_upload_bytes)])
    if args.include_hidden:
        watch_args.append('--include-hidden')
    if args.max_files > 0:
        watch_args.extend(['--max-files', str(args.max_files)])
    return watch_args


def build_elevated_install_args(args):
    admin_args = ['--install-ui', '--server-url', args.server_url, '--interval', str(args.interval)]
    if args.exclude_drives:
        admin_args.extend(['--exclude-drives', args.exclude_drives])
    if not args.upload_content:
        admin_args.append('--no-upload-content')
    if args.max_upload_bytes != DEFAULT_MAX_UPLOAD_BYTES:
        admin_args.extend(['--max-upload-bytes', str(args.max_upload_bytes)])
    if args.token:
        admin_args.extend(['--token', args.token])
    if args.include_hidden:
        admin_args.append('--include-hidden')
    if args.max_files > 0:
        admin_args.extend(['--max-files', str(args.max_files)])
    return admin_args


def write_install_config(args):
    config_path = get_install_dir() / CONFIG_FILE_NAME
    config = {
        'server_url': args.server_url,
        'token': args.token,
        'interval': args.interval,
        'exclude_drives': args.exclude_drives,
        'upload_content': args.upload_content,
        'max_upload_bytes': args.max_upload_bytes,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')


def create_scheduled_task(installed_exe, args):
    command = subprocess.list2cmdline([str(installed_exe), *build_watch_args(args)])
    run_hidden_process(
        [
            'schtasks',
            '/Create',
            '/TN',
            TASK_NAME,
            '/TR',
            command,
            '/SC',
            'ONLOGON',
            '/RL',
            'HIGHEST',
            '/F',
        ],
        check=True,
    )
    run_hidden_process(['schtasks', '/Run', '/TN', TASK_NAME])


def delete_scheduled_task():
    if not scheduled_task_exists():
        return

    run_hidden_process(['schtasks', '/End', '/TN', TASK_NAME])
    run_hidden_process(
        ['schtasks', '/Delete', '/TN', TASK_NAME, '/F'],
        check=True,
    )


def copy_agent_bundle(source, install_dir, installed_exe):
    source = source.resolve()
    install_dir.mkdir(parents=True, exist_ok=True)

    if source.parent.resolve() == install_dir.resolve():
        return

    if source != installed_exe.resolve():
        shutil.copy2(source, installed_exe)

    source_internal_dir = source.parent / '_internal'
    if not source_internal_dir.exists():
        return

    target_internal_dir = install_dir / '_internal'
    if target_internal_dir.exists():
        if not path_is_inside(target_internal_dir, install_dir):
            raise RuntimeError(f'Unsafe install folder: {target_internal_dir}')
        shutil.rmtree(target_internal_dir)

    shutil.copytree(source_internal_dir, target_internal_dir)


def install_agent(args):
    install_dir = get_install_dir()
    installed_exe = get_installed_exe_path()

    source = current_program_path()
    delete_scheduled_task()
    copy_agent_bundle(source, install_dir, installed_exe)
    write_install_config(args)
    get_device_id()
    create_scheduled_task(installed_exe, args)

    if not installed_exe.exists():
        raise RuntimeError('Installed agent executable was not created.')
    if not scheduled_task_exists():
        raise RuntimeError('Windows scheduled task was not created.')


def remove_install_dir_later(install_dir):
    command = f'timeout /t 2 /nobreak > nul & rmdir /s /q "{install_dir}"'
    subprocess.Popen(
        ['cmd.exe', '/c', command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_process_kwargs(),
    )


def uninstall_agent():
    delete_scheduled_task()

    for config_dir in get_known_config_dirs():
        if config_dir.exists():
            shutil.rmtree(config_dir, ignore_errors=True)

    install_dir = get_install_dir()
    current_path = current_program_path()
    if install_dir.exists():
        if path_is_inside(current_path, install_dir):
            remove_install_dir_later(install_dir)
        else:
            shutil.rmtree(install_dir, ignore_errors=True)


def prompt_for_agent_token():
    if not is_windows():
        return ''

    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$token = [Microsoft.VisualBasic.Interaction]::InputBox("
        "'Paste the Render AGENT_API_TOKEN to register this PC on the dashboard:', "
        f"'{APP_DISPLAY_NAME}', ''); "
        "[Console]::Out.Write($token)"
    )
    try:
        result = run_hidden_process([
            'powershell',
            '-NoProfile',
            '-STA',
            '-WindowStyle',
            'Hidden',
            '-Command',
            script,
        ])
    except OSError:
        return ''

    if result.returncode != 0:
        return ''
    return result.stdout.strip()


def ensure_agent_token(args):
    if not token_required_for_server(args.server_url) or args.token:
        return True

    token = prompt_for_agent_token()
    if token:
        args.token = token
        return True

    show_message(
        (
            'The Render AGENT_API_TOKEN is required to register this PC on the dashboard.\n\n'
            'Run the installer again and paste the token when asked.'
        ),
        flags=MB_OK | MB_ICONERROR,
    )
    return False


def install_and_register(args, reinstall=False):
    if not ensure_agent_token(args):
        return 1

    try:
        install_agent(args)
    except Exception as exc:
        show_message(f'Drive Agent installation failed:\n\n{exc}', flags=MB_OK | MB_ICONERROR)
        return 1

    try:
        register_agent_on_dashboard(args)
    except Exception as exc:
        show_message(
            (
                'Drive Agent was installed, but this PC could not be registered '
                f'on the dashboard yet.\n\nReason: {describe_sync_error(exc)}\n\n'
                'The background agent will keep retrying. If the reason is HTTP 401, '
                'rebuild the exe with the correct Render AGENT_API_TOKEN.'
            ),
            flags=MB_OK | MB_ICONERROR,
        )
        return 1

    action = 'reinstalled' if reinstall else 'installed'
    show_message(
        (
            f'Drive Agent successfully {action} on your PC.\n\n'
            'This device is now registered on the dashboard and will keep syncing in the background.'
        )
    )
    return 0


def uninstall_with_status():
    try:
        uninstall_agent()
    except Exception as exc:
        show_message(f'Drive Agent uninstall failed:\n\n{exc}', flags=MB_OK | MB_ICONERROR)
        return 1

    show_message('Drive Agent successfully uninstalled from your PC.')
    return 0


def run_existing_install_ui(args):
    if not is_admin():
        if not relaunch_as_admin(build_elevated_install_args(args)):
            show_message('Administrator permission was not granted.', flags=MB_OK | MB_ICONERROR)
            return 1
        return 0

    choice = show_message(
        (
            'Drive Agent is already installed on this PC.\n\n'
            'Do you want to reinstall it and register this PC on the dashboard?'
        ),
        flags=MB_YESNO | MB_ICONQUESTION,
    )
    if choice == IDYES:
        return install_and_register(args, reinstall=True)
    return 0


def run_install_ui(args):
    if not is_windows():
        write_output('Install/uninstall UI is only available on Windows.', error=True)
        return 1

    if is_installed():
        return run_existing_install_ui(args)

    if not is_admin():
        if not relaunch_as_admin(build_elevated_install_args(args)):
            show_message('Administrator permission was not granted.', flags=MB_OK | MB_ICONERROR)
            return 1
        return 0

    choice = show_message(
        (
            'Do you want to install the Drive Agent on this PC?\n\n'
            f'It will monitor visible files from all drives except {args.exclude_drives} '
            'and upload storage details, file details, and downloadable file copies '
            f'up to {args.max_upload_bytes // (1024 * 1024)} MB each.'
        ),
        flags=MB_YESNO | MB_ICONQUESTION,
    )
    if choice != IDYES:
        return 0

    return install_and_register(args)


def run_uninstall_ui():
    if not is_windows():
        write_output('Install/uninstall UI is only available on Windows.', error=True)
        return 1

    if not is_admin():
        if not relaunch_as_admin(['--uninstall-ui']):
            show_message('Administrator permission was not granted.', flags=MB_OK | MB_ICONERROR)
            return 1
        return 0

    choice = show_message(
        'Do you want to uninstall Drive Agent from this PC?',
        flags=MB_YESNO | MB_ICONQUESTION,
    )
    if choice != IDYES:
        return 0

    return uninstall_with_status()


def get_config_dir():
    candidates = get_known_config_dirs()

    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / '.write-test'
            test_file.write_text('', encoding='utf-8')
            test_file.unlink(missing_ok=True)
            return path
        except OSError:
            continue

    path = Path.cwd() / '.agent'
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_device_id():
    config_path = get_config_dir() / DEVICE_FILE
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
            if data.get('device_id'):
                return data['device_id']
        except (OSError, json.JSONDecodeError):
            pass

    device_id = str(uuid.uuid4())
    config_path.write_text(json.dumps({'device_id': device_id}, indent=2), encoding='utf-8')
    return device_id


def get_primary_ip_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return ''


def get_primary_mac_address():
    node = uuid.getnode()
    if node & (1 << 40):
        return ''
    return ':'.join(f'{(node >> shift) & 0xff:02X}' for shift in range(40, -1, -8))


def get_windows_attrs(path):
    if os.name != 'nt':
        return None

    try:
        import ctypes

        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return None
        return attrs
    except Exception:
        return None


def is_hidden_or_system(path):
    name = Path(path).name
    if name.startswith('.'):
        return True

    attrs = get_windows_attrs(path)
    if attrs is None:
        return False
    return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def read_downloadable_content(path, size_bytes, upload_content=True, max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES):
    if not upload_content or size_bytes > max_upload_bytes:
        return {}

    try:
        content = path.read_bytes()
    except (OSError, PermissionError):
        return {}

    content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    return {
        'content_base64': base64.b64encode(content).decode('ascii'),
        'content_type': content_type,
        'content_sha256': hashlib.sha256(content).hexdigest(),
    }


def iter_available_drives(include_c=True):
    if os.name == 'nt':
        import ctypes

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if not bitmask & (1 << index):
                continue

            letter = chr(65 + index)
            if not include_c and letter.upper() == 'C':
                continue

            root = f'{letter}:\\'
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
            if drive_type in (DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE) and os.path.isdir(root):
                yield root
        return

    for mount in Path('/mnt').glob('*'):
        if mount.is_dir():
            yield str(mount)


def normalize_drive_name(drive):
    drive_text = str(drive or '').strip().replace('/', '\\')
    if not drive_text:
        return ''

    if len(drive_text) >= 2 and drive_text[1] == ':':
        return f'{drive_text[0].upper()}:'

    return drive_text.rstrip('\\').upper()


def parse_drive_list(value):
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or '').split(',')

    return {
        normalized
        for normalized in (normalize_drive_name(item) for item in raw_items)
        if normalized
    }


def iter_scanned_drives(excluded_drives):
    excluded = parse_drive_list(excluded_drives)
    for drive in iter_available_drives(include_c=True):
        if normalize_drive_name(drive) not in excluded:
            yield drive


def collect_storage_info():
    c_drive = {}
    secondary_drives = []

    for root in iter_available_drives(include_c=True):
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue

        drive_info = {
            'drive': str(root)[:2],
            'total_bytes': usage.total,
            'used_bytes': usage.total - usage.free,
            'free_bytes': usage.free,
        }

        if str(root)[:1].upper() == 'C':
            c_drive = drive_info
        else:
            secondary_drives.append(drive_info)

    return {
        'c_drive': c_drive,
        'secondary_drives': secondary_drives,
    }


def iter_visible_files(
    root,
    include_hidden=False,
    max_files=0,
    upload_content=DEFAULT_UPLOAD_CONTENT,
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
):
    scanned = 0
    for current_root, dirs, files in os.walk(root, topdown=True):
        if not include_hidden:
            dirs[:] = [
                dirname for dirname in dirs
                if not is_hidden_or_system(Path(current_root) / dirname)
            ]

        for filename in files:
            full_path = Path(current_root) / filename
            if not include_hidden and is_hidden_or_system(full_path):
                continue

            try:
                stat = full_path.stat()
            except (OSError, PermissionError):
                continue

            scanned += 1
            file_record = {
                'drive': str(root)[:2],
                'path': str(full_path),
                'name': filename,
                'extension': full_path.suffix.lower(),
                'size_bytes': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
            file_record.update(
                read_downloadable_content(
                    full_path,
                    stat.st_size,
                    upload_content=upload_content,
                    max_upload_bytes=max_upload_bytes,
                )
            )

            yield file_record

            if max_files > 0 and scanned >= max_files:
                return


def collect_files_from_drives(
    drives,
    include_hidden=False,
    max_files=0,
    upload_content=DEFAULT_UPLOAD_CONTENT,
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
):
    files = []

    for drive in drives:
        remaining = max_files - len(files) if max_files > 0 else 0
        files.extend(iter_visible_files(
            drive,
            include_hidden=include_hidden,
            max_files=remaining,
            upload_content=upload_content,
            max_upload_bytes=max_upload_bytes,
        ))
        if max_files > 0 and len(files) >= max_files:
            break

    return files


def scan_machine(
    excluded_drives=None,
    include_hidden=False,
    max_files=0,
    upload_content=DEFAULT_UPLOAD_CONTENT,
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
):
    drives = list(iter_scanned_drives(excluded_drives))
    files = collect_files_from_drives(
        drives,
        include_hidden=include_hidden,
        max_files=max_files,
        upload_content=upload_content,
        max_upload_bytes=max_upload_bytes,
    )
    return drives, files


def post_payload(server_url, token, payload):
    body = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'SystemMonitorAgent/1.0',
        'X-Drive-Agent': 'SystemMonitorDriveAgent/1.0',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    request = Request(server_url, data=body, headers=headers, method='POST')
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def build_agent_payload(device_id, drives, storage, files, replace_files=True):
    return {
        'device_id': device_id,
        'hostname': socket.gethostname(),
        'username': getpass.getuser(),
        'ip_address': get_primary_ip_address(),
        'mac_address': get_primary_mac_address(),
        'platform': platform.platform(),
        'drives': [drive[:2] for drive in drives],
        'storage': storage,
        'files': files,
        'replace_files': replace_files,
    }


def token_required_for_server(server_url):
    return 'drive-monitor.onrender.com' in str(server_url or '').lower()


def describe_sync_error(exc):
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code} {exc.reason}'
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)


def register_agent_on_dashboard(args):
    drives = list(iter_scanned_drives(args.exclude_drives))
    storage = collect_storage_info()
    device_id = get_device_id()
    payload = build_agent_payload(device_id, drives, storage, [], replace_files=False)
    return post_payload(args.server_url, args.token, payload)


def run_once(args):
    drives = list(iter_scanned_drives(args.exclude_drives))
    storage = collect_storage_info()
    device_id = get_device_id()

    if args.dry_run:
        files = collect_files_from_drives(
            drives,
            include_hidden=args.include_hidden,
            max_files=args.max_files,
            upload_content=args.upload_content,
            max_upload_bytes=args.max_upload_bytes,
        )
        excluded = ', '.join(sorted(parse_drive_list(args.exclude_drives))) or 'none'
        write_output(
            f'Found {len(files)} visible file(s) on {len(drives)} scanned drive(s). '
            f'Excluded drive(s): {excluded}.'
        )
        return True

    try:
        heartbeat_payload = build_agent_payload(device_id, drives, storage, [], replace_files=False)
        post_payload(args.server_url, args.token, heartbeat_payload)
        files = collect_files_from_drives(
            drives,
            include_hidden=args.include_hidden,
            max_files=args.max_files,
            upload_content=args.upload_content,
            max_upload_bytes=args.max_upload_bytes,
        )
        payload = build_agent_payload(device_id, drives, storage, files, replace_files=True)
        result = post_payload(args.server_url, args.token, payload)
    except HTTPError as exc:
        write_output(f'Sync failed: HTTP {exc.code} {exc.reason}', error=True)
        return False
    except URLError as exc:
        write_output(f'Sync failed: {exc.reason}', error=True)
        return False
    except TimeoutError:
        write_output('Sync failed: request timed out', error=True)
        return False

    write_output(f"Synced {result.get('file_count', 0)} file(s) from {socket.gethostname()}.")
    return True


def parse_args():
    app_config = load_app_config()
    default_excluded_drives = (
        os.environ.get('AGENT_EXCLUDED_DRIVES')
        or app_config.get('exclude_drives')
        or DEFAULT_EXCLUDED_DRIVES
    )
    if isinstance(default_excluded_drives, (list, tuple, set)):
        default_excluded_drives = ','.join(str(item) for item in default_excluded_drives)
    else:
        default_excluded_drives = str(default_excluded_drives)

    upload_content_default = str(
        os.environ.get('AGENT_UPLOAD_CONTENT')
        or app_config.get('upload_content')
        or DEFAULT_UPLOAD_CONTENT
    ).lower() in {'1', 'true', 'yes', 'on'}
    max_upload_bytes_default = int(
        os.environ.get('AGENT_MAX_UPLOAD_BYTES')
        or app_config.get('max_upload_bytes')
        or DEFAULT_MAX_UPLOAD_BYTES
    )
    parser = argparse.ArgumentParser(description='System Monitor drive file scanner')
    parser.add_argument('--server-url', default=os.environ.get('AGENT_SERVER_URL') or app_config.get('server_url') or DEFAULT_SERVER_URL)
    parser.add_argument('--token', default=os.environ.get('AGENT_TOKEN') or app_config.get('token') or DEFAULT_AGENT_TOKEN)
    parser.add_argument('--install-ui', action='store_true', help='show the Windows install prompt')
    parser.add_argument('--uninstall-ui', action='store_true', help='show the Windows uninstall prompt')
    parser.add_argument('--watch', action='store_true', help='keep scanning on an interval')
    parser.add_argument('--interval', type=int, default=int(os.environ.get('AGENT_SCAN_INTERVAL_SECONDS') or app_config.get('interval') or '300'))
    parser.add_argument('--exclude-drives', default=default_excluded_drives, help='comma-separated drive letters to skip for file scanning')
    parser.add_argument('--no-upload-content', action='store_false', dest='upload_content', default=upload_content_default, help='only send file metadata, not downloadable copies')
    parser.add_argument('--max-upload-bytes', type=int, default=max_upload_bytes_default, help='maximum single-file size to upload for download')
    parser.add_argument('--include-hidden', action='store_true', help='include hidden/system files')
    parser.add_argument('--max-files', type=int, default=int(os.environ.get('AGENT_MAX_FILES', '0')), help='limit files for testing; default scans all')
    parser.add_argument('--dry-run', action='store_true', help='scan and print the count without sending data')
    return parser.parse_args()


def main():
    args = parse_args()
    if args.install_ui:
        return run_install_ui(args)
    if args.uninstall_ui:
        return run_uninstall_ui()
    if len(sys.argv) == 1 and is_windows():
        return run_install_ui(args)

    if not args.watch:
        return 0 if run_once(args) else 1

    while True:
        run_once(args)
        time.sleep(max(args.interval, 30))


if __name__ == '__main__':
    raise SystemExit(main())
