"""Historique local des relevés (SQLite), pour les graphiques et la prévision.

Tout reste sur le PC : %APPDATA%\\ClaudeTracker\\history.db.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .usage_client import UsageSnapshot

DEDUP_S = 15 * 60  # une valeur identique n'est réenregistrée qu'au bout de 15 min
RETENTION_S = 35 * 86400
SAME_WINDOW_S = 600  # resets_at peut varier de quelques secondes d'un appel à l'autre

Sample = tuple[float, float]  # (horodatage epoch, pourcentage)


def _ts(dt: datetime | None) -> float | None:
    return dt.timestamp() if dt else None


def _same_window(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) < SAME_WINDOW_S


class History:
    def __init__(self, path: Path | str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Utilisé depuis le thread Tk et le thread du calcul de coût : un verrou suffit.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    ts REAL NOT NULL, window TEXT NOT NULL, utilization REAL NOT NULL, resets_at REAL
                );
                CREATE INDEX IF NOT EXISTS samples_window_ts ON samples(window, ts);
                """
            )

    # ------------------------------------------------------------ écriture
    def record(self, snapshot: UsageSnapshot) -> None:
        now = snapshot.fetched_at.timestamp()
        with self.lock, self.db:
            for key, w in snapshot.windows.items():
                last = self.db.execute(
                    "SELECT ts, utilization, resets_at FROM samples WHERE window=? ORDER BY ts DESC LIMIT 1",
                    (key,),
                ).fetchone()
                resets = _ts(w.resets_at)
                if (
                    last
                    and abs(last[1] - w.utilization) < 0.05
                    and _same_window(last[2], resets)
                    and now - last[0] < DEDUP_S
                ):
                    continue
                self.db.execute(
                    "INSERT INTO samples(ts, window, utilization, resets_at) VALUES (?, ?, ?, ?)",
                    (now, key, w.utilization, resets),
                )
            self.db.execute("DELETE FROM samples WHERE ts < ?", (now - RETENTION_S,))

    # ------------------------------------------------------------- lecture
    def series(self, window: str, since: float) -> list[Sample]:
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, utilization FROM samples WHERE window=? AND ts>=? ORDER BY ts", (window, since)
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def window_samples(self, window: str, resets_at: datetime | None) -> list[Sample]:
        """Les relevés de la fenêtre en cours (même date de reset)."""
        target = _ts(resets_at)
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, utilization, resets_at FROM samples WHERE window=? AND ts>=? ORDER BY ts",
                (window, time.time() - 8 * 86400),
            ).fetchall()
        return [(r[0], r[1]) for r in rows if _same_window(r[2], target)]

    def daily_increase(self, window: str, days: int = 7, now: datetime | None = None) -> list[tuple[date, float]]:
        """Consommation par jour : somme des hausses, en repartant de 0 à chaque reset."""
        now = now or datetime.now()
        first_day = now.date() - timedelta(days=days - 1)
        since = datetime.combine(first_day, datetime.min.time()).timestamp() - 8 * 86400
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, utilization, resets_at FROM samples WHERE window=? AND ts>=? ORDER BY ts",
                (window, since),
            ).fetchall()
        totals = {first_day + timedelta(days=i): 0.0 for i in range(days)}
        prev = None
        for ts, util, resets in rows:
            if prev is not None:
                if _same_window(prev[2], resets):
                    gain = max(0.0, util - prev[1])
                else:
                    gain = util  # nouvelle fenêtre : tout ce qui est affiché a été consommé depuis le reset
                day = datetime.fromtimestamp(ts).date()
                if day in totals:
                    totals[day] += gain
            prev = (ts, util, resets)
        return sorted(totals.items())

    def close(self) -> None:
        with self.lock:
            self.db.close()
