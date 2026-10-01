"""Point d'entrée : ``python -m claude_tracker`` (ou ClaudeTracker.exe)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .config import Config
from .usage_client import UsageSnapshot, UsageWindow


class DemoFetcher:
    """Fausses données (offre Pro) qui montent doucement, pour tester l'interface."""

    STEP = 3.0

    def __init__(self) -> None:
        start = datetime.now(timezone.utc)
        self._session_reset = start + timedelta(hours=5)
        self._weekly_reset = start + timedelta(days=7)
        self._session = 5.0 - self.STEP

    def fetch(self) -> UsageSnapshot:
        self._session += self.STEP
        if self._session > 100:
            self._session = 5.0
        windows = {
            "five_hour": UsageWindow("five_hour", "Session 5h", self._session, self._session_reset),
            "seven_day": UsageWindow("seven_day", "Semaine", 10 + self._session / 4, self._weekly_reset),
        }
        return UsageSnapshot(windows=windows, plan="pro", demo=True)


def _single_instance() -> bool:
    """Empêche de lancer deux fois l'appli (mutex nommé Windows)."""
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClaudeUsageTray")
    ERROR_ALREADY_EXISTS = 183
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _run_check(run) -> int:
    """Diagnostic : dans la console, ou dans une boîte de dialogue pour l'exe sans console."""
    if sys.stdout is not None:
        return run()
    import contextlib
    import ctypes
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = run()
    MB_ICONINFORMATION, MB_ICONWARNING = 0x40, 0x30
    ctypes.windll.user32.MessageBoxW(
        None, buffer.getvalue(), "Claude Usage Tray - diagnostic", MB_ICONWARNING if code else MB_ICONINFORMATION
    )
    return code


def main() -> None:
    parser = argparse.ArgumentParser(prog="claude_tracker", description="Suivi de l'abonnement Claude")
    parser.add_argument("--demo", action="store_true", help="utilise de fausses données")
    parser.add_argument("--check", action="store_true", help="diagnostic de la connexion, sans lancer l'appli")
    parser.add_argument("--interval", type=int, help="intervalle de rafraîchissement (s, min 60)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    if args.check:
        from .diagnose import run

        sys.exit(_run_check(run))

    if not _single_instance():
        print("Claude Usage Tray tourne déjà (regarde près de l'horloge, flèche ^).", file=sys.stderr)
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
