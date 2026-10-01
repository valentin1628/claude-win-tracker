"""Lancement automatique avec Windows (clé HKCU\\...\\Run). Sans effet ailleurs."""

from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ClaudeUsageTray"

try:
    import winreg
except ImportError:  # pas sous Windows
    winreg = None  # type: ignore[assignment]


def supported() -> bool:
    return winreg is not None


def _command() -> str:
    if getattr(sys, "frozen", False):  # exécutable PyInstaller
        return f'"{sys.executable}"'
    # En mode script : pythonw.exe pour éviter la console.
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{exe}" -m claude_tracker'


def is_enabled() -> bool:
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
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
