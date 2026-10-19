"""Prévision : à ce rythme, quand atteint-on 100 % ?

Régression linéaire sur les relevés récents de la fenêtre en cours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

SESSION_LOOKBACK_S = 3600  # session 5 h : le rythme de la dernière heure
WEEKLY_LOOKBACK_S = 86400  # semaine : le rythme des dernières 24 h
MIN_POINTS = 3
MIN_SPAN_S = 600


@dataclass(frozen=True)
class Forecast:
    kind: str  # "eta" (limite avant le reset) ou "safe" (tient jusqu'au reset)
    at: datetime | None = None


def _slope(points: list[tuple[float, float]]) -> float:
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    var = sum((p[0] - mx) ** 2 for p in points)
    if var == 0:
        return 0.0
    return sum((p[0] - mx) * (p[1] - my) for p in points) / var


def forecast(
    samples: list[tuple[float, float]],
    lookback_s: float,
    resets_at: datetime | None,
    now: datetime | None = None,
) -> Forecast | None:
    """None s'il n'y a pas assez de données pour estimer quoi que ce soit."""
    now = now or datetime.now(timezone.utc)
    now_ts = now.timestamp()
    recent = [p for p in samples if now_ts - lookback_s <= p[0] <= now_ts + 60]
    if len(recent) < MIN_POINTS or recent[-1][0] - recent[0][0] < MIN_SPAN_S:
        return None
    current = recent[-1][1]
    if current >= 100:
        return None
    slope = _slope(recent)  # % par seconde
    if slope <= 1e-7:
        return Forecast("safe") if resets_at else None
    hit = datetime.fromtimestamp(recent[-1][0] + (100 - current) / slope, tz=timezone.utc)
    if resets_at and hit >= resets_at:
        return Forecast("safe")
    return Forecast("eta", hit)
