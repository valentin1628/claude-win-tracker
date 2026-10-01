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
from .usage_client import (
    OAUTH_BETA,
    USAGE_URL,
    UsageError,
    default_credentials_path,
    load_credentials,
    parse_usage,
)


def _line(ok: bool | None, message: str) -> None:
    tag = {True: "[ OK ]", False: "[ KO ]", None: "[INFO]"}[ok]
    print(f"{tag} {message}")


def run(credentials_path: Path | None = None, session: requests.Session | None = None) -> int:
    """Retourne 0 si tout va bien, 1 sinon."""
    _line(None, f"Claude Usage Tray {__version__} - Python {platform.python_version()} - {platform.platform()}")

    path = credentials_path or default_credentials_path()
    if not path.exists():
        _line(False, f"Fichier introuvable : {path}")
        print("       -> Installe Claude Code sur ce PC puis connecte-toi : `claude` puis `/login`.")
        print("          (sur Mac, le jeton est dans le Trousseau : ce fichier n'existe que sous Windows/Linux)")
        return 1
    _line(True, f"Fichier du jeton : {path}")

    try:
        creds = load_credentials(path)
    except UsageError as exc:
        _line(False, str(exc))
        return 1
    _line(True, f"Jeton présent - offre : {creds.plan or 'inconnue'}")

    if creds.expires_at:
        local = creds.expires_at.astimezone()
        if creds.expired:
            _line(False, f"Jeton expiré depuis le {local:%d/%m %H:%M}")
            print("       -> Lance `claude` (Claude Code) une fois pour qu'il le renouvelle, puis relance ce test.")
            return 1
        _line(True, f"Jeton valide jusqu'au {local:%d/%m %H:%M}")

    http = session or requests.Session()
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
