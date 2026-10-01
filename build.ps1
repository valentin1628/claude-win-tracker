# Construit dist\ClaudeTracker.exe (un seul fichier, sans console).
# Usage : .\build.ps1   (depuis la racine du dépôt, dans PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Création de l'environnement virtuel .venv..."
    py -3 -m venv .venv
}
$python = ".\.venv\Scripts\python.exe"

& $python -m pip install --upgrade pip --quiet
& $python -m pip install -e ".[dev]" --quiet

Write-Host "Tests..."
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Les tests ont échoué" }

Write-Host "Génération de l'icône..."
& $python -m claude_tracker.render --ico assets\app.ico

Write-Host "Construction de l'exécutable..."
& $python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name ClaudeTracker `
    --icon assets\app.ico `
    --paths src `
    --collect-data customtkinter `
    --hidden-import pystray._win32 `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

Write-Host ""
Write-Host "OK -> dist\ClaudeTracker.exe" -ForegroundColor Green
