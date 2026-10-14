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

from . import APP_NAME, __version__, autostart, login, render, updater
from .config import Config
from .formatting import reset_clock, tooltip
from .popup import UsagePopup
from .usage_client import CredentialsNotFound, NetworkError, TokenExpired, UsageClient, UsageError, UsageSnapshot


def _same_window(a: datetime | None, b: datetime | None) -> bool:
    # resets_at peut varier de quelques secondes d'un appel à l'autre.
    if a is None or b is None:
        return a is b
    return abs((a - b).total_seconds()) < 600


def threshold_message(window, threshold: int) -> str:
    clock = reset_clock(window)
    when = f" · reset à {clock}" if clock else ""
    if threshold >= 100:
        return f"{window.label} : quota atteint{when}"
    return f"{window.label} : {round(window.utilization)} % utilisés{when}"


class Fetcher(Protocol):
    def fetch(self) -> UsageSnapshot: ...


METRIC_LABELS = {"five_hour": "Session 5h", "seven_day": "Semaine", "max": "Le plus élevé"}
THRESHOLD_CHOICES = (50, 75, 80, 90, 95, 100)
# Après une coupure réseau (ex. juste après le démarrage de Windows) : nouveaux essais rapprochés.
NETWORK_RETRY_DELAYS = (15, 30)
RECHARGE_MIN_PCT = 50  # « session rechargée » seulement si on l'avait bien entamée


class TrayApp:
    def __init__(self, config: Config, fetcher: Fetcher | None = None) -> None:
        self.config = config
        self.fetcher = fetcher or UsageClient(auto_refresh_token=config.auto_refresh_token)
        self.snapshot: UsageSnapshot | None = None
        self.error: str | None = None
        self.auth_error = False  # jeton expiré/absent : on propose de se reconnecter
        self._login_running = False
        # Par fenêtre : (date de reset, dernier % vu) pour détecter les franchissements de palier.
        self._last_seen: dict[str, tuple[datetime | None, float]] = {}
        self.update_info: updater.UpdateInfo | None = None
        self._update_notified: str | None = None
        self._update_wake = threading.Event()
        self._installing = False
        self._manual_check = False

        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.popup = UsagePopup(self.root, on_refresh=self.request_refresh, on_login=self.open_login)

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
            pystray.MenuItem(
                "Se reconnecter à Claude…", self.open_login, visible=lambda _item: self.auth_error
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("L'icône affiche", pystray.Menu(*(metric_item(k) for k in METRIC_LABELS))),
            pystray.MenuItem("Notifications", self._notifications_menu()),
            pystray.MenuItem(
                "Lancer au démarrage",
                self._toggle_autostart,
                checked=lambda _item: autostart.is_enabled(),
                visible=autostart.supported(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _item: f"Installer la mise à jour v{self.update_info.version}" if self.update_info else "",
                self._install_update,
                visible=lambda _item: self.update_info is not None,
            ),
            pystray.MenuItem(
                "Rechercher les mises à jour",
                self._check_updates_now,
                visible=updater.updates_supported(),
            ),
            pystray.MenuItem("Quitter", self.quit),
        )

    def _notifications_menu(self) -> pystray.Menu:
        cfg = self.config
        on = lambda _item: cfg.notifications_enabled  # noqa: E731

        def threshold_item(t: int) -> pystray.MenuItem:
            return pystray.MenuItem(
                f"À {t} %",
                lambda: self._toggle_threshold(t),
                checked=lambda _item: t in cfg.notify_thresholds,
                enabled=on,
            )

        def flag_item(label: str, attr: str) -> pystray.MenuItem:
            return pystray.MenuItem(
                label, lambda: self._toggle_flag(attr), checked=lambda _item: getattr(cfg, attr), enabled=on
            )

        return pystray.Menu(
            pystray.MenuItem(
                "Activées", lambda: self._toggle_flag("notifications_enabled"),
                checked=lambda _item: cfg.notifications_enabled,
            ),
            pystray.Menu.SEPARATOR,
            *(threshold_item(t) for t in THRESHOLD_CHOICES),
            pystray.Menu.SEPARATOR,
            flag_item("Pour la session 5h", "notify_session"),
            flag_item("Pour la semaine", "notify_weekly"),
            flag_item("Quand la session est rechargée", "notify_recharge"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Tester une notification", self._test_notification),
        )

    def _toggle_threshold(self, t: int) -> None:
        current = set(self.config.notify_thresholds)
        current.symmetric_difference_update({t})
        self.config.notify_thresholds = tuple(sorted(current))
        self.config.save()

    def _toggle_flag(self, attr: str) -> None:
        setattr(self.config, attr, not getattr(self.config, attr))
        self.config.save()

    def _test_notification(self) -> None:
        self.icon.notify("Session 5h : 80 % utilisés · reset à 16:30 (exemple)", APP_NAME)

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
        # Toujours replanifié : root.quit() peut arriver après _stop.set().
        self.root.after(100, self._drain_ui_queue)

    def request_refresh(self) -> None:
        self._wake.set()

    def _poll_loop(self) -> None:
        network_failures = 0
        while not self._stop.is_set():
            network_failures = self._poll_once(network_failures)
            self._wake.wait(self.next_delay(network_failures))
            self._wake.clear()

    def _poll_once(self, network_failures: int) -> int:
        """Un relevé. Renvoie le nombre d'erreurs réseau consécutives."""
        try:
            snapshot = self.fetcher.fetch()
        except (TokenExpired, CredentialsNotFound) as exc:
            self._ui(lambda msg=str(exc): self._on_error(msg, auth=True))
        except NetworkError as exc:
            self._ui(lambda msg=str(exc): self._on_error(msg))
            return network_failures + 1
        except UsageError as exc:
            self._ui(lambda msg=str(exc): self._on_error(msg))
        except Exception as exc:  # ne jamais tuer le thread de polling
            self._ui(lambda msg=f"Erreur inattendue : {exc}": self._on_error(msg))
        else:
            self._ui(lambda s=snapshot: self._on_snapshot(s))
        return 0

    def next_delay(self, network_failures: int) -> float:
        if 0 < network_failures <= len(NETWORK_RETRY_DELAYS):
            return min(NETWORK_RETRY_DELAYS[network_failures - 1], self.config.poll_seconds)
        return self.config.poll_seconds

    # ------------------------------------------------------ mises à jour
    UPDATE_FIRST_DELAY = 30
    UPDATE_INTERVAL = 12 * 3600

    def _update_loop(self) -> None:
        self._update_wake.wait(self.UPDATE_FIRST_DELAY)
        while not self._stop.is_set():
            self._update_wake.clear()
            manual, self._manual_check = self._manual_check, False
            info = updater.check_latest()
            self._ui(lambda i=info, m=manual: self._on_update_checked(i, m))
            self._update_wake.wait(self.UPDATE_INTERVAL)

    def _check_updates_now(self) -> None:
        self._manual_check = True
        self._update_wake.set()

    def _on_update_checked(self, info: updater.UpdateInfo | None, manual: bool = False) -> None:
        self.update_info = info
        self.icon.update_menu()
        if manual and info is None:
            self.icon.notify(f"Tu as déjà la dernière version ({__version__}).", APP_NAME)
        if info and self._update_notified != info.version:
            self._update_notified = info.version
            self.icon.notify(
                f"La version {info.version} est disponible. Clic droit sur l'icône pour l'installer.",
                APP_NAME,
            )

    def _install_update(self) -> None:
        info = self.update_info
        if info is None or self._installing:
            return
        self._installing = True

        def work() -> None:
            try:
                self.icon.notify(f"Téléchargement de la version {info.version}…", APP_NAME)
                setup = updater.download(info)
                updater.launch_installer(setup)
            except (updater.UpdateError, OSError) as exc:
                self._installing = False
                self.icon.notify(f"Mise à jour impossible : {exc}", APP_NAME)
                return
            # L'installeur remplace les fichiers puis relance l'appli.
            self.quit()

        threading.Thread(target=work, name="update-install", daemon=True).start()

    # ------------------------------------------------------- connexion
    def open_login(self) -> None:
        """Ouvre un PowerShell avec Claude Code, puis rafraîchit quand il est fermé."""
        if self._login_running:
            return
        try:
            proc = login.open_login_console()
        except OSError as exc:
            self.icon.notify(f"Impossible d'ouvrir PowerShell : {exc}", APP_NAME)
            return
        if proc is None:
            return
        self._login_running = True

        def wait() -> None:
            proc.wait()
            self._login_running = False
            self.request_refresh()

        threading.Thread(target=wait, name="login-wait", daemon=True).start()

    # ------------------------------------------------------------- état
    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot, self.error, self.auth_error = snapshot, None, False
        self.icon.update_menu()
        self._apply_state()
        self._maybe_notify(snapshot)

    def _on_error(self, message: str, auth: bool = False) -> None:
        self.error, self.auth_error = message, auth
        self.icon.update_menu()
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
        self.popup.update_state(self.snapshot, self.error, show_login=self.auth_error)

    def _maybe_notify(self, snapshot: UsageSnapshot) -> None:
        """Notifie quand un palier est franchi entre deux relevés (et au rechargement).

        Au premier relevé, les paliers déjà dépassés ne déclenchent rien : pas de
        rafale au démarrage, ni en réactivant les notifications ou en ajoutant un palier.
        """
        cfg = self.config
        wanted = {"five_hour": cfg.notify_session, "seven_day": cfg.notify_weekly}
        for window in (snapshot.session, snapshot.weekly):
            if window is None:
                continue
            pct = window.utilization
            seen = self._last_seen.get(window.key)
            self._last_seen[window.key] = (window.resets_at, pct)
            if seen is None:
                continue
            prev_reset, prev_pct = seen
            active = cfg.notifications_enabled and wanted.get(window.key, False)

            if not _same_window(prev_reset, window.resets_at):
                recharged = window.key == "five_hour" and prev_pct >= RECHARGE_MIN_PCT and pct < prev_pct
                if recharged and cfg.notifications_enabled and cfg.notify_recharge:
                    self.icon.notify(f"{window.label} rechargée : tu peux y retourner !", APP_NAME)
                prev_pct = 0.0

            crossed = [t for t in cfg.notify_thresholds if prev_pct < t <= pct]
            if active and crossed:
                self.icon.notify(threshold_message(window, max(crossed)), APP_NAME)

    # --------------------------------------------------------- cycle de vie
    def run(self) -> None:
        self.icon.run_detached()
        threading.Thread(target=self._poll_loop, name="usage-poll", daemon=True).start()
        if self.config.check_updates and updater.updates_supported():
            threading.Thread(target=self._update_loop, name="update-check", daemon=True).start()
        self.root.after(100, self._drain_ui_queue)
        self.root.mainloop()

    def quit(self) -> None:
        self._stop.set()
        self._wake.set()
        self._update_wake.set()
        self.icon.stop()
        self._ui(self.root.quit)
