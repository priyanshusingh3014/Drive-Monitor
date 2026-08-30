import argparse
import getpass
import json
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


def is_windows():
    return os.name == 'nt'


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

    print(message)
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

    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', executable, params, None, 1)
    return result > 32


def scheduled_task_exists():
    if not is_windows():
        return False

    result = subprocess.run(
        ['schtasks', '/Query', '/TN', TASK_NAME],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_installed():
    return get_installed_exe_path().exists() or scheduled_task_exists()


def path_is_inside(child, parent):
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_watch_args(args):
    watch_args = ['--watch']
    if args.include_hidden:
        watch_args.append('--include-hidden')
    if args.max_files > 0:
        watch_args.extend(['--max-files', str(args.max_files)])
    return watch_args


def write_install_config(args):
    config_path = get_install_dir() / CONFIG_FILE_NAME
    config = {
        'server_url': args.server_url,
        'token': args.token,
        'interval': args.interval,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')


def create_scheduled_task(installed_exe, args):
    command = subprocess.list2cmdline([str(installed_exe), *build_watch_args(args)])
    subprocess.run(
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
        capture_output=True,
        text=True,
    )
    subprocess.run(['schtasks', '/Run', '/TN', TASK_NAME], capture_output=True, text=True)


def delete_scheduled_task():
    if not scheduled_task_exists():
        return

    subprocess.run(['schtasks', '/End', '/TN', TASK_NAME], capture_output=True, text=True)
    subprocess.run(
        ['schtasks', '/Delete', '/TN', TASK_NAME, '/F'],
        check=True,
        capture_output=True,
        text=True,
    )


def install_agent(args):
    install_dir = get_install_dir()
    installed_exe = get_installed_exe_path()
    install_dir.mkdir(parents=True, exist_ok=True)

    source = current_program_path()
    if source != installed_exe:
        shutil.copy2(source, installed_exe)

    write_install_config(args)
    create_scheduled_task(installed_exe, args)


def remove_install_dir_later(install_dir):
    command = f'timeout /t 2 /nobreak > nul & rmdir /s /q "{install_dir}"'
    subprocess.Popen(
        ['cmd.exe', '/c', command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
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


def run_install_ui(args):
    if not is_windows():
        print('Install/uninstall UI is only available on Windows.', file=sys.stderr)
        return 1

    if not is_admin():
        admin_args = ['--install-ui', '--server-url', args.server_url, '--interval', str(args.interval)]
        if args.token:
            admin_args.extend(['--token', args.token])
        if args.include_hidden:
            admin_args.append('--include-hidden')
        if args.max_files > 0:
            admin_args.extend(['--max-files', str(args.max_files)])

        if not relaunch_as_admin(admin_args):
            show_message('Administrator permission was not granted.', flags=MB_OK | MB_ICONERROR)
            return 1
        return 0

    choice = show_message(
        'Do you want to install the Drive Agent on this PC?',
        flags=MB_YESNO | MB_ICONQUESTION,
    )
    if choice != IDYES:
        return 0

    try:
        install_agent(args)
    except Exception as exc:
        show_message(f'Drive Agent installation failed:\n\n{exc}', flags=MB_OK | MB_ICONERROR)
        return 1

    show_message('Drive Agent successfully installed on your PC.')
    return 0


def run_uninstall_ui():
    if not is_windows():
        print('Install/uninstall UI is only available on Windows.', file=sys.stderr)
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

    try:
        uninstall_agent()
    except Exception as exc:
        show_message(f'Drive Agent uninstall failed:\n\n{exc}', flags=MB_OK | MB_ICONERROR)
        return 1

    show_message('Drive Agent successfully uninstalled from your PC.')
    return 0


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


def iter_non_c_drives():
    yield from iter_available_drives(include_c=False)


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


def iter_visible_files(root, include_hidden=False, max_files=0):
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
            yield {
                'drive': str(root)[:2],
                'path': str(full_path),
                'name': filename,
                'extension': full_path.suffix.lower(),
                'size_bytes': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }

            if max_files > 0 and scanned >= max_files:
                return


def scan_machine(include_hidden=False, max_files=0):
    drives = list(iter_non_c_drives())
    files = []

    for drive in drives:
        remaining = max_files - len(files) if max_files > 0 else 0
        files.extend(iter_visible_files(drive, include_hidden=include_hidden, max_files=remaining))
        if max_files > 0 and len(files) >= max_files:
            break

    return drives, files


def post_payload(server_url, token, payload):
    body = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'SystemMonitorAgent/1.0',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    request = Request(server_url, data=body, headers=headers, method='POST')
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def run_once(args):
    drives, files = scan_machine(include_hidden=args.include_hidden, max_files=args.max_files)
    storage = collect_storage_info()
    payload = {
        'device_id': get_device_id(),
        'hostname': socket.gethostname(),
        'username': getpass.getuser(),
        'platform': platform.platform(),
        'drives': [drive[:2] for drive in drives],
        'storage': storage,
        'files': files,
    }

    if args.dry_run:
        print(f'Found {len(files)} visible file(s) on {len(drives)} non-C drive(s).')
        return True

    try:
        result = post_payload(args.server_url, args.token, payload)
    except HTTPError as exc:
        print(f'Sync failed: HTTP {exc.code} {exc.reason}', file=sys.stderr)
        return False
    except URLError as exc:
        print(f'Sync failed: {exc.reason}', file=sys.stderr)
        return False
    except TimeoutError:
        print('Sync failed: request timed out', file=sys.stderr)
        return False

    print(f"Synced {result.get('file_count', 0)} file(s) from {socket.gethostname()}.")
    return True


def parse_args():
    app_config = load_app_config()
    parser = argparse.ArgumentParser(description='System Monitor drive file scanner')
    parser.add_argument('--server-url', default=os.environ.get('AGENT_SERVER_URL') or app_config.get('server_url') or DEFAULT_SERVER_URL)
    parser.add_argument('--token', default=os.environ.get('AGENT_TOKEN') or app_config.get('token') or '')
    parser.add_argument('--install-ui', action='store_true', help='show the Windows install prompt')
    parser.add_argument('--uninstall-ui', action='store_true', help='show the Windows uninstall prompt')
    parser.add_argument('--watch', action='store_true', help='keep scanning on an interval')
    parser.add_argument('--interval', type=int, default=int(os.environ.get('AGENT_SCAN_INTERVAL_SECONDS') or app_config.get('interval') or '300'))
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
        return run_uninstall_ui() if is_installed() else run_install_ui(args)

    if not args.watch:
        return 0 if run_once(args) else 1

    while True:
        run_once(args)
        time.sleep(max(args.interval, 30))


if __name__ == '__main__':
    raise SystemExit(main())
