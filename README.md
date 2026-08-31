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

If you build without a token, the exe asks for the Render `AGENT_API_TOKEN` during installation. To avoid that prompt, embed the token at build time:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_agent.ps1 -AgentToken "paste-your-render-agent-api-token-here"
```

Double-click `dist\agent_client.exe` with no options to install it. Windows will ask for administrator permission, then the app asks:

```text
Do you want to install the Drive Agent on this PC?
```

If Drive Agent is already installed, double-clicking the same `.exe` asks to reinstall and register it again:

```text
Drive Agent is already installed on this PC.

Do you want to reinstall it and register this PC on the dashboard?
```

To uninstall explicitly, run `agent_client.exe --uninstall-ui`.

The installer copies the no-console agent to `C:\Program Files\SystemMonitorDriveAgent\agent_client.exe`, creates a Windows scheduled task named `SystemMonitorDriveAgent`, and starts the first background sync immediately.

By default, file scanning skips the `C:` drive. The agent still reports storage capacity for the machine so the dashboard can show device/storage status quickly. The Devices section shows the agent ID, IP address, MAC address, drives, files, and last seen time. The Files section lists discovered files and shows View/Download actions. Download is available for stored file copies up to 5 MB by default.

If Windows Defender flags the executable, use code signing or submit the file to Microsoft as a false positive; do not disable Windows security.

For a one-time manual sync:

```powershell
.\dist\agent_client.exe --server-url https://drive-monitor.onrender.com/api/agent/sync/
```

For a small test scan:

```powershell
.\dist\agent_client.exe --max-files 10 --server-url https://drive-monitor.onrender.com/api/agent/sync/
```

For continuous scanning:

```powershell
.\dist\agent_client.exe --watch --interval 300 --server-url https://drive-monitor.onrender.com/api/agent/sync/
```

To change the per-file download copy limit:

```powershell
.\dist\agent_client.exe --max-upload-bytes 10485760
```
