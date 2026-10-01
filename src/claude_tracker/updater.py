"""Mise à jour automatique depuis les Releases GitHub.

L'appli installée (exe) interroge la dernière release publiée. Si elle est plus
récente, elle propose de télécharger l'installeur et de le lancer en silencieux.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__

REPO = "valentin1628/claude-win-tracker"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP_SUFFIX = "-Setup.exe"


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    setup_url: str
    setup_name: str
    sha256: str | None
    page_url: str


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.10.0' -> (1, 10, 0). Les suffixes non numériques sont ignorés."""
    return tuple(int(n) for n in re.findall(r"\d+", text.split("-")[0])[:3]) or (0,)


def updates_supported() -> bool:
    # En mode sources, on met à jour avec git pull.
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def check_latest(session: requests.Session | None = None, current: str = __version__) -> UpdateInfo | None:
    """Renvoie la mise à jour disponible, ou None (y compris en cas d'erreur)."""
    http = session or requests.Session()
    try:
        resp = http.get(
            LATEST_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"claude-win-tracker/{current}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    tag = str(data.get("tag_name") or "")
    if not tag or parse_version(tag) <= parse_version(current):
        return None
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        url = asset.get("browser_download_url")
        if name.endswith(SETUP_SUFFIX) and url:
            digest = str(asset.get("digest") or "")
            sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
            return UpdateInfo(tag.lstrip("v"), url, name, sha, data.get("html_url") or "")
    return None


def download(info: UpdateInfo, session: requests.Session | None = None, folder: Path | None = None) -> Path:
    http = session or requests.Session()
    folder = folder or Path(tempfile.gettempdir())
    target = folder / info.setup_name
    sha = hashlib.sha256()
    try:
        with http.get(info.setup_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(target, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    fh.write(chunk)
                    sha.update(chunk)
    except requests.RequestException as exc:
        raise UpdateError(f"Téléchargement impossible : {exc}") from None
    if info.sha256 and sha.hexdigest() != info.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("Fichier téléchargé corrompu (empreinte SHA-256 différente)")
    if target.stat().st_size == 0:
        raise UpdateError("Fichier téléchargé vide")
    return target


def launch_installer(setup: Path) -> None:
    """Lance l'installeur en silencieux, détaché : il survit à la fermeture de l'appli."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=flags,
        close_fds=True,
    )
