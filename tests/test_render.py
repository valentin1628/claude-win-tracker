import pytest

from claude_tracker import render


@pytest.mark.parametrize("pct", [None, 0, 1, 50, 99.6, 100, 140])
def test_tray_icon_renders(pct):
    img = render.tray_icon(pct)
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


@pytest.mark.parametrize("pct", [None, 0, 42, 100])
def test_gauge_renders(pct):
    assert render.gauge(pct, size=120).size == (120, 120)


def test_colors_by_threshold():
    assert render.color_for(None) == render.GREY
    assert render.color_for(10) == render.GREEN
    assert render.color_for(60) == render.ORANGE
    assert render.color_for(85) == render.RED


def test_ring_uses_threshold_color():
    img = render.tray_icon(100)
    # Haut de l'anneau (12 h) : doit être rouge.
    r, g, b, a = img.getpixel((32, 4))
    assert a > 200 and r > 200 and g < 120


def test_app_icon(tmp_path):
    path = tmp_path / "app.ico"
    render.save_app_icon(path)
    assert path.stat().st_size > 0
