"""Journal d'erreurs : pour comprendre un plantage après coup.

macOS : ~/Library/Logs/ClaudeTracker/claude-tracker.log (lisible dans l'appli Console).
Ailleurs : à côté des réglages.
"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import config_dir

log = logging.getLogger("claude_tracker")
_crash_file = None  # gardé ouvert pour faulthandler


def log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "ClaudeTracker"
    return config_dir()


def setup() -> Path | None:
    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "claude-tracker.log"
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # Plantage dur (segfault…) : la pile de chaque thread est écrite dans crash.log.
    # Fichier à part : faulthandler garde le descripteur, que la rotation du journal fermerait.
    global _crash_file
    try:
        _crash_file = open(folder / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        pass

    def excepthook(exc_type, exc, tb) -> None:
        log.error("Exception non gérée", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args) -> None:
        log.error("Exception dans le thread %s", args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return path
