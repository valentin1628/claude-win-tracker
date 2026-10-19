"""Lancement automatique à l'ouverture de session.

- Windows : clé HKCU\\...\\Run ;
- macOS : un LaunchAgent dans ~/Library/LaunchAgents (lu à la prochaine connexion).
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ClaudeUsageTray"
LAUNCH_AGENT_LABEL = "com.valentin1628.claudeusagetray"

try:
    import winreg
except ImportError:  # pas sous Windows
    winreg = None  # type: ignore[assignment]


def supported() -> bool:
    return winreg is not None or sys.platform == "darwin"


def label() -> str:
    return "Lancer à l'ouverture de session" if sys.platform == "darwin" else "Lancer au démarrage de Windows"


def _command() -> str:
    if getattr(sys, "frozen", False):  # exécutable PyInstaller
        return f'"{sys.executable}"'
    # En mode script : pythonw.exe pour éviter la console.
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{exe}" -m claude_tracker'


# ------------------------------------------------------------------ macOS
def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def mac_program_arguments(executable: str | None = None, frozen: bool | None = None) -> list[str]:
    executable = executable or sys.executable
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        # …/Claude Usage Tray.app/Contents/MacOS/Claude Usage Tray -> on lance le bundle avec open.
        exe = Path(executable)
        if len(exe.parents) >= 3 and exe.parents[2].suffix == ".app":
            return ["/usr/bin/open", "-a", str(exe.parents[2])]
        return [executable]
    return [executable, "-m", "claude_tracker"]


def launch_agent_plist() -> bytes:
    return plistlib.dumps({
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": mac_program_arguments(),
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    })


# ---------------------------------------------------------------- commun
def is_enabled() -> bool:
    if sys.platform == "darwin":
        return launch_agent_path().exists()
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    if sys.platform == "darwin":
        path = launch_agent_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(launch_agent_plist())
        else:
            path.unlink(missing_ok=True)
        return
    if not winreg:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
