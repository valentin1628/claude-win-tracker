"""Bouton « Se reconnecter » : ouvre un PowerShell qui lance Claude Code.

Au démarrage, Claude Code renouvelle le jeton s'il le peut, sinon il propose
de se connecter. Une fois la fenêtre fermée, l'appli se rafraîchit.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

INSTALL_CMD = "irm https://claude.ai/install.ps1 | iex"


def powershell_script(claude_found: bool) -> str:
    if claude_found:
        return (
            "Write-Host 'Claude Usage Tray : connexion a Claude Code' -ForegroundColor Cyan; "
            "Write-Host 'Si Claude Code demande de te connecter, choisis ton compte Claude (abonnement).'; "
            "Write-Host 'Une fois connecte, tape /exit puis ferme cette fenetre.'; "
            "Write-Host ''; "
            "claude"
        )
    return (
        "Write-Host 'Claude Code est introuvable sur ce PC.' -ForegroundColor Yellow; "
        "Write-Host 'Pour l installer, copie cette commande puis lance claude et tape /login :'; "
        f"Write-Host '  {INSTALL_CMD}' -ForegroundColor Cyan"
    )


def open_login_console() -> subprocess.Popen | None:
    """Ouvre une nouvelle console PowerShell. Renvoie le processus (None hors Windows)."""
    if sys.platform != "win32":
        return None
    script = powershell_script(shutil.which("claude") is not None)
    return subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
