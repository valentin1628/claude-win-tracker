import pytest

from claude_tracker import hotkey, render, theme
from claude_tracker.config import Config


@pytest.mark.parametrize("text,expected", [
    ("Ctrl+Alt+C", (0x0002 | 0x0001, ord("C"))),
    ("ctrl + shift + 9", (0x0002 | 0x0004, ord("9"))),
    ("Win+F5", (0x0008, 0x74)),
])
def test_hotkey_parse(text, expected):
    assert hotkey.parse(text) == expected


@pytest.mark.parametrize("bad", ["C", "Ctrl+", "Hyper+C", "Ctrl+Échap", "Ctrl+F99"])
def test_hotkey_rejects(bad):
    with pytest.raises(hotkey.HotkeyError):
        hotkey.parse(bad)


def test_hotkey_normalize():
    assert hotkey.normalize("ctrl + alt + c") == "Ctrl+Alt+C"


def test_theme_resolve_explicit():
    assert theme.resolve("light") == "light"
    assert theme.resolve("dark") == "dark"
    assert theme.resolve("auto") in ("light", "dark")


def test_palette_switch_changes_module_colors():
    try:
        render.set_theme("light")
        assert render.BG == render.PALETTES["light"]["BG"]
        assert render.color_for(10) == render.PALETTES["light"]["GREEN"]
        render.set_theme("nimporte")
        assert render.current_theme == "dark"
    finally:
        render.set_theme("dark")


def test_tray_icon_ink_follows_taskbar():
    # Bord gauche de l'anneau : la piste non remplie, dont la couleur dépend de la barre des tâches.
    dark = render.tray_icon(42, light_taskbar=False).getpixel((4, 32))
    light = render.tray_icon(42, light_taskbar=True).getpixel((4, 32))
    assert dark != light


def test_empty_charts_render():
    assert render.sparkline([], 0, 1, width=300, height=64).size == (300, 64)
    assert render.day_bars([("lu", 0)] * 7).size == (300, 78)


def test_config_new_fields_and_bad_theme(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"theme": "violet", "config_version": 3}')
    c = Config.load(cfg)
    assert c.theme == "auto" and c.hotkey == "Ctrl+Alt+C" and c.minibar is False and c.last_version == ""


def test_announce_version(monkeypatch, tmp_path):
    try:
        from claude_tracker.app import TrayApp
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"UI indisponible : {exc}")
    from claude_tracker import __version__

    toasts = []
    app = TrayApp.__new__(TrayApp)
    app.icon = type("I", (), {"notify": lambda self, m, t: toasts.append(m)})()
    app.config = Config(last_version="0.0.1")
    monkeypatch.setattr(Config, "save", lambda self, path=None: None)
    app._announce_version()
    assert toasts == [f"Mise à jour installée : v{__version__} ✓"]
    app._announce_version()  # déjà annoncée : rien de plus
    assert len(toasts) == 1
    app.config.last_version = ""
    app._announce_version()
    assert "installé et prêt" in toasts[-1]
