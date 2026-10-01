"""Point d'entrée pour PyInstaller (qui ne gère pas les imports relatifs de __main__.py)."""

from claude_tracker.__main__ import main

if __name__ == "__main__":
    main()
