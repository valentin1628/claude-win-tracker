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

# Palettes. Les modules lisent render.BG, render.TEXT… : set_theme() les remplace.
PALETTES = {
    "dark": {
        "BG": "#1C1C1E", "CARD": "#2A2A2D", "TEXT": "#F2F2F2", "TEXT_MUTED": "#9A9A9F",
        "ACCENT": "#D97757", "TRACK": "#3A3A3E", "GREEN": "#4ADE80", "ORANGE": "#F59E0B",
        "RED": "#EF4444", "GREY": "#8E8E93",
    },
    "light": {
        "BG": "#F5F5F7", "CARD": "#FFFFFF", "TEXT": "#1C1C1E", "TEXT_MUTED": "#6E6E73",
        "ACCENT": "#C96442", "TRACK": "#E3E3E8", "GREEN": "#16A34A", "ORANGE": "#D97706",
        "RED": "#DC2626", "GREY": "#8E8E93",
    },
}
# Icône du tray : lisible sur une barre des tâches sombre ou claire (réglage Windows distinct).
TRAY_INK = {"dark": ("#F2F2F2", "#3A3A3E"), "light": ("#1C1C1E", "#C8C8CD")}

BG = CARD = TEXT = TEXT_MUTED = ACCENT = TRACK = GREEN = ORANGE = RED = GREY = ""
current_theme = ""


def set_theme(name: str) -> None:
    """Applique la palette "dark" ou "light" à tout le module."""
    global current_theme
    current_theme = name if name in PALETTES else "dark"
    globals().update(PALETTES[current_theme])


set_theme("dark")

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


def tray_icon(pct: float | None, size: int = 64, offline: bool = False, light_taskbar: bool = False) -> Image.Image:
    """Icône de la zone de notification : anneau épais + chiffre au centre."""
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    thickness = int(s * 0.14)
    ink, track = TRAY_INK["light" if light_taskbar else "dark"]
    ring_color = GREY if offline else color_for(pct)
    _draw_ring(d, s, pct, ring_color, thickness, track)

    text = _pct_text(pct)
    inner = s - 2 * thickness
    f = _fit_font(d, text, inner * 0.84, inner * 0.56)
    d.text((s / 2, s / 2), text, font=f, fill=ink, anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


MENUBAR_PT = (9, 16)  # taille de la pilule dans la barre de menus macOS, en points
MENUBAR_RED = "#FF453A"  # rouge système macOS


def menubar_icon(pct: float | None, offline: bool = False, scale: int = 2) -> tuple[Image.Image, bool]:
    """Pilule verticale pour la barre de menus macOS, remplie de bas en haut.

    Renvoie (image, template). En « template » (noir + transparence), macOS colore
    l'icône lui-même selon le fond, comme ses icônes système ; à partir de 85 %
    elle passe en rouge (non template), comme la batterie faible.
    """
    k = SUPERSAMPLE * scale
    w, h = MENUBAR_PT[0] * k, MENUBAR_PT[1] * k
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    critical = pct is not None and pct >= 85 and not offline
    ink = _hex_to_rgba(MENUBAR_RED) if critical else (0, 0, 0, 255)
    stroke = max(1, int(1.15 * k))
    radius = w / 2
    d.rounded_rectangle((stroke / 2, stroke / 2, w - stroke / 2 - 1, h - stroke / 2 - 1), radius=radius,
                        outline=ink if not offline else (0, 0, 0, 110), width=stroke)
    if pct is not None and not offline:
        gap = stroke + 1.1 * k  # espace entre le contour et le remplissage, comme la batterie
        inner_top, inner_bottom = gap, h - gap
        level = inner_bottom - (inner_bottom - inner_top) * min(max(pct, 0), 100) / 100
        if pct > 0:
            fill_top = min(level, inner_bottom - 1.6 * k)  # même à 1 %, un trait reste visible
            d.rounded_rectangle((gap, fill_top, w - gap - 1, inner_bottom), radius=(w - 2 * gap) / 2, fill=ink)
    out = img.resize((MENUBAR_PT[0] * scale, MENUBAR_PT[1] * scale), Image.LANCZOS)
    return out, not critical


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


def _empty_text(d: ImageDraw.ImageDraw, w: float, h: float, text: str, k: float) -> None:
    d.text((w / 2, h / 2), text, font=font(int(11 * k), bold=False), fill=_hex_to_rgba(TEXT_MUTED), anchor="mm")


def sparkline(
    points: list[tuple[float, float]], start: float, end: float, width: int = 300, height: int = 64,
    empty_text: str = "Le graphique se remplit au fil des relevés",
) -> Image.Image:
    """Courbe d'utilisation (0-100 %) entre deux horodatages, fond transparent."""
    k = SUPERSAMPLE * height / 64  # tailles relatives : l'image peut être rendue en x2 (écrans HiDPI)
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bottom = 4 * k, h - 2 * k
    for level in (50, 100):  # repères discrets
        y = bottom - (bottom - top) * level / 100
        d.line([(0, y), (w, y)], fill=_hex_to_rgba(TRACK), width=max(1, int(k)))
    d.line([(0, bottom), (w, bottom)], fill=_hex_to_rgba(TRACK), width=max(1, int(k)))
    pts = [p for p in points if start <= p[0] <= end]
    if len(pts) >= 2:
        span = max(end - start, 1)
        xy = [((p[0] - start) / span * w, bottom - (bottom - top) * min(p[1], 100) / 100) for p in pts]
        color = color_for(pts[-1][1])
        d.polygon([(xy[0][0], bottom), *xy, (xy[-1][0], bottom)], fill=_hex_to_rgba(color, 50))
        d.line(xy, fill=_hex_to_rgba(color), width=int(2.2 * k), joint="curve")
        x, y = xy[-1]
        r = 3 * k
        d.ellipse((x - r, y - r, x + r, y + r), fill=_hex_to_rgba(color))
    elif empty_text:
        _empty_text(d, w, (top + bottom) / 2 * 2, empty_text, k)
    return img.resize((width, height), Image.LANCZOS)


def day_bars(
    values: list[tuple[str, float]], width: int = 300, height: int = 78,
    empty_text: str = "Les barres se remplissent jour après jour",
) -> Image.Image:
    """Barres verticales (une par jour) avec le libellé du jour et la valeur en %."""
    k = SUPERSAMPLE * height / 78  # tailles relatives : l'image peut être rendue en x2 (écrans HiDPI)
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_label = font(int(11 * k), bold=False)
    f_value = font(int(10 * k), bold=True)
    label_h, value_h = 14 * k, 12 * k
    top, bottom = value_h + 2 * k, h - label_h
    n = max(len(values), 1)
    slot = w / n
    bar_w = slot * 0.55
    peak = max([v for _, v in values] + [10.0])
    if empty_text and not any(v >= 0.5 for _, v in values):
        _empty_text(d, w, top + bottom, empty_text, k)
    for i, (label, value) in enumerate(values):
        cx = slot * i + slot / 2
        today = i == n - 1
        color = ACCENT if today else "#B86A50"
        bar_h = (bottom - top) * value / peak
        x0, x1 = cx - bar_w / 2, cx + bar_w / 2
        d.rounded_rectangle((x0, bottom - max(bar_h, 2 * k), x1, bottom), radius=3 * k,
                            fill=_hex_to_rgba(color if value > 0 else TRACK))
        if value >= 0.5:
            d.text((cx, bottom - bar_h - 2 * k), f"{round(value)}", font=f_value,
                   fill=_hex_to_rgba(TEXT_MUTED), anchor="mb")
        d.text((cx, h), label, font=f_label, fill=_hex_to_rgba(TEXT if today else TEXT_MUTED), anchor="mb")
    return img.resize((width, height), Image.LANCZOS)


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


def mac_app_icon(size: int = 1024) -> Image.Image:
    """Icône macOS : même dessin, avec la marge des icônes de macOS (contenu sur 80 % de la grille)."""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(s * 0.1)
    inner = s - 2 * pad
    d.rounded_rectangle((pad, pad, s - pad - 1, s - pad - 1), radius=int(inner * 0.225), fill=BG)
    inset = int(inner * 0.18)
    ring = Image.new("RGBA", (inner - 2 * inset,) * 2, (0, 0, 0, 0))
    _draw_ring(ImageDraw.Draw(ring), ring.width, 70, ACCENT, int(ring.width * 0.16), TRACK)
    img.alpha_composite(ring, (pad + inset, pad + inset))
    return img.resize((size, size), Image.LANCZOS)


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
    bar = Image.new("RGBA", (len(values) * 40 + 16, 40), "#ECECEC")
    for i, v in enumerate([5, 42, 75, 97, None]):
        icon, _ = menubar_icon(v)
        bar.alpha_composite(icon, (12 + i * 40, 4))
    bar.save(out / "menubar_icons.png")
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
    p.add_argument("--icns", type=Path, help="Écrit uniquement l'icône .icns (macOS)")
    args = p.parse_args()
    if args.ico:
        save_app_icon(args.ico)
    elif args.icns:
        args.icns.parent.mkdir(parents=True, exist_ok=True)
        mac_app_icon().save(args.icns, format="ICNS")
    else:
        _preview(args.preview)
