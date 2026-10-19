"""Mini-fenêtre sombre qui s'ouvre au-dessus de la zone de notification."""

from __future__ import annotations

import logging
import sys
import time
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from . import render
from .formatting import ago_text, cost_text, plan_label, reset_text
from .usage_client import UsageSnapshot, UsageWindow

GAUGE_PX = 112  # taille logique d'une jauge (customtkinter gère le DPI)
MARGIN = 12  # distance au bord de la zone de travail (px physiques)


def _work_area(win: ctk.CTkToplevel) -> tuple[int, int, int, int]:
    """Zone de l'écran hors barre des tâches : (gauche, haut, droite, bas)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48


def _round_corners(win: ctk.CTkToplevel) -> None:
    """Coins arrondis natifs de Windows 11 (ignoré ailleurs)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND)
        )
    except (OSError, AttributeError):
        pass


class GaugeCard(ctk.CTkFrame):
    def __init__(self, master, title: str) -> None:
        super().__init__(master, fg_color=render.CARD, corner_radius=14)
        self.image_label = ctk.CTkLabel(self, text="")
        self.image_label.pack(padx=16, pady=(16, 6))
        self.title_label = ctk.CTkLabel(
            self, text=title, text_color=render.TEXT, font=ctk.CTkFont(size=13, weight="bold")
        )
        self.title_label.pack()
        self.reset_label = ctk.CTkLabel(
            self, text="", text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=11), height=18
        )
        self.reset_label.pack()
        self.forecast_label = ctk.CTkLabel(
            self, text=" ", text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=11), height=16
        )
        self.forecast_label.pack(pady=(0, 10))
        self.set(None, offline=False)

    def set_forecast(self, text: str) -> None:
        self.forecast_label.configure(text=text or " ")

    def set(self, window: UsageWindow | None, offline: bool) -> None:
        pct = window.utilization if window else None
        img = render.gauge(pct, size=GAUGE_PX * 2, offline=offline)
        self._image = ctk.CTkImage(light_image=img, dark_image=img, size=(GAUGE_PX, GAUGE_PX))
        self.image_label.configure(image=self._image)
        self.reset_label.configure(text=reset_text(window) or " ")


class DetailsPanel(ctk.CTkFrame):
    """Volet « Détails » : courbe 24 h, barres par jour, coût équivalent API."""

    WIDTH = 300

    def __init__(self, master) -> None:
        super().__init__(master, fg_color=render.CARD, corner_radius=14)
        muted = {"text_color": render.TEXT_MUTED, "font": ctk.CTkFont(size=11)}
        ctk.CTkLabel(self, text="Session 5h · dernières 24 h", anchor="w", **muted).pack(fill="x", padx=14, pady=(10, 0))
        self.spark = ctk.CTkLabel(self, text="")
        self.spark.pack(padx=14, pady=(2, 6))
        ctk.CTkLabel(self, text="Semaine · consommation par jour (%)", anchor="w", **muted).pack(fill="x", padx=14)
        self.bars = ctk.CTkLabel(self, text="")
        self.bars.pack(padx=14, pady=(2, 8))
        ctk.CTkLabel(self, text="Coût équivalent API (Claude Code)", anchor="w", **muted).pack(fill="x", padx=14)
        self.cost = ctk.CTkLabel(
            self, text="", text_color=render.TEXT, font=ctk.CTkFont(size=12, weight="bold"), justify="left", anchor="w"
        )
        self.cost.pack(fill="x", padx=14)
        ctk.CTkLabel(
            self, text="Au tarif public de l'API. claude.ai et Claude Desktop ne sont pas comptés.",
            anchor="w", wraplength=self.WIDTH - 10, justify="left", text_color=render.TEXT_MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=14, pady=(0, 10))
        self._images: list = []

    def update_data(self, series, start: float, end: float, days, cost_summary) -> None:
        w = self.WIDTH - 28
        spark = render.sparkline(series, start, end, width=w * 2, height=64 * 2)
        bars = render.day_bars(days, width=w * 2, height=78 * 2)
        self._images = [
            ctk.CTkImage(light_image=spark, dark_image=spark, size=(w, 64)),
            ctk.CTkImage(light_image=bars, dark_image=bars, size=(w, 78)),
        ]
        self.spark.configure(image=self._images[0])
        self.bars.configure(image=self._images[1])
        self.cost.configure(text=cost_text(cost_summary))


class ExtraRow(ctk.CTkFrame):
    """Ligne discrète pour Opus/Sonnet hebdo : libellé, barre fine, %."""

    def __init__(self, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.label = ctk.CTkLabel(self, text="", text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=11))
        self.label.pack(side="left")
        self.value = ctk.CTkLabel(self, text="", text_color=render.TEXT, font=ctk.CTkFont(size=11, weight="bold"))
        self.value.pack(side="right")
        self.bar = ctk.CTkProgressBar(self, height=4, corner_radius=2, fg_color=render.TRACK, width=110)
        self.bar.pack(side="right", padx=10)

    def set(self, window: UsageWindow) -> None:
        self.label.configure(text=window.label)
        self.value.configure(text=f"{round(window.utilization)} %")
        self.bar.configure(progress_color=render.color_for(window.utilization))
        self.bar.set(min(window.utilization, 100) / 100)


class UsagePopup(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        on_refresh: Callable[[], None],
        on_login: Callable[[], None] | None = None,
        on_details: Callable[[bool], None] | None = None,
        details_open: bool = False,
    ) -> None:
        super().__init__(master, fg_color=render.BG)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self._on_refresh = on_refresh
        self._on_login = on_login
        self._on_details = on_details
        self._details_open = details_open
        self._snapshot: UsageSnapshot | None = None
        self._notice: str | None = None
        self._hidden_at = 0.0
        self._tick_job: str | None = None
        # macOS : renvoie (centre x, bas) de l'icône de la barre de menus, pour ouvrir juste dessous.
        self.anchor: Callable[[], tuple[float, float] | None] | None = None

        radius = 0
        if sys.platform == "darwin":
            # Fenêtre transparente + cadre arrondi : un panneau aux coins arrondis, comme un popover.
            try:
                self.attributes("-transparent", True)
                tk.Toplevel.configure(self, bg="systemTransparent")
                radius = 14
            except tk.TclError:
                pass
        outer = ctk.CTkFrame(self, fg_color=render.BG, corner_radius=radius,
                             bg_color="systemTransparent" if radius else "transparent")
        outer.pack(fill="both", expand=True)
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=14)

        # En-tête
        header = ctk.CTkFrame(body, fg_color="transparent")
        header.pack(fill="x")
        self.dot = ctk.CTkLabel(header, text="●", text_color=render.ACCENT, font=ctk.CTkFont(size=12), width=14)
        self.dot.pack(side="left")
        self.plan_label = ctk.CTkLabel(
            header, text="Claude", text_color=render.TEXT, font=ctk.CTkFont(size=15, weight="bold")
        )
        self.plan_label.pack(side="left", padx=(6, 0))
        self.demo_badge = ctk.CTkLabel(
            header, text=" DÉMO ", fg_color=render.ACCENT, text_color=render.BG, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"), height=18,
        )
        self.refresh_btn = ctk.CTkButton(
            header, text="⟳", width=30, height=28, corner_radius=8, fg_color="transparent",
            hover_color=render.CARD, text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=16),
            command=self._refresh_clicked,
        )
        self.refresh_btn.pack(side="right")

        # Jauges
        self._gauges = gauges = ctk.CTkFrame(body, fg_color="transparent")
        gauges.pack(fill="x", pady=(12, 0))
        self.session_card = GaugeCard(gauges, "Session 5h")
        self.session_card.pack(side="left", expand=True, fill="both", padx=(0, 6))
        self.weekly_card = GaugeCard(gauges, "Semaine")
        self.weekly_card.pack(side="left", expand=True, fill="both", padx=(6, 0))

        # Packé seulement s'il y a des lignes : un CTkFrame vide fait 200 px de haut.
        self.extras_frame = ctk.CTkFrame(body, fg_color="transparent")
        self._extra_rows: list[ExtraRow] = []

        self.message = ctk.CTkLabel(
            body, text="", text_color=render.ORANGE, font=ctk.CTkFont(size=11), wraplength=300, justify="left"
        )

        self.login_btn = ctk.CTkButton(
            body, text="Se reconnecter à Claude", height=32, corner_radius=8,
            fg_color=render.ACCENT, hover_color="#C4654A", text_color=render.BG,
            font=ctk.CTkFont(size=12, weight="bold"), command=self._login_clicked,
        )

        # Volet « Détails » (fermé par défaut)
        self.details_btn = ctk.CTkButton(
            body, text="", height=26, corner_radius=8, fg_color="transparent", hover_color=render.CARD,
            text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=12), command=self._toggle_details,
        )
        self.details_btn.pack(fill="x", pady=(8, 0))
        self.details = DetailsPanel(body)

        # Pied de page
        self.footer = ctk.CTkLabel(body, text="", text_color=render.TEXT_MUTED, font=ctk.CTkFont(size=11), wraplength=300)
        self.footer.pack(fill="x", pady=(10, 0))

        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Escape>", lambda _e: self.hide())

    # ------------------------------------------------------------------ état
    def update_state(
        self,
        snapshot: UsageSnapshot | None,
        error: str | None,
        show_login: bool = False,
        notice: str | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._notice = notice
        offline = error is not None
        self.plan_label.configure(text=plan_label(snapshot.plan if snapshot else None))
        if snapshot and snapshot.demo:
            self.demo_badge.pack(side="left", padx=(8, 0))
        else:
            self.demo_badge.pack_forget()
        self.dot.configure(text_color=render.GREY if offline or not snapshot else render.ACCENT)
        self.session_card.set(snapshot.session if snapshot else None, offline)
        self.weekly_card.set(snapshot.weekly if snapshot else None, offline)

        extras = snapshot.extras if snapshot else []
        while len(self._extra_rows) < len(extras):
            self._extra_rows.append(ExtraRow(self.extras_frame))
        for row, window in zip(self._extra_rows, extras):
            row.set(window)
            row.pack(fill="x", pady=(8, 0))
        for row in self._extra_rows[len(extras):]:
            row.pack_forget()
        if extras:
            self.extras_frame.pack(fill="x", after=self._gauges)
        else:
            self.extras_frame.pack_forget()

        # Retirés puis remis dans l'ordre : message, bouton, pied de page.
        self.message.pack_forget()
        self.login_btn.pack_forget()
        if error:
            self.message.configure(text=f"⚠ {error}")
            self.message.pack(fill="x", pady=(10, 0), before=self.details_btn)
        if show_login and self._on_login:
            self.login_btn.pack(fill="x", pady=(10, 0), before=self.details_btn)
        self._apply_details_visibility()
        self._update_footer()

    def update_extras(self, forecasts: dict[str, str], details: tuple | None) -> None:
        """Prévisions sous les jauges et contenu du volet Détails."""
        self.session_card.set_forecast(forecasts.get("five_hour", ""))
        self.weekly_card.set_forecast(forecasts.get("seven_day", ""))
        if details is not None:
            self.details.update_data(*details)

    def _toggle_details(self) -> None:
        self._details_open = not self._details_open
        self._apply_details_visibility()
        if self._on_details:
            self._on_details(self._details_open)
        if self.winfo_viewable():
            self._reposition()

    def _apply_details_visibility(self) -> None:
        self.details_btn.configure(text="Détails ▴" if self._details_open else "Détails ▾")
        if self._details_open:
            self.details.pack(fill="x", pady=(4, 0), after=self.details_btn)
        else:
            self.details.pack_forget()

    def _update_footer(self) -> None:
        text = ago_text(self._snapshot.fetched_at if self._snapshot else None)
        if self._notice:
            text += f"\n{self._notice}"
        self.footer.configure(text=text)

    def _tick(self) -> None:
        # Rafraîchit les comptes à rebours tant que la fenêtre est visible.
        self._update_footer()
        if self._snapshot:
            self.session_card.reset_label.configure(text=reset_text(self._snapshot.session) or " ")
            self.weekly_card.reset_label.configure(text=reset_text(self._snapshot.weekly) or " ")
        self._tick_job = self.after(15_000, self._tick)

    def _login_clicked(self) -> None:
        self.footer.configure(text="Fenêtre de connexion ouverte…")
        if self._on_login:
            self._on_login()

    def _refresh_clicked(self) -> None:
        self.footer.configure(text="Actualisation…")
        self._on_refresh()

    # ------------------------------------------------------- affichage
    def toggle(self) -> None:
        if self.winfo_viewable():
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.35:
            # Le clic sur l'icône retire le focus juste avant : on évite de rouvrir aussitôt.
            self.show()

    def _reposition(self) -> None:
        """Ancre la fenêtre en bas à droite, au-dessus de la barre des tâches."""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        point = self.anchor() if self.anchor else None
        if point:  # macOS : centré sous l'icône de la barre de menus
            screen_w = self.winfo_screenwidth()
            x = min(max(8, int(point[0] - w / 2)), screen_w - w - 8)
            self.geometry(f"+{x}+{int(point[1]) + 6}")
            return
        left, top, right, bottom = _work_area(self)
        self.geometry(f"+{right - w - MARGIN}+{max(top, bottom - h - MARGIN)}")

    def show(self) -> None:
        logging.getLogger("claude_tracker").info("Popup affiché")
        self._reposition()
        self.deiconify()
        self.lift()
        _round_corners(self)
        if sys.platform == "darwin":
            from .mac_status import activate_app

            activate_app()  # une appli de barre de menus doit s'activer pour passer devant
        self.after(10, self.focus_force)
        if self._tick_job is None:
            self._tick()

    def hide(self) -> None:
        logging.getLogger("claude_tracker").info("Popup masqué")
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        self._hidden_at = time.monotonic()
        self.withdraw()

    def _focus_out(self, event) -> None:
        if event.widget is not self:
            return
        # Laisse le temps au focus d'arriver sur un widget enfant.
        self.after(120, self._hide_if_unfocused)

    def _hide_if_unfocused(self) -> None:
        try:
            focused = self.focus_get()
        except KeyError:  # focus sur un widget Tk interne (menu…)
            focused = None
        if focused is None and self.winfo_viewable():
            self.hide()
