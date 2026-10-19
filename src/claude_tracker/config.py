"""Réglages persistants dans %APPDATA%\\ClaudeTracker\\config.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ICON_METRICS = ("five_hour", "seven_day", "max")
THEMES = ("auto", "dark", "light")
MIN_POLL_SECONDS = 60
CONFIG_VERSION = 3


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "ClaudeTracker"


@dataclass
class Config:
    poll_seconds: int = 300  # plus souvent, Anthropic répond « trop de requêtes » (429)
    icon_metric: str = "five_hour"  # five_hour | seven_day | max
    notifications_enabled: bool = True
    notify_thresholds: tuple[int, ...] = (80, 95)
    notify_session: bool = True
    notify_weekly: bool = True
    notify_recharge: bool = False
    notify_forecast: bool = False
    auto_refresh_token: bool = True  # comme Claude Code : renouvelle le jeton expiré en silence
    check_updates: bool = True
    details_open: bool = False
    theme: str = "auto"  # auto (suit Windows) | dark | light
    hotkey_enabled: bool = True
    hotkey: str = "Ctrl+Alt+C"
    minibar: bool = False
    last_version: str = ""  # pour la notification « mise à jour installée »
    config_version: int = CONFIG_VERSION

    def normalized(self) -> "Config":
        self.poll_seconds = max(MIN_POLL_SECONDS, int(self.poll_seconds))
        if self.icon_metric not in ICON_METRICS:
            self.icon_metric = "five_hour"
        if self.theme not in THEMES:
            self.theme = "auto"
        self.notify_thresholds = tuple(sorted({int(t) for t in self.notify_thresholds if 0 < int(t) <= 100}))
        return self

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_dir() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls().normalized()
        if not isinstance(data, dict):
            return cls().normalized()
        if data.get("config_version", 1) < 2:
            # Avant la v0.4.0, save() écrivait "auto_refresh_token": false (l'ancien défaut)
            # même si on ne l'avait jamais choisi : on l'ignore pour profiter du nouveau défaut.
            data.pop("auto_refresh_token", None)
        if data.get("config_version", 1) < 3 and data.get("poll_seconds") == 120:
            # 120 s était l'ancien défaut, trop fréquent pour Anthropic : on passe au nouveau.
            data.pop("poll_seconds")
        data["config_version"] = CONFIG_VERSION
        known = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in data.items() if k in known}).normalized()
        except (TypeError, ValueError):
            return cls().normalized()

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["notify_thresholds"] = list(self.notify_thresholds)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
