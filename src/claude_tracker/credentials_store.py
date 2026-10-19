"""Où Claude Code range son jeton : un fichier (Windows, Linux) ou le Trousseau (macOS).

Le nom du service, le compte et la façon d'écrire dans le Trousseau sont repris de
Claude Code (vérifiés dans le binaire 2.1.299), pour rester compatibles avec lui.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Protocol

KEYCHAIN_SERVICE = "Claude Code-credentials"
SECURITY = "/usr/bin/security"


class StoreError(Exception):
    """Lecture ou écriture impossible (message affichable)."""


class Store(Protocol):
    label: str

    def read(self) -> dict[str, Any] | None:
        """Le contenu JSON, ou None si Claude Code n'y a rien enregistré."""

    def write(self, data: dict[str, Any]) -> None: ...


def default_credentials_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / ".credentials.json"


class FileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_credentials_path()
        self.label = str(self.path)

    def read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Impossible de lire {self.path.name} : {exc}") from None
        return data if isinstance(data, dict) else None

    def write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".credentials.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def keychain_account() -> str:
    """Même règle que Claude Code : $USER, ou un nom générique s'il contient des caractères exotiques."""
    try:
        name = os.environ.get("USER") or getpass.getuser()
    except Exception:
        name = "claude-code-user"
    return name if re.fullmatch(r"[a-zA-Z0-9._-]+", name or "") else "claude-code-user"


Runner = Callable[..., subprocess.CompletedProcess]


class KeychainStore:
    """Trousseau macOS, via l'outil `security` (comme Claude Code)."""

    NOT_FOUND = 44  # code de sortie de `security` quand l'élément n'existe pas

    def __init__(self, service: str = KEYCHAIN_SERVICE, account: str | None = None, run: Runner = subprocess.run):
        self.service = service
        self.account = account or keychain_account()
        self.run = run
        self.label = f"Trousseau macOS ({service})"

    def _find(self, *account: str) -> subprocess.CompletedProcess:
        try:
            return self.run(
                [SECURITY, "find-generic-password", *account, "-w", "-s", self.service],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreError(f"Trousseau inaccessible : {exc}") from None

    def read(self) -> dict[str, Any] | None:
        proc = self._find("-a", self.account)
        if proc.returncode == self.NOT_FOUND:
            # Enregistré sous un autre nom de compte : on prend l'élément du service, quel qu'il soit.
            proc = self._find()
        if proc.returncode == self.NOT_FOUND:
            return None
        if proc.returncode != 0:
            raise StoreError(f"Trousseau inaccessible (code {proc.returncode}) : {proc.stderr.strip()}")
        secret = proc.stdout.strip()
        if re.fullmatch(r"(?:[0-9a-fA-F]{2})+", secret) and not secret.startswith("{"):
            secret = bytes.fromhex(secret).decode("utf-8", "replace")  # valeur écrite en hexadécimal
        try:
            data = json.loads(secret)
        except json.JSONDecodeError:
            raise StoreError("Contenu du Trousseau illisible") from None
        return data if isinstance(data, dict) else None

    def write(self, data: dict[str, Any]) -> None:
        # Comme Claude Code : la commande passe par l'entrée standard de `security -i`,
        # le secret (en hexadécimal) n'apparaît donc jamais dans la liste des processus.
        hex_value = json.dumps(data).encode("utf-8").hex()
        command = f'add-generic-password -U -a "{self.account}" -s "{self.service}" -X "{hex_value}"\n'
        try:
            proc = self.run([SECURITY, "-i"], input=command, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreError(f"Écriture dans le Trousseau impossible : {exc}") from None
        if proc.returncode != 0:
            raise StoreError(f"Écriture dans le Trousseau impossible : {(proc.stderr or proc.stdout).strip()}")


def default_store() -> Store:
    """macOS : le Trousseau, sauf si un fichier existe (CLAUDE_CONFIG_DIR, anciennes versions)."""
    path = default_credentials_path()
    if sys.platform == "darwin" and not path.exists():
        return KeychainStore()
    return FileStore(path)
