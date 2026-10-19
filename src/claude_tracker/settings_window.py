"""Fenêtre « Réglages » : tout ce qu'on pouvait faire dans config.json, en clics.

Chaque changement est enregistré tout de suite (Config.save) puis signalé à l'appli
via on_change(nom_du_réglage), qui l'applique sans redémarrage.
"""

from __future__ import annotations

import contextlib
import io
import threading
from typing import Callable

import customtkinter as ctk

from . import APP_NAME, __version__, autostart, hotkey, updater
from .config import Config
from .render import PALETTES

# Couleurs (clair, sombre) : customtkinter choisit selon le thème actif, en direct.
ACCENT = (PALETTES["light"]["ACCENT"], PALETTES["dark"]["ACCENT"])
ACCENT_HOVER = ("#B4573A", "#C4654A")
MUTED = (PALETTES["light"]["TEXT_MUTED"], PALETTES["dark"]["TEXT_MUTED"])
CARD = (PALETTES["light"]["CARD"], PALETTES["dark"]["CARD"])

INTERVALS = {"5 min": 300, "10 min": 600, "15 min": 900, "30 min": 1800}
METRICS = {"Session 5h": "five_hour", "Semaine": "seven_day", "Le plus élevé": "max"}
THEMES = {"Auto": "auto", "Sombre": "dark", "Clair": "light"}
THRESHOLDS = (50, 75, 80, 90, 95, 100)


def _key_for(mapping: dict, value) -> str:
    return next((k for k, v in mapping.items() if v == value), next(iter(mapping)))


class SettingsWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        config: Config,
        on_change: Callable[[str], None],
        post_ui: Callable[[Callable[[], None]], None],
        test_notification: Callable[[], None],
        check_updates: Callable[[], None],
        run_diagnostic: Callable[[], int],
    ) -> None:
        super().__init__(master)
        self.title(f"Réglages - {APP_NAME}")
        self.geometry("480x560")
        self.resizable(False, False)
        self.config_ = config
        self._on_change = on_change
        self._post_ui = post_ui
        self._test_notification = test_notification
        self._check_updates = check_updates
        self._run_diagnostic = run_diagnostic

        tabs = ctk.CTkTabview(self, segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color=ACCENT_HOVER)
        tabs.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self._general(tabs.add("Général"))
        self._notifications(tabs.add("Notifications"))
        self._connection(tabs.add("Connexion"))
        self._updates(tabs.add("Mises à jour"))
        self.after(50, self.focus_force)

    # ------------------------------------------------------------ outils
    def _set(self, attr: str, value) -> None:
        setattr(self.config_, attr, value)
        self.config_.normalized()
        self.config_.save()
        self._on_change(attr)

    def _row(self, parent, label: str, hint: str = "") -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text, text=label, anchor="w", font=ctk.CTkFont(size=13)).pack(fill="x")
        if hint:
            ctk.CTkLabel(text, text=hint, anchor="w", justify="left", wraplength=260, text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(fill="x")
        return row

    def _switch(self, parent, label: str, attr: str, hint: str = "") -> ctk.CTkSwitch:
        row = self._row(parent, label, hint)
        var = ctk.BooleanVar(value=getattr(self.config_, attr))
        sw = ctk.CTkSwitch(row, text="", variable=var, progress_color=ACCENT, width=46,
                           command=lambda: self._set(attr, var.get()))
        sw.pack(side="right")
        return sw

    def _segmented(self, parent, label: str, attr: str, mapping: dict) -> None:
        row = self._row(parent, label)
        var = ctk.StringVar(value=_key_for(mapping, getattr(self.config_, attr)))
        ctk.CTkSegmentedButton(
            row, values=list(mapping), variable=var, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            command=lambda choice: self._set(attr, mapping[choice]),
        ).pack(side="right")

    # ------------------------------------------------------------ onglets
    def _general(self, tab) -> None:
        row = self._row(tab, "Actualisation", "Plus souvent, Anthropic risque de répondre « trop de requêtes ».")
        var = ctk.StringVar(value=_key_for(INTERVALS, self.config_.poll_seconds))
        ctk.CTkOptionMenu(row, values=list(INTERVALS), variable=var, width=100, fg_color=ACCENT,
                          button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER,
                          command=lambda c: self._set("poll_seconds", INTERVALS[c])).pack(side="right")

        self._segmented(tab, "L'icône affiche", "icon_metric", METRICS)
        self._segmented(tab, "Thème", "theme", THEMES)

        if autostart.supported():
            row = self._row(tab, "Lancer au démarrage de Windows")
            auto_var = ctk.BooleanVar(value=autostart.is_enabled())

            def toggle_autostart() -> None:
                try:
                    autostart.set_enabled(auto_var.get())
                except OSError:
                    auto_var.set(autostart.is_enabled())

            ctk.CTkSwitch(row, text="", variable=auto_var, progress_color=ACCENT, width=46,
                          command=toggle_autostart).pack(side="right")

        if hotkey.supported():
            self._switch(tab, "Raccourci clavier", "hotkey_enabled", "Ouvre ou ferme la fenêtre depuis n'importe où.")
            row = ctk.CTkFrame(tab, fg_color="transparent")
            row.pack(fill="x", pady=(6, 0))
            entry = ctk.CTkEntry(row, width=160)
            entry.insert(0, self.config_.hotkey)
            entry.pack(side="left")
            status = ctk.CTkLabel(row, text="", text_color=MUTED, font=ctk.CTkFont(size=11))

            def apply_hotkey() -> None:
                try:
                    value = hotkey.normalize(entry.get())
                except hotkey.HotkeyError as exc:
                    status.configure(text=str(exc))
                    return
                entry.delete(0, "end")
                entry.insert(0, value)
                status.configure(text="Enregistré ✓")
                self._set("hotkey", value)

            ctk.CTkButton(row, text="Appliquer", width=90, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=apply_hotkey).pack(side="left", padx=8)
            status.pack(side="left")

            self._switch(tab, "Mini-barre", "minibar",
                         "Un fin trait coloré au-dessus de la barre des tâches, qui se remplit avec le %.")

    def _notifications(self, tab) -> None:
        self._switch(tab, "Notifications activées", "notifications_enabled")
        ctk.CTkLabel(tab, text="Paliers", anchor="w", font=ctk.CTkFont(size=13)).pack(fill="x", pady=(12, 0))
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x")
        for i, t in enumerate(THRESHOLDS):
            var = ctk.BooleanVar(value=t in self.config_.notify_thresholds)

            def toggle(t=t, var=var) -> None:
                current = set(self.config_.notify_thresholds)
                current.add(t) if var.get() else current.discard(t)
                self._set("notify_thresholds", tuple(sorted(current)))

            ctk.CTkCheckBox(grid, text=f"{t} %", variable=var, command=toggle, width=90,
                            fg_color=ACCENT, hover_color=ACCENT_HOVER).grid(row=i // 3, column=i % 3, sticky="w", pady=4)
        self._switch(tab, "Pour la session 5h", "notify_session")
        self._switch(tab, "Pour la semaine", "notify_weekly")
        self._switch(tab, "Quand la session est rechargée", "notify_recharge")
        self._switch(tab, "Si la limite approche à ce rythme", "notify_forecast",
                     "Moins de 45 min avant la limite (session) ou 24 h (semaine).")
        ctk.CTkButton(tab, text="Tester une notification", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._test_notification).pack(anchor="w", pady=(16, 0))

    def _connection(self, tab) -> None:
        self._switch(tab, "Renouveler la connexion automatiquement", "auto_refresh_token",
                     "Comme Claude Code : quand le jeton expire, l'appli en demande un nouveau en silence.")
        out = ctk.CTkTextbox(tab, height=230, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        btn = ctk.CTkButton(tab, text="Tester la connexion", fg_color=ACCENT, hover_color=ACCENT_HOVER)

        def run() -> None:
            btn.configure(state="disabled", text="Test en cours…")
            out.delete("1.0", "end")

            def work() -> None:
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    try:
                        self._run_diagnostic()
                    except Exception as exc:  # le test ne doit jamais faire planter l'appli
                        print(f"[ KO ] Erreur inattendue : {exc}")
                self._post_ui(lambda: done(buffer.getvalue()))

            def done(text: str) -> None:
                if not self.winfo_exists():
                    return
                out.insert("end", text)
                btn.configure(state="normal", text="Tester la connexion")

            threading.Thread(target=work, name="settings-check", daemon=True).start()

        btn.configure(command=run)
        btn.pack(anchor="w", pady=(16, 8))
        out.pack(fill="both", expand=True)

    def _updates(self, tab) -> None:
        ctk.CTkLabel(tab, text=f"Version installée : {__version__}", anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(10, 0))
        if not updater.updates_supported():
            ctk.CTkLabel(tab, text="Lancée depuis le code source : mets à jour avec « git pull ».",
                         anchor="w", text_color=MUTED).pack(fill="x", pady=(6, 0))
            return
        self._switch(tab, "Rechercher les mises à jour automatiquement", "check_updates",
                     "Au démarrage puis toutes les 12 h, sur les releases GitHub.")
        ctk.CTkButton(tab, text="Rechercher maintenant", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._check_updates).pack(anchor="w", pady=(16, 0))
