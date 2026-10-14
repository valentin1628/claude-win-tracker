import json
import time

from claude_tracker import diagnose


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


def write_creds(tmp_path, expires_in_s=3600):
    path = tmp_path / ".credentials.json"
    path.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "sk-ant-oat01-SECRET",
        "refreshToken": "sk-ant-ort01-SECRET",
        "expiresAt": int((time.time() + expires_in_s) * 1000),
        "subscriptionType": "pro",
    }}))
    return path


def test_missing_file(tmp_path, capsys):
    assert diagnose.run(tmp_path / "absent.json") == 1
    assert "introuvable" in capsys.readouterr().out


def test_expired_token_without_auto_refresh(tmp_path, capsys):
    assert diagnose.run(write_creds(tmp_path, -60), auto_refresh=False) == 1
    assert "expiré" in capsys.readouterr().out


def test_expired_token_is_refreshed(tmp_path, capsys):
    payload = {"five_hour": {"utilization": 27, "resets_at": "2026-10-01T16:30:00Z"}}
    session = FakeSession(FakeResponse(200, payload))
    session.post = lambda *a, **k: FakeResponse(200, {"access_token": "new", "expires_in": 28800})
    assert diagnose.run(write_creds(tmp_path, -60), session, auto_refresh=True) == 0
    out = capsys.readouterr().out
    assert "Jeton renouvelé" in out and "Session 5h : 27 %" in out


def test_http_error_shows_body(tmp_path, capsys):
    session = FakeSession(FakeResponse(403, {"error": "forbidden"}))
    assert diagnose.run(write_creds(tmp_path), session, auto_refresh=True) == 1
    out = capsys.readouterr().out
    assert "HTTP 403" in out and "forbidden" in out


def test_ok_never_prints_token(tmp_path, capsys):
    payload = {"five_hour": {"utilization": 27, "resets_at": "2026-10-01T16:30:00Z"}}
    assert diagnose.run(write_creds(tmp_path), FakeSession(FakeResponse(200, payload)), auto_refresh=True) == 0
    out = capsys.readouterr().out
    assert "Session 5h : 27 %" in out and "offre : pro" in out
    assert "SECRET" not in out
