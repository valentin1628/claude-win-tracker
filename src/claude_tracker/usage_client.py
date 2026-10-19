"""Récupération de l'utilisation de l'abonnement Claude.

On réutilise le jeton OAuth que Claude Code stocke localement, puis on appelle
l'endpoint utilisé par la commande ``/usage``. Cet endpoint n'est pas documenté
officiellement : tout ce qui dépend de son format est isolé dans ce module.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from . import __version__

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Renouvellement du jeton : mêmes adresse, client_id et format que Claude Code (vérifié sur la v2.1.299).
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_BETA = "oauth-2025-04-20"
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULT_SCOPES = ("user:profile", "user:inference", "user:sessions:claude_code", "user:mcp_servers", "user:file_upload")
# On renouvelle un peu avant l'expiration, comme Claude Code.
EXPIRY_MARGIN_S = 300

# Clés de la réponse API -> libellé affiché.
WINDOW_LABELS = {
    "five_hour": "Session 5h",
    "seven_day": "Semaine",
    "seven_day_opus": "Opus (semaine)",
    "seven_day_sonnet": "Sonnet (semaine)",
}


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #
class UsageError(Exception):
    """Erreur générique, le message est affichable tel quel."""


class CredentialsNotFound(UsageError):
    pass


class TokenExpired(UsageError):
    pass


class NetworkError(UsageError):
    pass


class RateLimited(UsageError):
    """HTTP 429 : Anthropic demande d'espacer les requêtes. Pas une panne."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Anthropic limite les actualisations")
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    """En-tête Retry-After : un nombre de secondes ou une date HTTP."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


# --------------------------------------------------------------------------- #
# Modèle de données
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class UsageWindow:
    key: str
    label: str
    utilization: float  # pourcentage 0-100 (peut dépasser 100)
    resets_at: datetime | None


@dataclass(frozen=True)
class UsageSnapshot:
    windows: dict[str, UsageWindow]
    plan: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    demo: bool = False  # fausses données (--demo)

    @property
    def session(self) -> UsageWindow | None:
        return self.windows.get("five_hour")

    @property
    def weekly(self) -> UsageWindow | None:
        return self.windows.get("seven_day")

    @property
    def extras(self) -> list[UsageWindow]:
        # Quotas secondaires (ex. Opus sur Max). Sur Pro, l'API les renvoie à 0 %
        # sans date de reset : ils ne s'appliquent pas, on les masque.
        return [
            w for k, w in self.windows.items()
            if k not in ("five_hour", "seven_day") and (w.resets_at is not None or w.utilization > 0)
        ]


@dataclass
class Credentials:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    plan: str | None
    raw: dict[str, Any]
    scopes: tuple[str, ...] = ()

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(timezone.utc)

    @property
    def expiring(self) -> bool:
        """Expiré ou sur le point de l'être : il est temps de renouveler."""
        if self.expires_at is None:
            return False
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds() <= EXPIRY_MARGIN_S


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_usage(payload: dict[str, Any], plan: str | None = None) -> UsageSnapshot:
    """Convertit la réponse JSON en ``UsageSnapshot`` en ignorant ce qui est absent."""
    windows: dict[str, UsageWindow] = {}
    for key, label in WINDOW_LABELS.items():
        data = payload.get(key)
        if not isinstance(data, dict):
            continue
        util = data.get("utilization")
        if not isinstance(util, (int, float)):
            continue
        windows[key] = UsageWindow(key, label, float(util), _parse_dt(data.get("resets_at")))
    if not windows:
        raise UsageError("Réponse inattendue de l'API (aucune donnée d'utilisation)")
    return UsageSnapshot(windows=windows, plan=plan)


def default_credentials_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / ".credentials.json"


def load_credentials(path: Path | None = None) -> Credentials:
    path = path or default_credentials_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CredentialsNotFound(
            "Claude Code n'est pas connecté sur ce PC (fichier .credentials.json introuvable)"
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"Impossible de lire {path.name} : {exc}") from None

    oauth = raw.get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token:
        raise CredentialsNotFound("Aucun jeton OAuth Claude dans .credentials.json")

    expires_ms = oauth.get("expiresAt")
    expires_at = (
        datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
        if isinstance(expires_ms, (int, float))
        else None
    )
    return Credentials(
        access_token=token,
        refresh_token=oauth.get("refreshToken"),
        expires_at=expires_at,
        plan=oauth.get("subscriptionType"),
        raw=raw,
        scopes=tuple(s for s in oauth.get("scopes") or () if isinstance(s, str)),
    )


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class UsageClient:
    def __init__(
        self,
        credentials_path: Path | None = None,
        auto_refresh_token: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self.credentials_path = credentials_path or default_credentials_path()
        self.auto_refresh_token = auto_refresh_token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"claude-win-tracker/{__version__}"

    def fetch(self) -> UsageSnapshot:
        # Le fichier est relu à chaque fois : Claude Code a pu renouveler le jeton.
        creds = load_credentials(self.credentials_path)
        if creds.expiring and self.auto_refresh_token and creds.refresh_token:
            creds = self.refresh()
        elif creds.expired:
            raise TokenExpired("Connexion à Claude expirée")

        resp = self._get_usage(creds.access_token)
        if resp.status_code == 401 and self.auto_refresh_token and creds.refresh_token:
            creds = self.refresh(force=True)
            resp = self._get_usage(creds.access_token)
        if resp.status_code == 401:
            raise TokenExpired("Connexion à Claude expirée")
        if resp.status_code == 429:
            raise RateLimited(parse_retry_after(resp.headers.get("Retry-After")))
        if not resp.ok:
            raise NetworkError(f"Erreur API ({resp.status_code})")
        try:
            payload = resp.json()
        except ValueError:
            raise UsageError("Réponse API illisible") from None
        return parse_usage(payload, plan=creds.plan)

    def _get_usage(self, token: str) -> requests.Response:
        try:
            return self.session.get(
                USAGE_URL,
                headers={"Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"Hors ligne ({exc.__class__.__name__})") from None

    def refresh(self, force: bool = False) -> Credentials:
        """Renouvelle le jeton avec le refresh token, comme le fait Claude Code.

        Le fichier est relu juste avant : si Claude Code vient de le renouveler,
        on réutilise son jeton sans rien demander au serveur.
        """
        creds = load_credentials(self.credentials_path)
        if not force and not creds.expiring:
            return creds
        if not creds.refresh_token:
            raise TokenExpired("Connexion à Claude expirée")
        try:
            resp = self.session.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": creds.refresh_token,
                    "client_id": CLAUDE_CODE_CLIENT_ID,
                    "scope": " ".join(creds.scopes or DEFAULT_SCOPES),
                },
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"Hors ligne ({exc.__class__.__name__})") from None
        if resp.status_code == 429:
            raise RateLimited(parse_retry_after(resp.headers.get("Retry-After")))
        if resp.status_code >= 500:
            raise NetworkError(f"Renouvellement indisponible ({resp.status_code}), nouvel essai plus tard")
        try:
            data = resp.json() if resp.ok else {}
            access_token = data["access_token"]
        except (ValueError, KeyError, TypeError):
            raise TokenExpired("Connexion à Claude expirée (renouvellement refusé)") from None

        oauth = dict(creds.raw.get("claudeAiOauth") or {})
        oauth["accessToken"] = access_token
        if data.get("refresh_token"):
            oauth["refreshToken"] = data["refresh_token"]
        if data.get("expires_in"):
            oauth["expiresAt"] = int((time.time() + float(data["expires_in"])) * 1000)
        if isinstance(data.get("scope"), str) and data["scope"].strip():
            oauth["scopes"] = data["scope"].split()
        _atomic_write_json(self.credentials_path, dict(creds.raw, claudeAiOauth=oauth))
        return load_credentials(self.credentials_path)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".credentials.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
