from claude_tracker import login


def test_script_launches_claude_when_installed():
    script = login.powershell_script(claude_found=True)
    assert script.rstrip().endswith("claude")
    assert "/exit" in script


def test_script_explains_install_when_missing():
    script = login.powershell_script(claude_found=False)
    assert login.INSTALL_CMD in script
    assert not script.rstrip().endswith("claude")


def test_scripts_are_ascii():
    # Passés en ligne de commande à powershell.exe : on évite les soucis d'encodage.
    for found in (True, False):
        login.powershell_script(found).encode("ascii")


def test_no_console_outside_windows(monkeypatch):
    monkeypatch.setattr(login.sys, "platform", "linux")
    assert login.open_login_console() is None
