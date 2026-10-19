"""Diagnostic pas à pas : ``python -m claude_tracker --check``.

N'affiche jamais le jeton lui-même. Sorties en ASCII pour les consoles Windows.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import __version__
from .config import Config
from .credentials_store import FileStore, default_store
from .usage_client import (
    OAUTH_BETA,
    USAGE_URL,
    CredentialsNotFound,
    UsageClient,
    UsageError,
    load_credentials,
    parse_usage,
)


def _line(ok: bool | None, message: str) -> None:
    tag = {True: "[ OK ]", False: "[ KO ]", None: "[INFO]"}[ok]
    print(f"{tag} {message}")


def run(
    credentials_path: Path | None = None,
    session: requests.Session | None = None,
    auto_refresh: bool | None = None,
) -> int:
    """Retourne 0 si tout va bien, 1 sinon."""
    if auto_refresh is None:
        auto_refresh = Config.load().auto_refresh_token
    _line(None, f"Claude Usage Tray {__version__} - Python {platform.python_version()} - {platform.platform()}")

    store = FileStore(credentials_path) if credentials_path else default_store()
    try:
        creds = load_credentials(store)
    except CredentialsNotFound:
        _line(False, f"Jeton introuvable : {store.label}")
        print("       -> Installe Claude Code puis connecte-toi : `claude` puis `/login`.")
        return 1
    except UsageError as exc:
        _line(False, str(exc))
        return 1
    _line(True, f"Jeton lu dans : {store.label}")
    _line(True, f"Jeton présent - offre : {creds.plan or 'inconnue'}")

    http = session or requests.Session()
    if creds.expires_at and creds.expiring:
        local = creds.expires_at.astimezone()
        if not (auto_refresh and creds.refresh_token):
            _line(False, f"Jeton expiré depuis le {local:%d/%m %H:%M} (renouvellement automatique désactivé)")
            print("       -> Lance `claude` (Claude Code) une fois pour qu'il le renouvelle, puis relance ce test.")
            return 1
        _line(None, f"Jeton expiré le {local:%d/%m %H:%M} : renouvellement...")
        client = UsageClient(store=store, auto_refresh_token=True)
        client.session = http
        try:
            creds = client.refresh()
        except UsageError as exc:
            _line(False, f"Renouvellement impossible : {exc}")
            print("       -> Lance `claude` puis `/login` pour te reconnecter.")
            return 1
        _line(True, "Jeton renouvelé")
    if creds.expires_at:
        _line(True, f"Jeton valide jusqu'au {creds.expires_at.astimezone():%d/%m %H:%M}")

    try:
        resp = http.get(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {creds.access_token}",
                "anthropic-beta": OAUTH_BETA,
                "User-Agent": f"claude-win-tracker/{__version__}",
            },
            timeout=15,
        )
    except requests.exceptions.SSLError as exc:
        _line(False, f"Erreur SSL vers api.anthropic.com : {exc}")
        print("       -> Souvent un proxy/antivirus qui inspecte le HTTPS (réseau d'entreprise).")
        return 1
    except requests.RequestException as exc:
        _line(False, f"Impossible de joindre api.anthropic.com : {exc.__class__.__name__} - {exc}")
        print("       -> Vérifie la connexion, le proxy ou le pare-feu.")
        return 1

    body = resp.text[:600]
    if not resp.ok:
        _line(False, f"Réponse HTTP {resp.status_code} de {USAGE_URL}")
        print(f"       Réponse : {body}")
        if resp.status_code in (401, 403):
            print("       -> Jeton refusé : relance `claude` puis `/login` pour te reconnecter.")
        return 1
    _line(True, f"Réponse HTTP {resp.status_code}")

    try:
        payload = resp.json()
        snapshot = parse_usage(payload, plan=creds.plan)
    except (ValueError, UsageError) as exc:
        _line(False, f"Réponse inattendue : {exc}")
        print(f"       Réponse : {body}")
        return 1

    now = datetime.now(timezone.utc)
    for window in snapshot.windows.values():
        reset = f" - reset {window.resets_at.astimezone():%d/%m %H:%M}" if window.resets_at else ""
        _line(True, f"{window.label} : {window.utilization:.0f} %{reset}")
    _line(None, f"Réponse brute : {json.dumps(payload, ensure_ascii=True)[:600]}")
    _line(None, f"Tout fonctionne ({now.astimezone():%H:%M:%S}).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
