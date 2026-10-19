"""Bouton « Se reconnecter » : ouvre un PowerShell (macOS : le Terminal) qui lance Claude Code.

Au démarrage, Claude Code renouvelle le jeton s'il le peut, sinon il propose
de se connecter. Une fois la fenêtre fermée, l'appli se rafraîchit.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

INSTALL_CMD = "irm https://claude.ai/install.ps1 | iex"
MAC_INSTALL_CMD = "curl -fsSL https://claude.ai/install.sh | bash"


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


def terminal_command() -> str:
    """Commande shell tapée dans le Terminal (son PATH est celui de l'utilisateur, pas celui de l'appli)."""
    return (
        "clear; echo 'Claude Usage Tray : connexion a Claude Code'; "
        "if command -v claude >/dev/null 2>&1; then "
        "echo 'Si Claude Code demande de te connecter, choisis ton compte Claude (abonnement).'; "
        "echo 'Une fois connecte, tape /exit puis ferme cette fenetre.'; echo; claude; "
        "else echo 'Claude Code est introuvable sur ce Mac. Pour l installer, copie cette commande :'; "
        f"echo '  {MAC_INSTALL_CMD}'; echo 'puis lance claude et tape /login.'; fi"
    )


def osascript_args(command: str) -> list[str]:
    quoted = command.replace("\\", "\\\\").replace('"', '\\"')
    return [
        "/usr/bin/osascript",
        "-e", f'tell application "Terminal" to do script "{quoted}"',
        "-e", 'tell application "Terminal" to activate',
    ]


def open_login_console() -> subprocess.Popen | None:
    """Ouvre une nouvelle console. Renvoie le processus (None si le système n'est pas géré).

    Sur macOS, le processus (osascript) se termine dès que le Terminal est ouvert.
    """
    if sys.platform == "darwin":
        return subprocess.Popen(osascript_args(terminal_command()))
    if sys.platform != "win32":
        return None
    script = powershell_script(shutil.which("claude") is not None)
    return subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
