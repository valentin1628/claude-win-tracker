import time
from datetime import datetime, timedelta, timezone

import pytest

from claude_tracker.config import Config
from claude_tracker.usage_client import NetworkError, RateLimited, UsageSnapshot, UsageWindow, parse_retry_after

try:  # pystray a besoin d'un écran sous Linux (ex. CI sans X11)
    from claude_tracker import app as app_module
    from claude_tracker.app import TrayApp
except Exception as exc:  # pragma: no cover
    pytest.skip(f"UI indisponible : {exc}", allow_module_level=True)


class Fetcher:
    def __init__(self, *results):
        self.results = list(results)

    def fetch(self):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def snap(age_s=0.0):
    fetched = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return UsageSnapshot(windows={"five_hour": UsageWindow("five_hour", "Session 5h", 10, None)}, fetched_at=fetched)


def make_app(*results, **config):
    app = TrayApp.__new__(TrayApp)  # pas de Tk ni de pystray
    app.config = Config(**config).normalized()
    app.fetcher = Fetcher(*results)
    app.snapshot, app.error, app.notice, app.auth_error = None, None, None, False
    app._net_failures = app._rate_strikes = 0
    app._retry_after = None
    app._last_fetch = app._next_fetch_at = 0.0
    app._ui = lambda fn: fn()
    app.icon = type("FakeIcon", (), {"update_menu": lambda self: None})()
    app.applied = []
    app._apply_state = lambda: app.applied.append((app.error, app.notice))
    app._on_snapshot = lambda s: setattr(app, "snapshot", s)
    return app


def test_network_errors_retry_fast_then_normal():
    app = make_app(*(NetworkError("x") for _ in range(3)), snap())
    delays = []
    for _ in range(4):
        app._poll_once()
        delays.append(app.next_delay())
    assert delays == [15, 30, 300, 300]


def test_rate_limit_backs_off_and_never_retries_fast():
    app = make_app(*(RateLimited() for _ in range(5)), snap())
    delays = []
    for _ in range(6):
        app._poll_once()
        delays.append(app.next_delay())
    assert delays == [300, 600, 1200, 1800, 1800, 300]


def test_retry_after_header_is_honoured():
    app = make_app(RateLimited(retry_after=900))
    app._poll_once()
    assert app.next_delay() == 900


def test_rate_limit_with_recent_data_is_a_soft_notice():
    app = make_app(RateLimited())
    app.snapshot = snap(age_s=120)
    app._poll_once()
    assert app.error is None
    assert app.notice.startswith("Anthropic limite les actualisations, prochain essai à ")


def test_rate_limit_with_stale_data_is_an_error():
    app = make_app(RateLimited())
    app.snapshot = snap(age_s=app_module.STALE_AFTER_S + 60)
    app._poll_once()
    assert app.error and app.error.startswith("Anthropic limite")


def test_manual_refresh_is_throttled():
    app = make_app()
    app._last_fetch = time.monotonic()
    assert not app._manual_refresh_allowed()  # clic juste après un relevé
    app._last_fetch = time.monotonic() - 60
    assert app._manual_refresh_allowed()
    app._rate_strikes, app._next_fetch_at = 1, time.monotonic() + 300
    assert not app._manual_refresh_allowed()  # pendant une attente imposée par Anthropic


def test_parse_retry_after():
    assert parse_retry_after("120") == 120
    assert parse_retry_after(None) is None
    assert parse_retry_after("n'importe quoi") is None
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert 540 < parse_retry_after(future) <= 600


def test_old_default_poll_interval_is_migrated(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"poll_seconds": 120, "config_version": 2}')
    assert Config.load(cfg).poll_seconds == 300
    cfg.write_text('{"poll_seconds": 600, "config_version": 2}')
    assert Config.load(cfg).poll_seconds == 600
