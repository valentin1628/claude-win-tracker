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


def make_app():
    app = TrayApp.__new__(TrayApp)  # pas de Tk ni de pystray
    app.config = Config()
    app.icon = FakeIcon()
    app._notified = {}
    return app


def snap(pct, reset=RESET):
    return UsageSnapshot(windows={"five_hour": UsageWindow("five_hour", "Session 5h", pct, reset)})


def test_thresholds_fire_once():
    app = make_app()
    for pct in (10, 50, 82, 83, 96, 99):
        app._maybe_notify(snap(pct))
    assert app.icon.toasts == ["Session 5h : 82 % utilisés", "Session 5h : 96 % utilisés"]


def test_no_toast_for_thresholds_already_passed_at_startup():
    app = make_app()
    app._maybe_notify(snap(90))
    assert app.icon.toasts == []
    app._maybe_notify(snap(96))
    assert app.icon.toasts == ["Session 5h : 96 % utilisés"]


def test_rearms_after_reset_but_ignores_jitter():
    app = make_app()
    app._maybe_notify(snap(10))
    app._maybe_notify(snap(85, RESET + timedelta(seconds=3)))  # même fenêtre
    app._maybe_notify(snap(86, RESET - timedelta(seconds=2)))
    assert len(app.icon.toasts) == 1
    app._maybe_notify(snap(5, RESET + timedelta(hours=5)))  # nouvelle fenêtre
    app._maybe_notify(snap(81, RESET + timedelta(hours=5)))
    assert len(app.icon.toasts) == 2
