"""Orchestration : Tk dans le thread principal, pystray et le polling à côté.

Les autres threads ne touchent jamais Tk directement : ils déposent des messages
dans une file que la boucle Tk consomme toutes les 100 ms.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable, Protocol

import customtkinter as ctk
import pystray

from . import APP_NAME, autostart, render
from .config import Config
from .formatting import tooltip
from .popup import UsagePopup
from .usage_client import UsageClient, UsageError, UsageSnapshot


def _same_window(a: datetime | None, b: datetime | None) -> bool:
    # resets_at peut varier de quelques secondes d'un appel à l'autre.
    if a is None or b is None:
        return a is b
    return abs((a - b).total_seconds()) < 600


class Fetcher(Protocol):
    def fetch(self) -> UsageSnapshot: ...


METRIC_LABELS = {"five_hour": "Session 5h", "seven_day": "Semaine", "max": "Le plus élevé"}


class TrayApp:
    def __init__(self, config: Config, fetcher: Fetcher | None = None) -> None:
        self.config = config
        self.fetcher = fetcher or UsageClient(auto_refresh_token=config.auto_refresh_token)
        self.snapshot: UsageSnapshot | None = None
        self.error: str | None = None
        self._notified: dict[str, tuple[datetime | None, set[int]]] = {}

        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.popup = UsagePopup(self.root, on_refresh=self.request_refresh)

        self.icon = pystray.Icon(
            "claude_usage", icon=render.tray_icon(None), title=tooltip(None), menu=self._build_menu()
        )

    # ------------------------------------------------------------- menu
    def _build_menu(self) -> pystray.Menu:
        def metric_item(key: str) -> pystray.MenuItem:
            return pystray.MenuItem(
                METRIC_LABELS[key],
                lambda: self._set_metric(key),
                checked=lambda _item: self.config.icon_metric == key,
                radio=True,
            )

        return pystray.Menu(
            pystray.MenuItem("Ouvrir", lambda: self._ui(self.popup.toggle), default=True),
            pystray.MenuItem("Rafraîchir", self.request_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("L'icône affiche", pystray.Menu(*(metric_item(k) for k in METRIC_LABELS))),
            pystray.MenuItem(
                "Lancer au démarrage",
                self._toggle_autostart,
                checked=lambda _item: autostart.is_enabled(),
                visible=autostart.supported(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", self.quit),
        )

    def _set_metric(self, key: str) -> None:
        self.config.icon_metric = key
        self.config.save()
        self._ui(self._apply_state)

    def _toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(not autostart.is_enabled())
        except OSError as exc:
            self.icon.notify(f"Impossible de modifier le démarrage auto : {exc}", APP_NAME)

    # ----------------------------------------------------------- threads
    def _ui(self, fn: Callable[[], None]) -> None:
        self._ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            fn()
        if not self._stop.is_set():
            self.root.after(100, self._drain_ui_queue)

    def request_refresh(self) -> None:
        self._wake.set()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self.fetcher.fetch()
            except UsageError as exc:
                self._ui(lambda msg=str(exc): self._on_error(msg))
            except Exception as exc:  # ne jamais tuer le thread de polling
                self._ui(lambda msg=f"Erreur inattendue : {exc}": self._on_error(msg))
            else:
                self._ui(lambda s=snapshot: self._on_snapshot(s))
            self._wake.wait(self.config.poll_seconds)
            self._wake.clear()

    # ------------------------------------------------------------- état
    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot, self.error = snapshot, None
        self._apply_state()
        self._maybe_notify(snapshot)

    def _on_error(self, message: str) -> None:
        self.error = message
        self._apply_state()

    def _icon_value(self) -> float | None:
        if not self.snapshot:
            return None
        s, w = self.snapshot.session, self.snapshot.weekly
        values = {
            "five_hour": s.utilization if s else None,
            "seven_day": w.utilization if w else None,
        }
        if self.config.icon_metric == "max":
            present = [v for v in values.values() if v is not None]
            return max(present) if present else None
        return values.get(self.config.icon_metric)

    def _apply_state(self) -> None:
        offline = self.error is not None
        self.icon.icon = render.tray_icon(self._icon_value(), offline=offline)
        self.icon.title = tooltip(self.snapshot, self.error)
        self.popup.update_state(self.snapshot, self.error)

    def _maybe_notify(self, snapshot: UsageSnapshot) -> None:
        """Un toast par seuil franchi, une seule fois par fenêtre de reset."""
        for window in (snapshot.session, snapshot.weekly):
            if window is None:
                continue
            reset_key, done = self._notified.get(window.key, (None, set()))
            if not _same_window(reset_key, window.resets_at):
                # Nouvelle fenêtre : on ignore les seuils déjà dépassés au démarrage.
                first_seen = window.key not in self._notified
                done = {t for t in self.config.notify_thresholds if first_seen and window.utilization >= t}
            for threshold in self.config.notify_thresholds:
                if window.utilization >= threshold and threshold not in done:
                    done.add(threshold)
                    self.icon.notify(
                        f"{window.label} : {round(window.utilization)} % utilisés", "Claude Usage"
                    )
            self._notified[window.key] = (window.resets_at, done)

    # --------------------------------------------------------- cycle de vie
    def run(self) -> None:
        self.icon.run_detached()
        threading.Thread(target=self._poll_loop, name="usage-poll", daemon=True).start()
        self.root.after(100, self._drain_ui_queue)
        self.root.mainloop()

    def quit(self) -> None:
        self._stop.set()
        self._wake.set()
        self.icon.stop()
        self._ui(self.root.quit)
