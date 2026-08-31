param(
    [string]$AgentToken = $env:AGENT_API_TOKEN,
    [switch]$AllowMissingToken
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
} elseif (-not $AllowMissingToken) {
    throw "AgentToken is required for the Render dashboard build. Run: powershell -ExecutionPolicy Bypass -File .\build_agent.ps1 -AgentToken `"YOUR_RENDER_AGENT_API_TOKEN`""
} else {
    Write-Warning "No AgentToken supplied. This exe is only for local testing and will not register on the Render dashboard if AGENT_API_TOKEN is enabled."
}

.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --noupx --name agent_client $BuildSource

Write-Host "Built dist\agent_client.exe"
