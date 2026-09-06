$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv313\Scripts\python.exe"

if (!(Test-Path $Python)) {
    throw "Python not found: $Python"
}

Start-Process -FilePath $Python -ArgumentList @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8100"
) -WorkingDirectory $Root -WindowStyle Hidden

Start-Sleep -Seconds 4
try {
    $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8100/health"
    Write-Host $health.Content
    Write-Host "ValuSee started at http://127.0.0.1:8100/"
} catch {
    Write-Host $_.Exception.Message
    throw
}
