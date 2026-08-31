param(
    [string]$AgentToken = $env:AGENT_API_TOKEN
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$OldBundleDir = Join-Path $ProjectRoot "dist\agent_client"
if (Test-Path -LiteralPath $OldBundleDir) {
    Remove-Item -LiteralPath $OldBundleDir -Recurse -Force
}

$SourceFile = Join-Path $ProjectRoot "agent_client.py"
$BuildSource = $SourceFile

if ($AgentToken) {
    $BuildDir = Join-Path $ProjectRoot ".agent_build"
    $EmbeddedSource = Join-Path $BuildDir "agent_client.py"
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    $Source = Get-Content -LiteralPath $SourceFile -Raw
    $TokenLiteral = $AgentToken | ConvertTo-Json -Compress
    $Source = $Source.Replace("DEFAULT_AGENT_TOKEN = ''", "DEFAULT_AGENT_TOKEN = $TokenLiteral")
    Set-Content -LiteralPath $EmbeddedSource -Value $Source -Encoding UTF8
    $BuildSource = $EmbeddedSource
} else {
    Write-Warning "No AgentToken supplied. The exe will ask for the Render AGENT_API_TOKEN during installation."
}

.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --noupx --name agent_client $BuildSource

Write-Host "Built dist\agent_client.exe"
