# Django Starter

A small Django project scaffold with a `config` project package and a `core` app serving the home page.

## Run Locally

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Useful Commands

```powershell
python manage.py check
python manage.py test
python manage.py migrate
python manage.py createsuperuser
```

## Drive Agent

The agent scans visible files on all available drives except `C:` and sends file metadata to Django.
Hidden and system files are skipped by default.

Build the Windows agent with:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_agent.ps1
```

Double-click `dist\agent_client\agent_client.exe` with no options to install it. Windows will ask for administrator permission, then the app asks:

```text
Do you want to install the Drive Agent on this PC?
```

After install, double-click the same `.exe` again to uninstall it. It will ask:

```text
Do you want to uninstall Drive Agent from this PC?
```

The installer copies the no-console agent bundle to `C:\Program Files\SystemMonitorDriveAgent\agent_client.exe`, creates a Windows scheduled task named `SystemMonitorDriveAgent`, and starts the first background sync immediately.

Keep the generated `_internal` folder beside `agent_client.exe` when sharing the build folder. If Windows Defender flags the executable, use code signing or submit the file to Microsoft as a false positive; do not disable Windows security.

For a one-time manual sync:

```powershell
.\dist\agent_client\agent_client.exe --server-url https://drive-monitor.onrender.com/api/agent/sync/
```

For a small test scan:

```powershell
.\dist\agent_client\agent_client.exe --max-files 10 --server-url https://drive-monitor.onrender.com/api/agent/sync/
```

For continuous scanning:

```powershell
.\dist\agent_client\agent_client.exe --watch --interval 300 --server-url https://drive-monitor.onrender.com/api/agent/sync/
```
