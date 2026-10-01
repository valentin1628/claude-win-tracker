import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from claude_tracker import usage_client as uc
from claude_tracker.formatting import ago_text, plan_label, reset_text, tooltip

SAMPLE = {
    "five_hour": {"utilization": 42.0, "resets_at": "2026-10-01T16:30:00.123456+00:00"},
    "seven_day": {"utilization": 18, "resets_at": "2026-10-04T10:00:00Z"},
    "seven_day_oauth_apps": None,
    "seven_day_opus": {"utilization": 0.0, "resets_at": None},
    "extra_usage": {"is_enabled": False},
}


def write_creds(tmp_path, expires_in_s=3600, **extra):
    path = tmp_path / ".credentials.json"
    oauth = {
        "accessToken": "sk-ant-oat01-test",
        "refreshToken": "sk-ant-ort01-test",
        "expiresAt": int((time.time() + expires_in_s) * 1000),
        "subscriptionType": "max",
        **extra,
    }
    path.write_text(json.dumps({"claudeAiOauth": oauth}))
    return path


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def test_parse_full_payload():
    snap = uc.parse_usage(SAMPLE, plan="max")
    assert snap.session.utilization == 42.0
    assert snap.session.resets_at == datetime(2026, 10, 1, 16, 30, 0, 123456, tzinfo=timezone.utc)
    assert snap.weekly.utilization == 18.0
    assert snap.windows["seven_day_opus"].resets_at is None
    assert snap.extras == []  # Opus à 0 % sans reset : non applicable


def test_extras_only_when_active():
    payload = dict(SAMPLE, seven_day_opus={"utilization": 12, "resets_at": "2026-10-04T10:00:00Z"})
    assert [w.key for w in uc.parse_usage(payload).extras] == ["seven_day_opus"]


def test_pro_payload_has_no_extras():
    payload = {
        "five_hour": {"utilization": 30, "resets_at": "2026-10-01T16:30:00Z"},
        "seven_day": {"utilization": 9, "resets_at": "2026-10-04T10:00:00Z"},
        "seven_day_opus": None,
        "seven_day_sonnet": None,
    }
    assert uc.parse_usage(payload, plan="pro").extras == []


def test_parse_ignores_missing_and_null():
    snap = uc.parse_usage({"five_hour": {"utilization": 5}, "seven_day": None})
    assert snap.weekly is None
    assert snap.session.resets_at is None


def test_parse_empty_raises():
    with pytest.raises(uc.UsageError):
        uc.parse_usage({"foo": 1})


def test_missing_credentials(tmp_path):
    with pytest.raises(uc.CredentialsNotFound):
        uc.load_credentials(tmp_path / "nope.json")


def test_fetch_ok(tmp_path, monkeypatch):
    client = uc.UsageClient(credentials_path=write_creds(tmp_path))
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(headers)
        return FakeResponse(200, SAMPLE)

    monkeypatch.setattr(client.session, "get", fake_get)
    snap = client.fetch()
    assert snap.plan == "max"
    assert seen["Authorization"] == "Bearer sk-ant-oat01-test"
    assert seen["anthropic-beta"] == uc.OAUTH_BETA


def test_expired_token_without_refresh(tmp_path):
    client = uc.UsageClient(credentials_path=write_creds(tmp_path, expires_in_s=-10))
    with pytest.raises(uc.TokenExpired):
        client.fetch()


def test_401_raises_token_expired(tmp_path, monkeypatch):
    client = uc.UsageClient(credentials_path=write_creds(tmp_path))
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(401))
    with pytest.raises(uc.TokenExpired):
        client.fetch()


def test_refresh_rewrites_credentials(tmp_path, monkeypatch):
    path = write_creds(tmp_path, expires_in_s=-10)
    client = uc.UsageClient(credentials_path=path, auto_refresh_token=True)
    monkeypatch.setattr(
        client.session, "post",
        lambda *a, **k: FakeResponse(200, {"access_token": "new", "refresh_token": "new-r", "expires_in": 3600}),
    )
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(200, SAMPLE))
    client.fetch()
    saved = json.loads(path.read_text())["claudeAiOauth"]
    assert saved["accessToken"] == "new"
    assert saved["refreshToken"] == "new-r"
    assert saved["subscriptionType"] == "max"  # les autres champs sont conservés


def test_network_error(tmp_path, monkeypatch):
    client = uc.UsageClient(credentials_path=write_creds(tmp_path))

    def boom(*a, **k):
        raise uc.requests.ConnectionError()

    monkeypatch.setattr(client.session, "get", boom)
    with pytest.raises(uc.NetworkError):
        client.fetch()


def test_formatting():
    now = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    w = uc.UsageWindow("five_hour", "Session 5h", 42, now + timedelta(hours=2, minutes=14))
    assert reset_text(w, now) == "reset dans 2 h 14"
    assert reset_text(uc.UsageWindow("x", "x", 1, now + timedelta(seconds=30)), now) == "reset dans 1 min"
    assert reset_text(uc.UsageWindow("x", "x", 1, now + timedelta(days=3)), now).startswith("reset ")
    assert ago_text(now - timedelta(seconds=5), now) == "Mis à jour à l'instant"
    assert ago_text(now - timedelta(minutes=3), now) == "Mis à jour il y a 3 min"
    assert plan_label("max") == "Claude · Max"
    assert plan_label(None) == "Claude"
    tip = tooltip(uc.parse_usage(SAMPLE))
    assert "Session 5h : 42 %" in tip and "Semaine : 18 %" in tip
    assert len(tooltip(None, "x" * 300)) <= 127
    demo = uc.UsageSnapshot(windows=uc.parse_usage(SAMPLE).windows, demo=True)
    assert tooltip(demo).startswith("[Démo] ")
