"""Raccourci clavier global (Windows) : RegisterHotKey dans un thread dédié.

Le thread tourne sa propre boucle de messages Windows ; sur appui, il appelle le
callback (qui doit repasser par la file Tk de l'appli).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

MODIFIERS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 0xC1A0


class HotkeyError(ValueError):
    pass


def parse(text: str) -> tuple[int, int]:
    """« Ctrl+Alt+C » -> (modificateurs, code de touche virtuelle)."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if len(parts) < 2:
        raise HotkeyError("Il faut au moins une touche de contrôle et une touche, ex. Ctrl+Alt+C")
    *mods, key = parts
    flags = 0
    for mod in mods:
        if mod not in MODIFIERS:
            raise HotkeyError(f"Touche de contrôle inconnue : {mod}")
        flags |= MODIFIERS[mod]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise HotkeyError(f"Touche non prise en charge : {key} (lettre, chiffre ou F1-F24)")
    return flags, vk


def normalize(text: str) -> str:
    """Remet en forme : « ctrl + alt + c » -> « Ctrl+Alt+C »."""
    parse(text)
    parts = [p.strip() for p in text.replace(" ", "").split("+")]
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in parts)


def supported() -> bool:
    return sys.platform == "win32"


class GlobalHotkey:
    def __init__(self, text: str, callback: Callable[[], None]) -> None:
        self.text = text
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.error: str | None = None

    def start(self) -> bool:
        """Enregistre le raccourci. False si la combinaison est déjà prise (error renseigné)."""
        if not supported():
            return False
        mods, vk = parse(self.text)
        self._thread = threading.Thread(target=self._run, args=(mods, vk), name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.error is None

    def _run(self, mods: int, vk: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            self.error = f"Le raccourci {self.text} est déjà utilisé par une autre appli"
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.callback()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._thread = None
