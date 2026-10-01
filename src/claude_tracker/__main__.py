"""Point d'entrée : ``python -m claude_tracker`` (ou ClaudeTracker.exe)."""

from __future__ import annotations

import argparse
import itertools
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .config import Config
from .usage_client import UsageSnapshot, UsageWindow


class DemoFetcher:
    """Fausses données qui évoluent à chaque appel, pour tester l'interface."""

    def __init__(self) -> None:
        self._values = itertools.cycle([12, 38, 64, 81, 97])

    def fetch(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        v = float(next(self._values))
        windows = {
            "five_hour": UsageWindow("five_hour", "Session 5h", v, now + timedelta(hours=2, minutes=14)),
            "seven_day": UsageWindow("seven_day", "Semaine", v / 3, now + timedelta(days=3, hours=5)),
            "seven_day_opus": UsageWindow("seven_day_opus", "Opus (semaine)", v / 6, now + timedelta(days=3)),
        }
        return UsageSnapshot(windows=windows, plan="max")


def _single_instance() -> bool:
    """Empêche de lancer deux fois l'appli (mutex nommé Windows)."""
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClaudeUsageTray")
    ERROR_ALREADY_EXISTS = 183
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def main() -> None:
    parser = argparse.ArgumentParser(prog="claude_tracker", description="Suivi de l'abonnement Claude")
    parser.add_argument("--demo", action="store_true", help="utilise de fausses données")
    parser.add_argument("--interval", type=int, help="intervalle de rafraîchissement (s, min 60)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    if not _single_instance():
        return

    config = Config.load()
    if args.interval:
        config.poll_seconds = args.interval
        config.normalized()

    from .app import TrayApp  # import tardif : Tk/pystray seulement si on lance l'UI

    if args.demo:
        config.poll_seconds = 60
        TrayApp(config, fetcher=DemoFetcher()).run()
    else:
        TrayApp(config).run()


if __name__ == "__main__":
    main()
