# Construit l'appli (dist\ClaudeTracker\) puis l'installeur (dist\ClaudeTracker-<version>-Setup.exe).
# Usage local : .\build.ps1              (crée/utilise .venv)
# Usage CI    : .\build.ps1 -Python python
param(
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $Python) {
    if (-not (Test-Path ".venv")) {
        Write-Host "Création de l'environnement virtuel .venv..."
        py -3 -m venv .venv
    }
    $Python = ".\.venv\Scripts\python.exe"
}

& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "Installation des dépendances échouée" }

Write-Host "Tests..."
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Les tests ont échoué" }

$version = (& $Python -c "import claude_tracker; print(claude_tracker.__version__)").Trim()
Write-Host "Version $version"

Write-Host "Génération de l'icône..."
& $Python -m claude_tracker.render --ico assets\app.ico

Write-Host "Construction de l'appli (PyInstaller)..."
& $Python -m PyInstaller --noconfirm --clean --onedir --noconsole `
    --name ClaudeTracker `
    --icon assets\app.ico `
    --paths src `
    --collect-data customtkinter `
    --hidden-import pystray._win32 `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $iscc) {
    Write-Host ""
    Write-Host "Inno Setup introuvable : seule l'appli portable est construite (dist\ClaudeTracker\)." -ForegroundColor Yellow
    Write-Host "Pour l'installeur : winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}

Write-Host "Construction de l'installeur..."
& $iscc /Q "/DAppVersion=$version" installer\ClaudeTracker.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a échoué" }

Write-Host ""
Write-Host "OK -> dist\ClaudeTracker-$version-Setup.exe" -ForegroundColor Green
