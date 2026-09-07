import argparse
from pathlib import Path

from archinstaller import cli


def make_args(**overrides):
    defaults = {
        "target": "t", "target_port": 22, "login_user": "root", "login_password": None,
        "jump_host": None, "jump_port": 22, "jump_user": None, "jump_password": None,
        "disk": "/dev/vda", "hostname": None, "username": "nameless",
        "ssh_pubkey": "key", "locale": "en_US.UTF-8", "swap_size": "16G",
        "root_password": None, "user_password": None, "timezone": "Asia/Bangkok",
        "graphical": False, "install_timeout": 1, "reboot_timeout": 1,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_generated_passwords_are_deferred_to_summary_and_short(capsys):
    args = make_args()
    login, root, user, generated_notes = cli._resolve_passwords(args)
    assert login == cli.DEFAULT_LOGIN_PASSWORD
    assert len(root) == 10 and root.isalnum()
    assert len(user) == 10 and user.isalnum()
    assert capsys.readouterr().out == ""
    assert f"Root password:  {root}" in generated_notes
    assert f"nameless password:{user}" in generated_notes


def test_explicit_passwords_are_kept():
    args = make_args(root_password="rp", user_password="up")
    _login, root, user, generated_notes = cli._resolve_passwords(args)
    assert (root, user) == ("rp", "up")
    assert generated_notes == []


def test_private_key_path_from_pubkey_file(tmp_path: Path):
    pub = tmp_path / "id_ed25519.pub"
    priv = tmp_path / "id_ed25519"
    pub.write_text("ssh-ed25519 AAAA test\n")
    priv.write_text("PRIVATE")
    assert cli._private_key_path(str(pub)) == str(priv)
    assert cli._private_key_path("ssh-ed25519 AAAA test") is None
    assert cli._private_key_path(str(tmp_path / "missing.pub")) is None
