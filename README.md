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

Double-click `dist\agent_client.exe` with no options to install it. Windows will ask for administrator permission, then the app asks:

```text
Do you want to install the Drive Agent on this PC?
```

After install, double-click the same `.exe` again to uninstall it. It will ask:

```text
Do you want to uninstall Drive Agent from this PC?
```

The installer copies the agent to `C:\Program Files\SystemMonitorDriveAgent\agent_client.exe` and creates a visible Windows scheduled task named `SystemMonitorDriveAgent`.

For a one-time manual sync:

```powershell
.\dist\agent_client.exe --server-url http://127.0.0.1:8000/api/agent/sync/
```

For a small test scan:

```powershell
.\dist\agent_client.exe --max-files 10 --server-url http://127.0.0.1:8000/api/agent/sync/
```

For continuous scanning:

```powershell
.\dist\agent_client.exe --watch --interval 300 --server-url http://127.0.0.1:8000/api/agent/sync/
```

To rebuild the executable:

```powershell
.\build_agent.ps1
```
