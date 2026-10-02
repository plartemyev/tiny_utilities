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
        "graphical": False, "opencode": False, "install_timeout": 1, "reboot_timeout": 1,
        "no_subnet_scan": False, "vbox_vm": None, "resume": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_generated_passwords_are_deferred_to_summary_and_short(capsys):
    args = make_args()
    login, root, user, opencode, generated_notes = cli._resolve_passwords(args)
    assert login == cli.DEFAULT_LOGIN_PASSWORD
    assert len(root) == 10 and root.isalnum()
    assert len(user) == 10 and user.isalnum()
    assert opencode is None
    assert capsys.readouterr().out == ""
    assert f"Root password:  {root}" in generated_notes
    assert f"nameless password:{user}" in generated_notes


def test_explicit_passwords_are_kept():
    args = make_args(root_password="rp", user_password="up")
    _login, root, user, opencode, generated_notes = cli._resolve_passwords(args)
    assert (root, user, opencode) == ("rp", "up", None)
    assert generated_notes == []


def test_opencode_flag_generates_separate_password():
    args = make_args(opencode=True, user_password="up")
    _login, _root, _user, opencode, _notes = cli._resolve_passwords(args)
    assert opencode is not None
    assert len(opencode) == 10 and opencode.isalnum()
    assert opencode != "up"


def test_opencode_unit_contents():
    unit = cli._opencode_unit("secret01")
    assert "OPENCODE_SERVER_USERNAME" not in unit
    assert "Environment=OPENCODE_SERVER_PASSWORD=secret01" in unit
    assert f"ExecStart=/usr/bin/opencode serve --hostname 0.0.0.0 --port {cli.OPENCODE_PORT}" in unit
    assert "WantedBy=default.target" in unit


def test_private_key_path_from_pubkey_file(tmp_path: Path):
    pub = tmp_path / "id_ed25519.pub"
    priv = tmp_path / "id_ed25519"
    pub.write_text("ssh-ed25519 AAAA test\n")
    priv.write_text("PRIVATE")
    assert cli._private_key_path(str(pub)) == str(priv)
    assert cli._private_key_path("ssh-ed25519 AAAA test") is None
    assert cli._private_key_path(str(tmp_path / "missing.pub")) is None


def test_no_subnet_scan_flag_parsing():
    argv = ["--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv).no_subnet_scan is False
    assert cli._parse_args(argv + ["--no-subnet-scan"]).no_subnet_scan is True


def test_vbox_vm_and_resume_parsing():
    argv = ["--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv + ["--vbox-vm", "Vardan's anvil"]).vbox_vm == "Vardan's anvil"
    resumed = cli._parse_args(["--resume", "archinstaller-state-anvil.json"])
    assert resumed.resume == "archinstaller-state-anvil.json"


def test_target_and_pubkey_optional_only_for_resume():
    try:
        cli._parse_args(["--resume", "state.json"])
    except SystemExit:
        raise AssertionError("--resume alone must parse")
    try:
        cli._parse_args(["--target", "192.168.56.113"])
    except SystemExit:
        return
    raise AssertionError("--target without --ssh-pubkey must fail")


def test_state_roundtrip(tmp_path: Path):
    args = make_args()
    args.target = "192.168.56.113"
    state = cli._state_object(
        args, "anvil", "rootpw", "userpw", "opencodepw",
        ["Root password:  rootpw"], "/home/pasha/.ssh/id_ed25519",
        cli.JumpConfig("10.0.0.1", 2222, "root", "jpw"),
    )
    path = tmp_path / "archinstaller-state-anvil.json"
    cli._save_state(str(path), state)
    assert path.stat().st_mode & 0o777 == 0o600
    assert cli._load_state(str(path)) == state


def test_wait_user_service_active_polls_until_active(monkeypatch):
    results = iter([(0, "inactive\n"), (0, "activating\n"), (0, "active\n")])
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, timeout=30: next(results))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    cli._wait_user_service_active(client=None, unit="opencode.service")


def test_wait_user_service_active_gives_up(monkeypatch):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, timeout=30: (0, "failed\n"))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    try:
        cli._wait_user_service_active(client=None, unit="opencode.service", tries=3)
    except SystemExit:
        return
    raise AssertionError("expected SystemExit when the unit never becomes active")
