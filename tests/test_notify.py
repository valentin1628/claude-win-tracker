from datetime import datetime, timedelta, timezone

import pytest

from claude_tracker.config import Config
from claude_tracker.usage_client import UsageSnapshot, UsageWindow

try:  # pystray a besoin d'un écran sous Linux (ex. CI sans X11)
    from claude_tracker.app import TrayApp
except Exception as exc:  # pragma: no cover
    pytest.skip(f"UI indisponible : {exc}", allow_module_level=True)

RESET = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)


class FakeIcon:
    def __init__(self):
        self.toasts = []

    def notify(self, message, title):
        self.toasts.append(message)


def make_app(**config):
    app = TrayApp.__new__(TrayApp)  # pas de Tk ni de pystray
    app.config = Config(**config).normalized()
    app.icon = FakeIcon()
    app._last_seen = {}
    return app


def snap(pct, reset=RESET, weekly=None):
    windows = {"five_hour": UsageWindow("five_hour", "Session 5h", pct, reset)}
    if weekly is not None:
        windows["seven_day"] = UsageWindow("seven_day", "Semaine", weekly, RESET + timedelta(days=3))
    return UsageSnapshot(windows=windows)


def feed(app, *values):
    for v in values:
        app._maybe_notify(v if isinstance(v, UsageSnapshot) else snap(v))
    return app.icon.toasts


def test_thresholds_fire_once_when_crossed():
    toasts = feed(make_app(), 10, 50, 82, 83, 96, 99)
    assert len(toasts) == 2
    assert toasts[0].startswith("Session 5h : 82 % utilisés")
    assert toasts[1].startswith("Session 5h : 96 % utilisés")


def test_big_jump_gives_a_single_toast():
    assert len(feed(make_app(), 10, 97)) == 1


def test_no_toast_for_thresholds_already_passed_at_startup():
    app = make_app()
    assert feed(app, 90) == []
    assert len(feed(app, 96)) == 1


def test_rearms_after_reset_but_ignores_jitter():
    app = make_app()
    feed(app, 10, snap(85, RESET + timedelta(seconds=3)), snap(86, RESET - timedelta(seconds=2)))
    assert len(app.icon.toasts) == 1
    feed(app, snap(5, RESET + timedelta(hours=5)), snap(81, RESET + timedelta(hours=5)))
    assert len(app.icon.toasts) == 2


def test_disabled_sends_nothing_and_no_burst_when_reenabled():
    app = make_app(notifications_enabled=False)
    assert feed(app, 10, 85, 96) == []
    app.config.notifications_enabled = True
    assert feed(app, 97) == []  # paliers franchis pendant la coupure : pas de rattrapage


def test_per_window_switches():
    app = make_app(notify_session=False)
    toasts = feed(app, snap(10, weekly=10), snap(85, weekly=85))
    assert len(toasts) == 1 and toasts[0].startswith("Semaine : 85 % utilisés")


def test_custom_thresholds_and_quota_reached():
    toasts = feed(make_app(notify_thresholds=(50, 100)), 10, 55, 100)
    assert toasts[0].startswith("Session 5h : 55 %")
    assert toasts[1].startswith("Session 5h : quota atteint")


def test_recharge_notification_is_opt_in():
    later = RESET + timedelta(hours=5)
    assert not any("rechargée" in t for t in feed(make_app(), 10, 70, snap(0, later)))
    toasts = feed(make_app(notify_recharge=True), 10, 70, snap(0, later))
    assert toasts[-1] == "Session 5h rechargée : tu peux y retourner !"


def test_no_recharge_toast_if_session_barely_used():
    app = make_app(notify_recharge=True)
    assert feed(app, 10, 20, snap(0, RESET + timedelta(hours=5))) == []


def test_config_normalizes_thresholds():
    assert Config(notify_thresholds=(95, 0, 80, 80, 150)).normalized().notify_thresholds == (80, 95)
