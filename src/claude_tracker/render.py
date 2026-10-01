"""Dessin des anneaux de progression avec Pillow.

Tout est dessiné en x4 puis réduit (LANCZOS) : on obtient un anti-aliasing propre,
ce que le Canvas de Tk ne sait pas faire.
"""

from __future__ import annotations

import argparse
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Palette
BG = "#1C1C1E"
CARD = "#2A2A2D"
TEXT = "#F2F2F2"
TEXT_MUTED = "#9A9A9F"
ACCENT = "#D97757"  # orange Claude
TRACK = "#3A3A3E"
GREEN = "#4ADE80"
ORANGE = "#F59E0B"
RED = "#EF4444"
GREY = "#8E8E93"

SUPERSAMPLE = 4

_FONT_CANDIDATES = {
    True: ("segoeuib.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"),
    False: ("segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf"),
}


def color_for(pct: float | None) -> str:
    if pct is None:
        return GREY
    if pct < 60:
        return GREEN
    if pct < 85:
        return ORANGE
    return RED


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha)


def _draw_ring(draw: ImageDraw.ImageDraw, size: int, pct: float | None, color: str,
               thickness: int, track: str) -> None:
    pad = 2  # Pillow trace le trait vers l'intérieur de la boîte
    box = (pad, pad, size - pad - 1, size - pad - 1)
    draw.ellipse(box, outline=track, width=thickness)
    if pct is None or pct <= 0:
        return
    frac = min(pct, 100.0) / 100.0
    start, end = -90.0, -90.0 + 360.0 * frac
    draw.arc(box, start, end, fill=color, width=thickness)
    if frac < 1.0:
        # Extrémités arrondies.
        r = (box[2] - box[0]) / 2 - thickness / 2 + 0.5
        cx = cy = size / 2
        for angle in (start, end):
            a = math.radians(angle)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            h = thickness / 2
            draw.ellipse((x - h, y - h, x + h, y + h), fill=color)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: float, max_h: float, bold: bool = True):
    size = int(max_h)
    while size > 6:
        f = font(size, bold)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= max_w and b - t <= max_h:
            return f
        size -= 2
    return font(6, bold)


def _pct_text(pct: float | None) -> str:
    if pct is None:
        return "–"
    return f"{round(pct):d}"


def tray_icon(pct: float | None, size: int = 64, offline: bool = False) -> Image.Image:
    """Icône de la zone de notification : anneau épais + chiffre au centre."""
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    thickness = int(s * 0.14)
    ring_color = GREY if offline else color_for(pct)
    _draw_ring(d, s, pct, ring_color, thickness, TRACK)

    text = _pct_text(pct)
    inner = s - 2 * thickness
    f = _fit_font(d, text, inner * 0.84, inner * 0.56)
    d.text((s / 2, s / 2), text, font=f, fill=TEXT, anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def gauge(pct: float | None, size: int = 240, offline: bool = False) -> Image.Image:
    """Grande jauge du popup : anneau fin + pourcentage au centre."""
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), _hex_to_rgba(CARD, 0))
    d = ImageDraw.Draw(img)
    thickness = int(s * 0.075)
    _draw_ring(d, s, pct, GREY if offline else color_for(pct), thickness, TRACK)

    value = _pct_text(pct)
    f_big = font(int(s * 0.26), bold=True)
    f_small = font(int(s * 0.11), bold=False)
    vb = d.textbbox((0, 0), value, font=f_big, anchor="ls")
    pb = d.textbbox((0, 0), "%", font=f_small, anchor="ls")
    total_w = (vb[2] - vb[0]) + (pb[2] - pb[0]) + s * 0.01
    x = s / 2 - total_w / 2
    baseline = s / 2 + (vb[3] - vb[1]) * 0.42
    d.text((x, baseline), value, font=f_big, fill=TEXT, anchor="ls")
    if pct is not None:
        d.text((x + (vb[2] - vb[0]) + s * 0.01, baseline), "%", font=f_small, fill=TEXT_MUTED, anchor="ls")
    return img.resize((size, size), Image.LANCZOS)


def app_icon_images() -> list[Image.Image]:
    """Icône de l'application (.ico) : anneau orange Claude sur fond sombre."""
    out = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        s = size * SUPERSAMPLE
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BG)
        inset = int(s * 0.16)
        ring = Image.new("RGBA", (s - 2 * inset,) * 2, (0, 0, 0, 0))
        _draw_ring(ImageDraw.Draw(ring), ring.width, 70, ACCENT, int(ring.width * 0.16), TRACK)
        img.alpha_composite(ring, (inset, inset))
        out.append(img.resize((size, size), Image.LANCZOS))
    return out


def save_app_icon(path: Path) -> None:
    images = app_icon_images()
    path.parent.mkdir(parents=True, exist_ok=True)
    images[-1].save(path, format="ICO", sizes=[im.size for im in images])


def _preview(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    values = [0, 42, 75, 97, None]
    strip = Image.new("RGBA", (len(values) * 80 + 16, 96), BG)
    for i, v in enumerate(values):
        strip.alpha_composite(tray_icon(v), (16 + i * 80, 16))
    strip.save(out / "tray_icons.png")
    small = Image.new("RGBA", (len(values) * 40 + 16, 32), BG)
    for i, v in enumerate(values):
        small.alpha_composite(tray_icon(v, size=24), (8 + i * 40, 4))
    small.save(out / "tray_icons_24px.png")
    for v in values:
        bg = Image.new("RGBA", (240, 240), CARD)
        bg.alpha_composite(gauge(v))
        bg.save(out / f"gauge_{v}.png")
    save_app_icon(out / "app.ico")
    print(f"Aperçus générés dans {out.resolve()}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Génère des aperçus des icônes")
    p.add_argument("--preview", type=Path, default=Path("preview"))
    p.add_argument("--ico", type=Path, help="Écrit uniquement l'icône .ico de l'appli")
    args = p.parse_args()
    if args.ico:
        save_app_icon(args.ico)
    else:
        _preview(args.preview)
