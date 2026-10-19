"""Orchestration : Tk dans le thread principal, pystray et le polling à côté.

Les autres threads ne touchent jamais Tk directement : ils déposent des messages
dans une file que la boucle Tk vide dès qu'elle est réveillée (voir _setup_wakeup).
"""

from __future__ import annotations

import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import customtkinter as ctk
import pystray

from . import APP_NAME, __version__, autostart, hotkey, login, render, theme, updater
from .applog import log
from .config import Config, config_dir
from .costs import CostSummary, CostTracker
from .forecast import SESSION_LOOKBACK_S, WEEKLY_LOOKBACK_S, Forecast, forecast
from .formatting import forecast_text, reset_clock, tooltip
from .history import History
from .minibar import MiniBar
from .popup import UsagePopup
from .usage_client import (
    CredentialsNotFound,
    NetworkError,
    RateLimited,
    TokenExpired,
    UsageClient,
    UsageError,
    UsageSnapshot,
)

IS_MAC = sys.platform == "darwin"
# La file des tâches d'interface est vidée dès qu'on la remplit (réveil par un tube, hors
# Windows) ; le passage périodique n'est qu'un filet de sécurité. Sous Windows, où Tk ne
# sait pas surveiller un tube, on garde un passage toutes les 100 ms.
UI_POLL_MS = 100 if sys.platform == "win32" else 2000

# customtkinter fait tourner deux boucles permanentes, même fenêtres fermées :
# - le thème du système, toutes les 30 ms : inutile partout, l'appli impose clair ou sombre
#   et suit elle-même le mode « auto » (_watch_theme, toutes les 30 s) ;
# - l'échelle de l'écran, toutes les 100 ms : utile sous Windows (fenêtre déplacée vers un
#   écran réglé à une autre échelle), inutile sur Mac où macOS gère lui-même le Retina.
# Une boucle marquée « déjà lancée » n'est jamais démarrée par customtkinter.
ctk.AppearanceModeTracker.update_loop_running = True
if IS_MAC:
    ctk.ScalingTracker.update_loop_running = True
else:
    ctk.ScalingTracker.update_loop_interval = 1000

def _same_window(a: datetime | None, b: datetime | None) -> bool:
    # resets_at peut varier de quelques secondes d'un appel à l'autre.
    if a is None or b is None:
        return a is b
    return abs((a - b).total_seconds()) < 600


def _open_history() -> History:
    try:
        return History(config_dir() / "history.db")
    except (sqlite3.Error, OSError):
        return History(":memory:")  # fichier inaccessible : historique limité à cette session


def _age_s(snapshot: UsageSnapshot) -> float:
    return (datetime.now(timezone.utc) - snapshot.fetched_at).total_seconds()


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
# Quand Anthropic répond 429 : on attend de plus en plus longtemps (5, 10, 20 puis 30 min max).
RATE_LIMIT_BASE_S = 300
RATE_LIMIT_MAX_S = 1800
# Tant que les derniers chiffres ont moins de 30 min, un 429 n'est pas affiché comme une panne.
STALE_AFTER_S = 1800
# Clics trop rapprochés sur « Rafraîchir » : ignorés pour ne pas déclencher de 429.
MIN_MANUAL_INTERVAL_S = 30
COST_SCAN_INTERVAL_S = 600
# Notification « à ce rythme » : seulement si la limite est proche.
FORECAST_ALERT_S = {"five_hour": 45 * 60, "seven_day": 24 * 3600}
DAY_LABELS = ("lu", "ma", "me", "je", "ve", "sa", "di")
RECHARGE_MIN_PCT = 50  # « session rechargée » seulement si on l'avait bien entamée


class TrayApp:
    def __init__(self, config: Config, fetcher: Fetcher | None = None, history: History | None = None) -> None:
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

        self.notice: str | None = None  # info discrète (ex. limite d'Anthropic), sans griser l'icône
        self._net_failures = 0
        self._rate_strikes = 0
        self._retry_after: float | None = None
        self._last_fetch = 0.0
        self._next_fetch_at = 0.0

        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()

        self._taskbar_light = False
        self._apply_theme(rebuild=False)
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = lambda *exc: log.error("Erreur dans l'interface", exc_info=exc)
        self.history = history or _open_history()
        self.costs = CostTracker(self.history)
        self.cost_summary: CostSummary | None = None
        self.forecasts: dict[str, Forecast | None] = {}
        self._forecast_notified: dict[str, datetime | None] = {}
        self.popup = self._make_popup()
        self.minibar = None if IS_MAC else MiniBar(self.root)  # Windows uniquement
        self.hotkey: hotkey.GlobalHotkey | None = None
        self.settings_window = None
        self._update_thread: threading.Thread | None = None

        if IS_MAC:
            # Barre de menus : icône native (pystray voudrait sa propre boucle dans le thread principal).
            from . import mac_status

            mac_status.hide_from_dock()
            # Les clics arrivent d'AppKit pendant que Tk attend un événement : appeler Tk à ce
            # moment-là bloquerait l'appli (verrou de tkinter déjà pris). On passe par la file.
            self.icon = mac_status.MacStatusIcon(
                self._build_menu(),
                on_left_click=lambda: self.popup.toggle(),
                on_outside_click=self._outside_click,
                defer=self._ui,
            )
            self.popup.anchor = self.icon.anchor
        else:
            self.icon = pystray.Icon(
                "claude_usage", icon=render.tray_icon(None), title=tooltip(None), menu=self._build_menu()
            )

    def _outside_click(self) -> None:
        if self.popup.winfo_viewable():
            self.popup.hide()

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
            pystray.MenuItem("Réglages…", lambda: self._ui(self.open_settings)),
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
            flag_item("Si la limite approche à ce rythme", "notify_forecast"),
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
        wake_fd = getattr(self, "_wake_w", None)
        if wake_fd is not None:
            try:
                os.write(wake_fd, b"\0")  # simple appel système : sans risque depuis AppKit ou un thread
            except OSError:
                pass  # tube plein : un réveil est déjà en attente

    def _setup_wakeup(self) -> None:
        """Réveille la boucle Tk dès qu'une tâche arrive, au lieu de vérifier 10 fois par seconde."""
        self._wake_w = None
        if sys.platform == "win32":
            return
        import tkinter

        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)
        self.root.tk.createfilehandler(read_fd, tkinter.READABLE, self._on_wakeup)
        self._wake_r, self._wake_w = read_fd, write_fd

    def _on_wakeup(self, fd: int, _mask: int) -> None:
        try:
            os.read(fd, 4096)
        except OSError:
            pass
        self._run_ui_tasks()

    def _drain_ui_queue(self) -> None:
        self._run_ui_tasks()
        # Toujours replanifié : root.quit() peut arriver après _stop.set().
        self.root.after(UI_POLL_MS, self._drain_ui_queue)

    def _run_ui_tasks(self) -> None:
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # une erreur ne doit pas figer toute l'interface
                log.exception("Erreur dans l'interface")

    def request_refresh(self) -> None:
        self._wake.set()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._next_fetch_at = time.monotonic() + self.next_delay()
            while not self._stop.is_set():
                manual = self._wake.wait(max(0.0, self._next_fetch_at - time.monotonic()))
                self._wake.clear()
                if not manual or self._manual_refresh_allowed():
                    break
                # Clic sur « Rafraîchir » pendant une attente imposée : on n'appelle pas le serveur.
                self._ui(self._apply_state)

    def _manual_refresh_allowed(self) -> bool:
        now = time.monotonic()
        if self._rate_strikes and now < self._next_fetch_at:
            return False
        return now - self._last_fetch >= MIN_MANUAL_INTERVAL_S

    def _poll_once(self) -> None:
        """Un relevé : met à jour les compteurs d'erreurs qui fixent le délai suivant."""
        self._last_fetch = time.monotonic()
        try:
            snapshot = self.fetcher.fetch()
        except RateLimited as exc:
            self._net_failures = 0
            self._rate_strikes += 1
            self._retry_after = exc.retry_after
            self._ui(self._on_rate_limited)
            return
        except NetworkError as exc:
            self._net_failures += 1
            self._ui(lambda msg=str(exc): self._on_error(msg))
            return
        except (TokenExpired, CredentialsNotFound) as exc:
            self._ui(lambda msg=str(exc): self._on_error(msg, auth=True))
        except UsageError as exc:
            self._ui(lambda msg=str(exc): self._on_error(msg))
        except Exception as exc:  # ne jamais tuer le thread de polling
            self._ui(lambda msg=f"Erreur inattendue : {exc}": self._on_error(msg))
        else:
            self._ui(lambda s=snapshot: self._on_snapshot(s))
        self._net_failures = self._rate_strikes = 0
        self._retry_after = None

    def next_delay(self) -> float:
        poll = self.config.poll_seconds
        if self._rate_strikes:
            backoff = min(RATE_LIMIT_BASE_S * 2 ** (self._rate_strikes - 1), RATE_LIMIT_MAX_S)
            if self._retry_after is not None:
                backoff = max(backoff, min(self._retry_after, 3600))
            return max(backoff, poll)
        if 0 < self._net_failures <= len(NETWORK_RETRY_DELAYS):
            return min(NETWORK_RETRY_DELAYS[self._net_failures - 1], poll)
        return poll

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
            if IS_MAC:
                # On ferme l'appli pour que le Finder puisse la remplacer.
                self.icon.notify("Glisse l'appli dans Applications (Remplacer), puis relance-la.", APP_NAME)
            # L'installeur remplace les fichiers puis relance l'appli.
            self.quit()

        threading.Thread(target=work, name="update-install", daemon=True).start()

    # ------------------------------------------------------- connexion
    def open_login(self) -> None:
        """Ouvre une console avec Claude Code, puis rafraîchit quand c'est fini."""
        if self._login_running:
            return
        try:
            proc = login.open_login_console()
        except OSError as exc:
            self.icon.notify(f"Impossible d'ouvrir le terminal : {exc}", APP_NAME)
            return
        if proc is None:
            return
        self._login_running = True

        def wait() -> None:
            proc.wait()
            if IS_MAC:
                # osascript rend la main tout de suite : on laisse le temps de se connecter,
                # puis on réessaie à intervalles (le refresh manuel est limité à 1 / 30 s).
                for _ in range(10):
                    if self._stop.wait(30) or not self.auth_error:
                        break
                    self.request_refresh()
            self._login_running = False
            self.request_refresh()

        threading.Thread(target=wait, name="login-wait", daemon=True).start()

    # ------------------------------------------------------------- état
    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot, self.error, self.auth_error, self.notice = snapshot, None, False, None
        try:
            self.history.record(snapshot)
        except sqlite3.Error:
            pass  # l'historique est un bonus : ne jamais bloquer l'affichage
        self.icon.update_menu()
        self._update_forecasts()
        self._apply_state()
        self._maybe_notify(snapshot)
        self._maybe_notify_forecast(snapshot)

    def _on_rate_limited(self) -> None:
        retry_at = datetime.now() + timedelta(seconds=self.next_delay())
        note = f"Anthropic limite les actualisations, prochain essai à {retry_at:%H:%M}"
        if self.snapshot and _age_s(self.snapshot) < STALE_AFTER_S:
            # Les chiffres affichés sont encore récents : simple information, pas de panne.
            self.notice = note
            self._apply_state()
        else:
            self._on_error(note)

    def _on_error(self, message: str, auth: bool = False) -> None:
        self.error, self.auth_error, self.notice = message, auth, None
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
        if self._stop.is_set():
            return  # en cours de fermeture : l'icône est peut-être déjà arrêtée
        offline = self.error is not None
        if IS_MAC:
            self.icon.set_status(self._icon_value(), offline, tooltip(self.snapshot, self.error))
        else:
            self.icon.icon = render.tray_icon(self._icon_value(), offline=offline, light_taskbar=self._taskbar_light)
            self.icon.title = tooltip(self.snapshot, self.error)
        if self.minibar:
            self.minibar.set_value(self._icon_value(), offline)
        self.popup.update_state(self.snapshot, self.error, show_login=self.auth_error, notice=self.notice)
        self.popup.update_extras(
            {k: forecast_text(fc) for k, fc in self.forecasts.items()},
            self._details_data(),
        )

    # ------------------------------------------------ prévision et historique
    def _update_forecasts(self) -> None:
        self.forecasts = {}
        if not self.snapshot:
            return
        lookbacks = {"five_hour": SESSION_LOOKBACK_S, "seven_day": WEEKLY_LOOKBACK_S}
        for key, lookback in lookbacks.items():
            window = self.snapshot.windows.get(key)
            if window is None:
                continue
            try:
                samples = self.history.window_samples(key, window.resets_at)
            except sqlite3.Error:
                continue
            self.forecasts[key] = forecast(samples, lookback, window.resets_at)

    def _details_data(self) -> tuple | None:
        now = time.time()
        try:
            series = self.history.series("five_hour", now - 86400)
            days = self.history.daily_increase("seven_day", 7)
        except sqlite3.Error:
            return None
        bars = [(DAY_LABELS[d.weekday()], v) for d, v in days]
        return (series, now - 86400, now, bars, self.cost_summary)

    def _set_details_open(self, is_open: bool) -> None:
        self.config.details_open = is_open
        self.config.save()

    def _maybe_notify_forecast(self, snapshot: UsageSnapshot) -> None:
        """« À ce rythme, limite vers 15:40 » : une fois par fenêtre, si c'est proche."""
        if not (self.config.notifications_enabled and self.config.notify_forecast):
            return
        now = datetime.now(timezone.utc)
        for key, fc in self.forecasts.items():
            window = snapshot.windows.get(key)
            if not window or not fc or fc.kind != "eta":
                continue
            if (fc.at - now).total_seconds() > FORECAST_ALERT_S[key]:
                continue
            if key in self._forecast_notified and _same_window(self._forecast_notified[key], window.resets_at):
                continue
            self._forecast_notified[key] = window.resets_at
            self.icon.notify(f"À ce rythme, limite {window.label} : {forecast_text(fc)}", APP_NAME)

    def _cost_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.costs.scan()
                summary = self.costs.summary()
            except (OSError, sqlite3.Error):
                summary = None
            if summary is not None:
                self._ui(lambda s=summary: self._on_costs(s))
            self._stop.wait(COST_SCAN_INTERVAL_S)

    def _on_costs(self, summary: CostSummary) -> None:
        self.cost_summary = summary
        self._apply_state()

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
    # ------------------------------------------------------------ v0.6
    def _make_popup(self) -> UsagePopup:
        popup = UsagePopup(
            self.root,
            on_refresh=self.request_refresh,
            on_login=self.open_login,
            on_details=self._set_details_open,
            details_open=self.config.details_open,
        )
        icon = getattr(self, "icon", None)
        if IS_MAC and icon is not None:
            popup.anchor = icon.anchor
        return popup

    def _apply_theme(self, rebuild: bool = True) -> None:
        """Palette du popup (réglage ou thème des applis Windows) et encre de l'icône (barre des tâches)."""
        name = theme.resolve(self.config.theme)
        self._taskbar_light = theme.taskbar_light()
        changed = name != render.current_theme
        render.set_theme(name)
        ctk.set_appearance_mode(name)
        if changed and rebuild:
            # Le popup fige ses couleurs à la construction : on le reconstruit.
            was_visible = self.popup.winfo_viewable()
            self.popup.destroy()
            self.popup = self._make_popup()
            if was_visible:
                self.popup.show()
        if rebuild:
            self._apply_state()

    def _watch_theme(self) -> None:
        # En mode « auto », on suit les changements de thème Windows (vérifié toutes les 30 s).
        if self.config.theme == "auto":
            before = (render.current_theme, self._taskbar_light)
            if (theme.resolve("auto"), theme.taskbar_light()) != before:
                self._apply_theme()
        self.root.after(30_000, self._watch_theme)

    def _restart_hotkey(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        if not (self.config.hotkey_enabled and hotkey.supported()):
            return
        try:
            hk = hotkey.GlobalHotkey(self.config.hotkey, lambda: self._ui(self.popup.toggle))
            ok = hk.start()
        except hotkey.HotkeyError as exc:
            self.icon.notify(f"Raccourci invalide : {exc}", APP_NAME)
            return
        if ok:
            self.hotkey = hk
        else:
            self.icon.notify(hk.error or "Raccourci indisponible", APP_NAME)

    def _start_update_loop(self) -> None:
        if self._update_thread and self._update_thread.is_alive():
            return
        if self.config.check_updates and updater.updates_supported():
            self._update_thread = threading.Thread(target=self._update_loop, name="update-check", daemon=True)
            self._update_thread.start()

    def open_settings(self) -> None:
        from .diagnose import run as run_diagnostic
        from .settings_window import SettingsWindow

        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(
            self.root,
            self.config,
            on_change=self._setting_changed,
            post_ui=self._ui,
            test_notification=self._test_notification,
            check_updates=self._check_updates_now,
            run_diagnostic=run_diagnostic,
        )

    def _setting_changed(self, attr: str) -> None:
        if attr == "theme":
            self._apply_theme()
        elif attr in ("hotkey", "hotkey_enabled"):
            self._restart_hotkey()
        elif attr == "minibar" and self.minibar:
            self.minibar.enable(self.config.minibar)
        elif attr == "auto_refresh_token" and isinstance(self.fetcher, UsageClient):
            self.fetcher.auto_refresh_token = self.config.auto_refresh_token
        elif attr == "check_updates":
            self._start_update_loop()
        self.icon.update_menu()
        self._apply_state()

    def _announce_version(self) -> None:
        """Après une mise à jour (ou à la première installation) : une notification de confirmation."""
        previous = self.config.last_version
        if previous == __version__:
            return
        if previous:
            self.icon.notify(f"Mise à jour installée : v{__version__} ✓", APP_NAME)
        else:
            self.icon.notify(f"Claude Usage Tray v{__version__} est installé et prêt ✓", APP_NAME)
        self.config.last_version = __version__
        self.config.save()

    def run(self) -> None:
        self.icon.run_detached()
        threading.Thread(target=self._poll_loop, name="usage-poll", daemon=True).start()
        threading.Thread(target=self._cost_loop, name="cost-scan", daemon=True).start()
        self._start_update_loop()
        self._restart_hotkey()
        if self.minibar:
            self.minibar.enable(self.config.minibar)
        self.root.after(30_000, self._watch_theme)
        self.root.after(3000, self._announce_version)
        if IS_MAC:
            # Repère pour le diagnostic (et le test de la CI qui clique dessus).
            self.root.after(2000, lambda: log.info("Icône de la barre de menus : %s", self.icon.anchor()))
        self._setup_wakeup()
        self.root.after(100, self._drain_ui_queue)
        self.root.mainloop()

    def quit(self) -> None:
        self._stop.set()
        self._wake.set()
        self._update_wake.set()
        if self.hotkey:
            self.hotkey.stop()
        if IS_MAC:
            self._ui(self.icon.stop)  # AppKit : uniquement depuis le thread principal
        else:
            # Dans un thread à part : icon.stop() peut attendre son propre thread, jamais la boucle Tk.
            threading.Thread(target=self.icon.stop, name="tray-stop", daemon=True).start()
        self._ui(self.root.quit)
