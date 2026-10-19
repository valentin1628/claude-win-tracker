"""CI macOS : clique comme un humain sur l'icône de la barre de menus, puis à côté.

Les vrais clics passent par la boucle d'événements de l'appli : c'est ce chemin qui
la bloquait en v0.7.0. Usage : python mac_clicks.py <journal de l'appli>
"""

import re
import sys
import time
from pathlib import Path

import Quartz


def click(x: float, y: float) -> None:
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.05)


def main() -> None:
    log = Path(sys.argv[1])
    deadline = time.time() + 30
    anchor = None
    while time.time() < deadline and anchor is None:
        text = log.read_text(errors="replace") if log.exists() else ""
        m = re.search(r"Icône de la barre de menus : \(([\d.]+), ([\d.]+)\)", text)
        if m:
            anchor = float(m.group(1)), float(m.group(2))
        time.sleep(0.5)
    if anchor is None:
        print("Position de l'icône introuvable dans le journal")
        return
    x, bottom = anchor
    icon = (x, bottom - 11)
    print(f"Icône en {icon}")
    for label, point in [("icône", icon), ("à côté", (400, 500)), ("icône", icon), ("icône", icon),
                         ("à côté", (600, 600))]:
        print(f"Clic {label} {point}")
        click(*point)
        time.sleep(2.5)


if __name__ == "__main__":
    main()
