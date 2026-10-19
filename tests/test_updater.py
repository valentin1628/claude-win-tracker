import hashlib

import pytest
import requests

from claude_tracker import updater

SETUP = "ClaudeTracker-0.3.0-Setup.exe"


@pytest.fixture(autouse=True)
def windows_assets(monkeypatch):
    # Ces tests portent sur l'installeur Windows, même quand la CI les lance sur Mac.
    monkeypatch.setattr(updater, "asset_suffix", lambda platform=None: updater.SETUP_SUFFIX)


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self._content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


def release(tag="v0.3.0", assets=None):
    if assets is None:
        assets = [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
            {"name": SETUP, "browser_download_url": "https://x/setup.exe", "digest": "sha256:ABCDEF"},
        ]
    return {"tag_name": tag, "html_url": "https://github.com/r/releases/tag/" + tag, "assets": assets}


def test_parse_version():
    assert updater.parse_version("v1.10.0") > updater.parse_version("v1.9.3")
    assert updater.parse_version("0.2.0") == (0, 2, 0)
    assert updater.parse_version("v0.3.0-beta") == (0, 3, 0)


def test_newer_release_found():
    info = updater.check_latest(FakeSession(FakeResponse(200, release())), current="0.2.0")
    assert info.version == "0.3.0"
    assert info.setup_url == "https://x/setup.exe"
    assert info.setup_name == SETUP
    assert info.sha256 == "abcdef"


@pytest.mark.parametrize("tag", ["v0.2.0", "v0.1.9"])
def test_same_or_older_ignored(tag):
    assert updater.check_latest(FakeSession(FakeResponse(200, release(tag))), current="0.2.0") is None


def test_release_without_setup_ignored():
    session = FakeSession(FakeResponse(200, release(assets=[{"name": "a.zip", "browser_download_url": "u"}])))
    assert updater.check_latest(session, current="0.2.0") is None


def test_errors_return_none():
    assert updater.check_latest(FakeSession(FakeResponse(404, {})), current="0.2.0") is None
    assert updater.check_latest(FakeSession(error=requests.ConnectionError()), current="0.2.0") is None


def test_download_checks_sha(tmp_path):
    data = b"MZ fake installer"
    good = updater.UpdateInfo("0.3.0", "u", SETUP, hashlib.sha256(data).hexdigest(), "")
    path = updater.download(good, FakeSession(FakeResponse(200, content=data)), folder=tmp_path)
    assert path.read_bytes() == data

    bad = updater.UpdateInfo("0.3.0", "u", SETUP, "0" * 64, "")
    with pytest.raises(updater.UpdateError):
        updater.download(bad, FakeSession(FakeResponse(200, content=data)), folder=tmp_path)
    assert not (tmp_path / SETUP).exists()


def test_updates_not_supported_from_sources():
    assert updater.updates_supported() is False
