$ErrorActionPreference = "Stop"

.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --onefile --name agent_client agent_client.py

Write-Host "Built dist\agent_client.exe"
