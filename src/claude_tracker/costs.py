"""Coût équivalent API de l'usage Claude Code, d'après ses journaux locaux.

Claude Code écrit chaque réponse dans ~/.claude/projects/**/*.jsonl, avec le modèle
et le détail des tokens. On additionne au tarif public de l'API (en dollars).
Seul l'usage de Claude Code est compté : claude.ai et Claude Desktop n'écrivent rien ici.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .history import History

M = 1_000_000


@dataclass(frozen=True)
class Price:
    """Dollars par million de tokens."""

    input: float
    output: float
    cache_read: float
    # Haiku 5.5 : tarif plus élevé quand le prompt dépasse un seuil.
    long_prompt_tokens: int | None = None
    long_multiplier: float = 1.0

    @property
    def cache_write_5m(self) -> float:
        return self.input * 1.25

    @property
    def cache_write_1h(self) -> float:
        return self.input * 2.0


# Tarifs publics de l'API Anthropic (référence de la skill claude-api, octobre 2026).
# Le préfixe le plus long l'emporte : « claude-opus-5-5 » avant « claude-opus-5 ».
PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10.0, 50.0, 0.25),
    "claude-mythos-5-1": Price(10.0, 50.0, 0.25),
    "claude-fable-5": Price(10.0, 50.0, 1.00),
    "claude-mythos-5": Price(10.0, 50.0, 1.00),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-5": Price(5.0, 25.0, 0.50),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50),
    "claude-opus-4-7": Price(5.0, 25.0, 0.50),
    "claude-opus-4-6": Price(5.0, 25.0, 0.50),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, long_prompt_tokens=100_000, long_multiplier=5.0),
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10),
}
_PREFIXES = sorted(PRICES, key=len, reverse=True)


def price_for(model: str) -> Price | None:
    for prefix in _PREFIXES:
        if model.startswith(prefix):
            return PRICES[prefix]
    return None


def usage_tokens(usage: dict) -> tuple[int, int, int, int, int]:
    """(entrée, sortie, écriture cache 5 min, écriture cache 1 h, lecture cache)."""
    def n(value) -> int:
        return int(value) if isinstance(value, (int, float)) else 0

    created = n(usage.get("cache_creation_input_tokens"))
    detail = usage.get("cache_creation") or {}
    w1h = n(detail.get("ephemeral_1h_input_tokens"))
    w5m = max(0, created - w1h)
    return (
        n(usage.get("input_tokens")),
        n(usage.get("output_tokens")),
        w5m,
        w1h,
        n(usage.get("cache_read_input_tokens")),
    )


def message_cost(model: str, usage: dict) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    inp, out, w5m, w1h, read = usage_tokens(usage)
    mult = 1.0
    if price.long_prompt_tokens and inp + w5m + w1h + read > price.long_prompt_tokens:
        mult = price.long_multiplier
    return mult * (
        inp * price.input
        + out * price.output
        + w5m * price.cache_write_5m
        + w1h * price.cache_write_1h
        + read * price.cache_read
    ) / M


def default_projects_dir() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / "projects"


@dataclass(frozen=True)
class CostSummary:
    today: float
    month: float
    unknown_tokens: int  # tokens de modèles sans tarif connu (ce mois-ci)
    messages: int  # réponses comptées ce mois-ci


class CostTracker:
    """Lecture incrémentale des journaux, résultats gardés dans la base de l'historique."""

    def __init__(self, history: History, projects_dir: Path | None = None) -> None:
        self.history = history
        self.projects_dir = projects_dir or default_projects_dir()
        with history.lock, history.db:
            history.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cc_files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS cc_messages (
                    key TEXT PRIMARY KEY, ts REAL NOT NULL, model TEXT NOT NULL,
                    cost REAL, tokens INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cc_messages_ts ON cc_messages(ts);
                """
            )

    def scan(self) -> int:
        """Lit ce qui a été ajouté depuis la dernière fois. Renvoie le nombre de réponses ajoutées."""
        if not self.projects_dir.is_dir():
            return 0
        added = 0
        for path in self.projects_dir.rglob("*.jsonl"):
            try:
                added += self._scan_file(path)
            except OSError:
                continue
        return added

    CHUNK = 8 * 1024 * 1024  # lecture par morceaux : les journaux peuvent peser des centaines de Mo

    def _scan_file(self, path: Path) -> int:
        key = str(path)
        with self.history.lock:
            row = self.history.db.execute("SELECT offset FROM cc_files WHERE path=?", (key,)).fetchone()
        offset = row[0] if row else 0
        size = path.stat().st_size
        if size < offset:  # fichier réécrit : on repart du début
            offset = 0
        added = 0
        with open(path, "rb") as fh:
            while offset < size:
                fh.seek(offset)
                chunk = fh.read(min(self.CHUNK, size - offset))
                end = chunk.rfind(b"\n")
                if end < 0:
                    if len(chunk) < self.CHUNK:
                        break  # ligne en cours d'écriture : on attendra
                    end = len(chunk) - 1  # ligne géante sans fin : on la saute
                rows = [r for r in map(_parse_line, chunk[: end + 1].splitlines()) if r]
                offset += end + 1
                with self.history.lock, self.history.db:
                    before = self.history.db.total_changes
                    self.history.db.executemany(
                        "INSERT OR IGNORE INTO cc_messages(key, ts, model, cost, tokens) VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
                    added += self.history.db.total_changes - before
                    self.history.db.execute(
                        "INSERT OR REPLACE INTO cc_files(path, offset) VALUES (?, ?)", (key, offset)
                    )
        return added

    def summary(self, now: datetime | None = None) -> CostSummary:
        now = (now or datetime.now()).astimezone()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.history.lock:
            today = self.history.db.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM cc_messages WHERE ts>=?", (day_start,)
            ).fetchone()[0]
            month, count = self.history.db.execute(
                "SELECT COALESCE(SUM(cost), 0), COUNT(*) FROM cc_messages WHERE ts>=?", (month_start,)
            ).fetchone()
            unknown = self.history.db.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM cc_messages WHERE ts>=? AND cost IS NULL", (month_start,)
            ).fetchone()[0]
        return CostSummary(float(today), float(month), int(unknown), int(count))


def _parse_line(line: bytes) -> tuple | None:
    try:
        entry = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    message = entry.get("message") or {}
    usage = message.get("usage")
    model = message.get("model")
    if not isinstance(usage, dict) or not isinstance(model, str) or model.startswith("<"):
        return None  # "<synthetic>" : messages internes, pas d'appel au modèle
    stamp = entry.get("timestamp")
    try:
        ts = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    # Une même réponse peut être écrite plusieurs fois (une ligne par bloc de contenu).
    key = f"{message.get('id') or ''}:{entry.get('requestId') or ''}"
    if key == ":":
        key = str(entry.get("uuid") or "")
        if not key:
            return None
    tokens = sum(usage_tokens(usage))
    return (key, ts.timestamp(), model, message_cost(model, usage), tokens)
