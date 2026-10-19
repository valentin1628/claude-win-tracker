"""Icône de la barre de menus macOS (NSStatusItem natif, via PyObjC).

Remplace pystray sur Mac, avec la même interface (icon.notify, update_menu, stop…)
pour que le reste de l'appli ne change pas. Ce qu'on gagne en natif :
- une image « template » que macOS colore lui-même (clair, sombre, fond teinté) ;
- le pourcentage en texte à côté, en chiffres à chasse fixe (ils ne « dansent » pas) ;
- clic gauche : le popup ; clic droit ou ctrl-clic : le menu natif.

Tout s'exécute dans le thread principal, celui de la boucle Tk (qui tourne sur Cocoa).
Mais les rappels d'AppKit arrivent *pendant* que Tk traite ses événements, verrou de
tkinter pris : y toucher à Tk ferme l'appli. Ils ne font donc que confier le travail à
`defer` (la file que la boucle Tk vide), sans jamais appeler l'appli directement.
"""

from __future__ import annotations

import io
import logging
import subprocess
from typing import Callable

import objc
from AppKit import (
    NSApplication,
    NSEvent,
    NSFont,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSScreen,
    NSStatusBar,
)
from Foundation import NSData, NSMakePoint, NSMakeSize, NSObject

from . import render

log = logging.getLogger("claude_tracker")


def _guard(fn: Callable, *args) -> None:
    """Une exception Python qui remonte dans AppKit ferme l'appli : on la journalise ici."""
    try:
        fn(*args)
    except Exception:
        log.exception("Erreur dans un rappel macOS")

NSVariableStatusItemLength = -1.0
LEFT_DOWN, LEFT_UP, RIGHT_DOWN, RIGHT_UP = 1 << 1, 1 << 2, 1 << 3, 1 << 4
EVENT_RIGHT_UP = 4
MODIFIER_CONTROL = 1 << 18
ACCESSORY_POLICY = 1  # NSApplicationActivationPolicyAccessory : pas d'icône dans le Dock
FONT_WEIGHT_MEDIUM = 0.23


class _Target(NSObject):
    """Reçoit les clics (icône et menu) et la demande de mise à jour du menu."""

    def initWithOwner_(self, owner):
        self = objc.super(_Target, self).init()
        if self is not None:
            self.owner = owner
        return self

    def clicked_(self, sender):
        _guard(self.owner._on_click)

    def menuItem_(self, sender):
        _guard(self.owner._on_menu_item, sender.tag())



def _nsimage(img, size_pt: tuple[int, int], template: bool) -> NSImage:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    image = NSImage.alloc().initWithData_(data)
    image.setSize_(NSMakeSize(*size_pt))  # image en @2x, affichée en points
    image.setTemplate_(template)
    return image


def hide_from_dock() -> None:
    NSApplication.sharedApplication().setActivationPolicy_(ACCESSORY_POLICY)


def activate_app() -> None:
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def notify(message: str, title: str) -> None:
    """Notification macOS (via osascript : fonctionne aussi pour une appli non signée)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e", script])
    except OSError:
        pass


class MacStatusIcon:
    """Même interface que pystray.Icon, pour ce que l'appli en utilise."""

    def __init__(
        self,
        menu,
        on_left_click: Callable[[], None],
        on_outside_click: Callable[[], None],
        defer: Callable[[Callable[[], None]], None],
    ) -> None:
        self.menu = menu  # un pystray.Menu, utilisé comme simple description
        self._on_left_click = on_left_click
        self._defer = defer
        self._target = _Target.alloc().initWithOwner_(self)
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.button = self.item.button()
        self.button.setTarget_(self._target)
        self.button.setAction_("clicked:")
        self.button.sendActionOn_(LEFT_UP | RIGHT_UP)
        self.button.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13.0, FONT_WEIGHT_MEDIUM))
        self.button.setImagePosition_(2)  # NSImageLeft : la pilule, puis le texte
        self.nsmenu = NSMenu.alloc().init()
        self.nsmenu.setAutoenablesItems_(False)
        self._actions: dict[int, object] = {}
        # Clic ailleurs (dans une autre appli) : on referme le popup, comme un popover natif.
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            LEFT_DOWN | RIGHT_DOWN, lambda _event: _guard(defer, on_outside_click)
        )
        self.set_status(None, offline=True, tooltip="Claude Usage")

    # ------------------------------------------------------------- affichage
    def set_status(self, pct: float | None, offline: bool, tooltip: str) -> None:
        img, template = render.menubar_icon(pct, offline=offline, scale=2)
        self.button.setImage_(_nsimage(img, render.MENUBAR_PT, template))
        self.button.setTitle_(" –" if pct is None else f" {round(pct)} %")
        self.button.setAlphaValue_(0.55 if offline else 1.0)
        self.button.setToolTip_(tooltip)

    def anchor(self) -> tuple[float, float] | None:
        """Centre horizontal et bas de l'icône, en coordonnées Tk (origine en haut à gauche)."""
        window = self.button.window()
        if window is None:
            return None
        frame = window.frame()
        screen_h = NSScreen.screens()[0].frame().size.height
        return frame.origin.x + frame.size.width / 2, screen_h - frame.origin.y

    # ----------------------------------------------------------------- clics
    def _on_click(self) -> None:
        event = NSApplication.sharedApplication().currentEvent()
        right = event is not None and (event.type() == EVENT_RIGHT_UP or event.modifierFlags() & MODIFIER_CONTROL)
        if right:
            self.show_menu()
        else:
            self._defer(self._on_left_click)

    def show_menu(self) -> None:
        # Menu natif ouvert juste sous l'icône. Il tourne dans sa propre boucle : les
        # actions choisies sont confiées à defer et s'exécutent une fois le menu fermé.
        self._fill(self.nsmenu, self.menu)
        height = self.button.bounds().size.height
        self.nsmenu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, height + 4), self.button)

    def _fill(self, nsmenu, menu) -> None:
        if nsmenu is self.nsmenu:
            self._actions.clear()
        nsmenu.removeAllItems()
        for entry in menu.items:
            if not entry.visible:
                continue
            if entry is menu.SEPARATOR:
                nsmenu.addItem_(NSMenuItem.separatorItem())
                continue
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(str(entry.text), "menuItem:", "")
            mi.setTarget_(self._target)
            mi.setEnabled_(bool(entry.enabled))
            if entry.checked is not None:
                mi.setState_(1 if entry.checked else 0)
            if entry.submenu is not None:
                sub = NSMenu.alloc().init()
                sub.setAutoenablesItems_(False)
                self._fill(sub, entry.submenu)
                mi.setSubmenu_(sub)
            else:
                tag = len(self._actions) + 1
                self._actions[tag] = entry
                mi.setTag_(tag)
            nsmenu.addItem_(mi)

    def _on_menu_item(self, tag: int) -> None:
        entry = self._actions.get(tag)
        if entry is not None:
            self._defer(lambda: entry(self))  # même appel que pystray : l'action reçoit l'icône

    # ------------------------------------------- compatibilité avec pystray.Icon
    def notify(self, message: str, title: str | None = None) -> None:
        notify(message, title or "Claude Usage Tray")

    def update_menu(self) -> None:
        pass  # le menu est reconstruit à chaque ouverture

    def run_detached(self) -> None:
        pass  # l'icône est déjà dans la barre de menus

    def stop(self) -> None:
        if self._monitor is not None:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
        NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
