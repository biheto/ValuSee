$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonDir = Join-Path $Root ".python"
$PythonExe = Join-Path $PythonDir "tools\python.exe"
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$InstallerDir = Join-Path $Root ".cache"
$NugetZip = Join-Path $InstallerDir "python-3.13.5-nuget.zip"
$PythonUrl = "https://www.nuget.org/api/v2/package/python/3.13.5"

Write-Host "== ValuSee setup =="
Write-Host "Project: $Root"

if (!(Test-Path $PythonExe)) {
    Write-Host "Installing portable Python 3.13.5 into project..."
    New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
    if (Test-Path $PythonDir) {
        Remove-Item -LiteralPath $PythonDir -Recurse -Force
    }
    if (!(Test-Path $NugetZip)) {
        Write-Host "Downloading Python NuGet package..."
        Invoke-WebRequest -Uri $PythonUrl -OutFile $NugetZip
    }
    New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
    Expand-Archive -LiteralPath $NugetZip -DestinationPath $PythonDir -Force
}

if (!(Test-Path $PythonExe)) {
    throw "Portable Python install failed: $PythonExe not found"
}

Write-Host "Python:"
& $PythonExe -V

if (Test-Path $VenvDir) {
    Write-Host "Removing broken .venv..."
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

Write-Host "Creating .venv..."
& $PythonExe -m venv $VenvDir

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e .

Write-Host "Building frontend..."
Push-Location (Join-Path $Root "web")
if (!(Test-Path "node_modules")) {
    npm install
}
npm run build
Pop-Location

Write-Host "Writing start-all.cmd..."
$StartCmd = @"
@echo off
cd /d "%~dp0"
echo Starting ValuSee at http://127.0.0.1:8100/
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8100
"@
Set-Content -Path (Join-Path $Root "start-all.cmd") -Value $StartCmd -Encoding ASCII

Write-Host "Starting backend..."
Start-Process -FilePath (Join-Path $Root "start-all.cmd") -WorkingDirectory $Root -WindowStyle Hidden
Write-Host "Done. Open http://127.0.0.1:8100/"
