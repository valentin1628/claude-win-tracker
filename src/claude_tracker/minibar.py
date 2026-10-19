"""Mini-barre : un fin trait de couleur collé au-dessus de la barre des tâches.

Il se remplit selon le % affiché par l'icône. La fenêtre ignore les clics (on
clique « à travers ») et se cache quand une appli est en plein écran (jeu, vidéo).
"""

from __future__ import annotations

import sys
import tkinter as tk

from . import render

HEIGHT = 3
FULLSCREEN_CHECK_MS = 2000


def _work_area(win: tk.Misc) -> tuple[int, int, int, int]:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48


def _fullscreen_app_running() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (OSError, AttributeError):
        return False
    # 2 : appli plein écran, 3 : jeu Direct3D plein écran, 4 : mode présentation
    return state.value in (2, 3, 4)


def _make_click_through(win: tk.Misc) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    )


class MiniBar:
    def __init__(self, master: tk.Misc) -> None:
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.win, height=HEIGHT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.pct: float | None = None
        self.offline = False
        self.enabled = False
        self._job: str | None = None
        self._styled = False

    def set_value(self, pct: float | None, offline: bool) -> None:
        self.pct, self.offline = pct, offline
        if self.enabled:
            self._draw()

    def enable(self, on: bool) -> None:
        self.enabled = on
        if on:
            self._place()
            self._draw()
            self.win.deiconify()
            if not self._styled:
                self.win.update_idletasks()
                _make_click_through(self.win)
                self._styled = True
            self._tick()
        else:
            if self._job:
                self.win.after_cancel(self._job)
                self._job = None
            self.win.withdraw()

    def _place(self) -> None:
        left, top, right, bottom = _work_area(self.win)
        self.width = right - left
        self.win.geometry(f"{self.width}x{HEIGHT}+{left}+{bottom - HEIGHT}")

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        width = getattr(self, "width", self.win.winfo_width())
        c.configure(bg=render.TRACK, width=width)
        if self.pct is not None:
            color = render.GREY if self.offline else render.color_for(self.pct)
            c.create_rectangle(0, 0, width * min(self.pct, 100) / 100, HEIGHT, fill=color, width=0)

    def _tick(self) -> None:
        # Masquée pendant un plein écran ; sinon on la remet au premier plan et à sa place
        # (la barre des tâches a pu changer de taille).
        if _fullscreen_app_running():
            self.win.withdraw()
        else:
            self._place()
            self.win.deiconify()
            self.win.lift()
        self._job = self.win.after(FULLSCREEN_CHECK_MS, self._tick)

    def destroy(self) -> None:
        self.enable(False)
        self.win.destroy()
