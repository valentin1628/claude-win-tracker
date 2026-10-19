"""Point d'entrée : ``python -m claude_tracker`` (ou ClaudeTracker.exe)."""

from __future__ import annotations

import argparse
import os
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


_lock_file = None  # gardé ouvert tant que l'appli tourne


def _single_instance() -> bool:
    """Empêche de lancer deux fois l'appli (mutex nommé Windows, verrou de fichier sur Mac)."""
    if sys.platform == "darwin":
        import fcntl

        from .config import config_dir

        global _lock_file
        path = config_dir() / "app.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        _lock_file = open(path, "w")
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClaudeUsageTray")
    ERROR_ALREADY_EXISTS = 183
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _run_check(run) -> int:
    """Diagnostic : dans la console, ou dans une boîte de dialogue pour l'exe sans console."""
    if sys.stdout is not None or sys.platform != "win32":
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
    # Test de fumée de la CI : l'appli démarre puis se ferme toute seule.
    parser.add_argument("--exit-after", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.check:
        from .diagnose import run

        sys.exit(_run_check(run))

    from . import applog

    applog.setup()
    applog.log.info("Démarrage v%s (%s)", __version__, sys.platform)

    if not _single_instance():
        where = "dans la barre de menus, en haut" if sys.platform == "darwin" else "près de l'horloge, flèche ^"
        print(f"Claude Usage Tray tourne déjà (regarde {where}).", file=sys.stderr)
        return

    config = Config.load()
    if args.interval:
        config.poll_seconds = args.interval
        config.normalized()

    from .app import TrayApp  # import tardif : Tk/pystray seulement si on lance l'UI

    if args.demo:
        config.poll_seconds = 60
        from .history import History

        app = TrayApp(config, fetcher=DemoFetcher(), history=History(":memory:"))
    else:
        app = TrayApp(config)
    if args.exit_after:
        app.root.after(int(args.exit_after * 1000), app.quit)
    app.run()
    # La boucle est terminée : on ferme la base puis on quitte franchement, même si un
    # thread de pystray traîne (sinon l'installeur d'une mise à jour trouverait l'appli ouverte).
    try:
        app.history.close()
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
