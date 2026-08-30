$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$OldOneFile = Join-Path $ProjectRoot "dist\agent_client.exe"
if (Test-Path -LiteralPath $OldOneFile) {
    Remove-Item -LiteralPath $OldOneFile -Force
}

.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onedir --windowed --noupx --name agent_client agent_client.py

Write-Host "Built dist\agent_client\agent_client.exe"
