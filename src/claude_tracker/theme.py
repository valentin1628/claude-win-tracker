"""Thème clair ou sombre, d'après les réglages de Windows.

Windows a deux réglages distincts : le mode des applications (pour le popup) et
celui de la barre des tâches (pour que le chiffre de l'icône reste lisible).
"""

from __future__ import annotations

THEMES = ("auto", "dark", "light")
_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

try:
    import winreg
except ImportError:  # pas sous Windows
    winreg = None  # type: ignore[assignment]


def _read_flag(name: str) -> bool | None:
    if not winreg:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            return bool(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return None


def apps_light() -> bool:
    flag = _read_flag("AppsUseLightTheme")
    if flag is not None:
        return flag
    try:  # macOS / Linux : darkdetect est installé avec customtkinter
        import darkdetect

        return bool(darkdetect.isLight())
    except Exception:
        return False


def taskbar_light() -> bool:
    flag = _read_flag("SystemUsesLightTheme")
    return bool(flag) if flag is not None else False


def resolve(setting: str) -> str:
    """Réglage de l'appli ("auto", "dark", "light") -> palette à utiliser."""
    if setting == "light":
        return "light"
    if setting == "dark":
        return "dark"
    return "light" if apps_light() else "dark"
