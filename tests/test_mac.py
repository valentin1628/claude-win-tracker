"""v0.7 : ce qui sert à la version Mac et se teste sans Mac."""

import json
import plistlib
import subprocess
from pathlib import Path

from claude_tracker import autostart, config, credentials_store, login, render, updater
from claude_tracker.credentials_store import FileStore, KeychainStore
from claude_tracker.usage_client import UsageClient

CREDS = {"claudeAiOauth": {"accessToken": "tok", "refreshToken": "ref", "expiresAt": 1}}


class FakeSecurity:
    """Remplace /usr/bin/security : un dict {compte: valeur}."""

    def __init__(self, items=None, hex_values=False):
        self.items = dict(items or {})
        self.hex = hex_values
        self.calls = []

    def __call__(self, args, input=None, **kwargs):
        self.calls.append((args, input))
        if args[1] == "find-generic-password":
            if "-a" in args:
                value = self.items.get(args[args.index("-a") + 1])
            else:
                value = next(iter(self.items.values()), None)
            if value is None:
                return subprocess.CompletedProcess(args, 44, "", "not found")
            out = value.encode().hex() if self.hex else value
            return subprocess.CompletedProcess(args, 0, out + "\n", "")
        if args[1] == "-i":
            parts = input.split('"')
            account, hex_value = parts[1], parts[5]
            self.items[account] = bytes.fromhex(hex_value).decode()
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)


def test_keychain_read_plain_and_hex():
    for hex_values in (False, True):
        store = KeychainStore(account="val", run=FakeSecurity({"val": json.dumps(CREDS)}, hex_values))
        assert store.read() == CREDS


def test_keychain_not_found_returns_none():
    assert KeychainStore(account="val", run=FakeSecurity()).read() is None


def test_keychain_falls_back_to_any_account():
    fake = FakeSecurity({"autre": json.dumps(CREDS)})
    assert KeychainStore(account="val", run=fake).read() == CREDS
    assert "-a" not in fake.calls[-1][0]


def test_keychain_write_goes_through_stdin():
    fake = FakeSecurity()
    KeychainStore(account="val", run=fake).write(CREDS)
    args, stdin = fake.calls[-1]
    assert args == [credentials_store.SECURITY, "-i"]
    assert "tok" not in " ".join(args)  # le secret ne passe jamais en argument
    assert json.loads(fake.items["val"]) == CREDS


def test_default_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(credentials_store.sys, "platform", "darwin")
    assert isinstance(credentials_store.default_store(), KeychainStore)
    (tmp_path / ".credentials.json").write_text("{}")
    assert isinstance(credentials_store.default_store(), FileStore)
    monkeypatch.setattr(credentials_store.sys, "platform", "win32")
    (tmp_path / ".credentials.json").unlink()
    assert isinstance(credentials_store.default_store(), FileStore)


def test_client_reads_token_from_keychain():
    store = KeychainStore(account="val", run=FakeSecurity({"val": json.dumps(CREDS)}))
    client = UsageClient(store=store)
    assert client.store is store


def test_menubar_icon_template_until_critical():
    img, template = render.menubar_icon(42)
    assert template and img.size == (render.MENUBAR_PT[0] * 2, render.MENUBAR_PT[1] * 2)
    pixels = [img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)]
    assert {px[:3] for px in pixels if px[3] > 200} <= {(0, 0, 0)}
    _, template = render.menubar_icon(90)
    assert not template
    _, template = render.menubar_icon(90, offline=True)
    assert template


def test_menubar_icon_fills_from_bottom():
    img, _ = render.menubar_icon(50)
    w, h = img.size
    alpha = lambda y: img.getpixel((w // 2, y))[3]  # noqa: E731
    assert alpha(int(h * 0.75)) > 200  # moitié basse remplie
    assert alpha(int(h * 0.3)) < 50  # moitié haute vide


def test_config_dir_on_mac(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "darwin")
    assert config.config_dir() == Path.home() / "Library" / "Application Support" / "ClaudeTracker"


def test_update_picks_dmg_on_mac():
    assets = [
        {"name": "ClaudeTracker-9.0.0-Setup.exe", "browser_download_url": "https://x/setup.exe"},
        {"name": "ClaudeTracker-9.0.0-macOS-arm64.dmg", "browser_download_url": "https://x/app.dmg"},
    ]

    class Session:
        def get(self, *a, **k):
            class R:
                status_code = 200

                def json(self):
                    return {"tag_name": "v9.0.0", "assets": assets, "html_url": "https://x"}

            return R()

    info = updater.check_latest(Session(), current="0.7.0", suffix=updater.asset_suffix("darwin"))
    assert info.setup_url == "https://x/app.dmg"
    info = updater.check_latest(Session(), current="0.7.0", suffix=updater.asset_suffix("win32"))
    assert info.setup_url == "https://x/setup.exe"


def test_launch_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.setattr(autostart.Path, "home", lambda: tmp_path)
    exe = "/Applications/Claude Usage Tray.app/Contents/MacOS/Claude Usage Tray"
    assert autostart.mac_program_arguments(exe, frozen=True) == [
        "/usr/bin/open", "-a", "/Applications/Claude Usage Tray.app"
    ]
    assert autostart.supported() and not autostart.is_enabled()
    autostart.set_enabled(True)
    plist = plistlib.loads(autostart.launch_agent_path().read_bytes())
    assert plist["RunAtLoad"] and plist["Label"] == autostart.LAUNCH_AGENT_LABEL
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not autostart.is_enabled()


def test_terminal_login_command_is_escaped():
    args = login.osascript_args(login.terminal_command())
    assert args[0] == "/usr/bin/osascript"
    script = args[2]
    assert script.startswith('tell application "Terminal" to do script "') and script.endswith('"')
    inner = script[len('tell application "Terminal" to do script "'):-1]
    assert '"' not in inner.replace('\\"', "")
    assert login.MAC_INSTALL_CMD in inner
