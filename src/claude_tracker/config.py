"""Réglages persistants dans %APPDATA%\\ClaudeTracker\\config.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ICON_METRICS = ("five_hour", "seven_day", "max")
MIN_POLL_SECONDS = 60


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "ClaudeTracker"


@dataclass
class Config:
    poll_seconds: int = 120
    icon_metric: str = "five_hour"  # five_hour | seven_day | max
    notify_thresholds: tuple[int, ...] = (80, 95)
    auto_refresh_token: bool = False
    check_updates: bool = True

    def normalized(self) -> "Config":
        self.poll_seconds = max(MIN_POLL_SECONDS, int(self.poll_seconds))
        if self.icon_metric not in ICON_METRICS:
            self.icon_metric = "five_hour"
        self.notify_thresholds = tuple(sorted(int(t) for t in self.notify_thresholds))
        return self

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_dir() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls().normalized()
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
