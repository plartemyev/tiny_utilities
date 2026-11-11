import argparse
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from archinstaller import cli
from archinstaller.steps import (ZCODE_BUILD_TIMEOUT, post_boot_steps,
                                 zcode_build_payload)


LIVE_CONN = SimpleNamespace(client=None)  # probe target: only .client is used


def make_args(**overrides):
    defaults = {
        "command": "install",
        "target": "t", "target_port": 22, "login_user": "root", "login_password": None,
        "jump_host": None, "jump_port": 22, "jump_user": None, "jump_password": None,
        "disk": "/dev/vda", "hostname": None, "username": "nameless",
        "ssh_pubkey": "key", "locale": "en_US.UTF-8", "swap_size": "16G",
        "root_password": None, "user_password": None, "timezone": "Asia/Bangkok",
        "graphical": False, "devel": False, "opencode": False, "zcode": False,
        "local_mirror": False,
        "virt": None, "discard": False,
        "provision": "none", "disk_size_gib": 45, "ram_gib": 4, "cores": 4,
        "iso_path": "~/Downloads/archlinux.iso",
        "install_timeout": 1, "reboot_timeout": 1,
        "no_subnet_scan": False, "vbox_vm": None,
        "out": None, "with_passwords": False, "language": "en", "state_file": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_generated_passwords_are_deferred_to_summary_and_short(capsys):
    args = make_args()
    login, root, user, opencode, zcode_token, generated_notes = cli._resolve_passwords(args)
    assert login == cli.DEFAULT_LOGIN_PASSWORD
    assert len(root) == 10 and root.isalnum()
    assert len(user) == 10 and user.isalnum()
    assert opencode is None
    assert zcode_token is None
    assert capsys.readouterr().out == ""
    assert f"Root password:  {root}" in generated_notes
    assert f"nameless password:{user}" in generated_notes


def test_explicit_passwords_are_kept():
    args = make_args(root_password="rp", user_password="up")
    _login, root, user, opencode, zcode_token, generated_notes = cli._resolve_passwords(args)
    assert (root, user, opencode, zcode_token) == ("rp", "up", None, None)
    assert generated_notes == []


def test_opencode_flag_generates_separate_password():
    args = make_args(opencode=True, user_password="up")
    _login, _root, _user, opencode, _zcode, _notes = cli._resolve_passwords(args)
    assert opencode is not None
    assert len(opencode) == 10 and opencode.isalnum()
    assert opencode != "up"


def test_zcode_flag_generates_urlsafe_token():
    args = make_args(zcode=True, user_password="up")
    _login, _root, _user, _opencode, zcode_token, _notes = cli._resolve_passwords(args)
    # matches `openssl rand -base64 24 | tr '/+' '_-'`: 24 bytes base64 into
    # exactly 32 unpadded URL-safe characters
    assert zcode_token is not None
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", zcode_token)


def test_opencode_unit_contents():
    from archinstaller.steps import OPENCODE_PORT, opencode_unit
    unit = opencode_unit("secret01")
    assert "OPENCODE_SERVER_USERNAME" not in unit
    assert "Environment=OPENCODE_SERVER_PASSWORD=secret01" in unit
    assert f"ExecStart=/usr/bin/opencode serve --hostname 0.0.0.0 --port {OPENCODE_PORT}" in unit
    assert "WantedBy=default.target" in unit


def test_zcode_unit_contents():
    from archinstaller.steps import ZCODE_WEB_PORT, zcode_web_unit
    unit = zcode_web_unit("tok_abc123-_")
    assert "[Unit]" in unit and "Description=ZCode web (LAN, token auth)" in unit
    assert "After=network-online.target" in unit
    assert (f"ExecStart=/usr/bin/zcode --web --host 0.0.0.0 --port {ZCODE_WEB_PORT}"
            " --no-open --token tok_abc123-_" in unit)
    assert "ZCODE_CREDENTIAL_SECRET_FILE=" in unit  # headless credential store
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_zcode_flag_parsing():
    argv = ["install", "--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv).zcode is False
    assert cli._parse_args(argv + ["--zcode"]).zcode is True
    assert cli._parse_args(["workbook", "--ssh-pubkey", "k", "--zcode"]).zcode is True


def test_private_key_path_from_pubkey_file(tmp_path: Path):
    pub = tmp_path / "id_ed25519.pub"
    priv = tmp_path / "id_ed25519"
    pub.write_text("ssh-ed25519 AAAA test\n")
    priv.write_text("PRIVATE")
    assert cli._private_key_path(str(pub)) == str(priv)
    assert cli._private_key_path("ssh-ed25519 AAAA test") is None
    assert cli._private_key_path(str(tmp_path / "missing.pub")) is None


def test_ssh_pubkey_is_optional_with_ed25519_default():
    argv = ["install", "--target", "192.168.56.113"]
    assert cli._parse_args(argv).ssh_pubkey == "~/.ssh/id_ed25519.pub"
    assert cli._parse_args(argv + ["--ssh-pubkey", "k"]).ssh_pubkey == "k"
    assert cli._parse_args(["workbook"]).ssh_pubkey == "~/.ssh/id_ed25519.pub"


def test_unresolvable_pubkey_exits_cleanly_instead_of_traceback():
    with pytest.raises(SystemExit) as excinfo:
        cli._resolve_public_key("/nonexistent/key.pub")
    assert "--ssh-pubkey" in str(excinfo.value)


def test_no_subnet_scan_flag_parsing():
    argv = ["install", "--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv).no_subnet_scan is False
    assert cli._parse_args(argv + ["--no-subnet-scan"]).no_subnet_scan is True


def test_virt_and_discard_flag_parsing():
    argv = ["install", "--target", "t", "--ssh-pubkey", "k"]
    args = cli._parse_args(argv)
    assert args.virt is None and args.discard is False  # probe by default
    pinned = cli._parse_args(argv + ["--virt", "oracle", "--discard"])
    assert pinned.virt == "oracle" and pinned.discard is True
    try:
        cli._parse_args(argv + ["--virt", "bogus"])
    except SystemExit:
        return
    raise AssertionError("--virt must be choice-validated")


def test_vbox_vm_and_resume_parsing():
    argv = ["install", "--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv + ["--vbox-vm", "test's vm"]).vbox_vm == "test's vm"
    resumed = cli._parse_args(["resume", "archinstaller-state-testhost.json"])
    assert resumed.command == "resume"
    assert resumed.state_file == "archinstaller-state-testhost.json"


def test_local_mirror_flag_parsing():
    argv = ["install", "--target", "192.168.56.113", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv).local_mirror is False
    assert cli._parse_args(argv + ["--local-mirror"]).local_mirror is True
    assert cli._parse_args(argv + ["--local_mirror"]).local_mirror is True


def test_provision_flag_parsing():
    argv = ["install", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv + ["--target", "t"]).provision == "none"
    args = cli._parse_args(argv + ["--provision", "libvirt"])
    assert args.provision == "libvirt" and args.target is None
    assert args.disk_size_gib == 45 and args.ram_gib == 4 and args.cores == 4
    assert args.iso_path == "~/Downloads/archlinux.iso"
    try:
        cli._parse_args(argv + ["--provision", "aws"])
    except SystemExit:
        return
    raise AssertionError("--provision must be choice-validated")


def test_provision_rejects_transport_flags(tmp_path):
    iso = tmp_path / "arch.iso"
    iso.write_bytes(b"")
    base = ["install", "--provision", "vbox", "--ssh-pubkey", "k",
            "--iso-path", str(iso)]
    for extra in (["--target", "192.168.56.113"], ["--jump-host", "j"],
                  ["--vbox-vm", "vm"], ["--virt", "kvm"],
                  ["--cores", "0"], ["--ram-gib", "0"]):
        try:
            cli._parse_args(base + extra)
        except SystemExit:
            continue
        raise AssertionError(f"--provision must reject {extra}")


def test_provision_validates_the_iso_path(tmp_path):
    base = ["install", "--provision", "vbox", "--ssh-pubkey", "k"]
    for bad in ("/no/such.iso", str(tmp_path / "arch.txt")):
        try:
            cli._parse_args(base + ["--iso-path", bad])
        except SystemExit:
            continue
        raise AssertionError(f"--iso-path must reject {bad}")
    iso = tmp_path / "arch.iso"
    iso.write_bytes(b"")
    args = cli._parse_args(base + ["--iso-path", str(iso)])
    assert args.iso_path == str(iso)


def test_workbook_provision_parsing():
    argv = ["workbook", "--ssh-pubkey", "k", "--provision", "vbox"]
    args = cli._parse_args(argv)
    assert args.provision == "vbox"
    assert args.disk_size_gib == 45 and args.ram_gib == 4 and args.cores == 4
    try:
        cli._parse_args(argv + ["--provision", "aws"])
    except SystemExit:
        pass
    else:
        raise AssertionError("--provision must be choice-validated")
    try:
        cli._parse_args(argv + ["--virt", "kvm"])
    except SystemExit:
        pass
    else:
        raise AssertionError("--virt must be rejected with --provision")


def test_workbook_provision_needs_no_iso_on_disk():
    # the workbook may be rendered for another host: --iso-path is only
    # rendered, not validated
    args = cli._parse_args(["workbook", "--ssh-pubkey", "k",
                            "--provision", "libvirt",
                            "--iso-path", "/no/such.iso"])
    assert args.iso_path == "/no/such.iso"
    try:
        cli._parse_args(["workbook", "--ssh-pubkey", "k",
                         "--provision", "libvirt", "--cores", "0"])
    except SystemExit:
        return
    raise AssertionError("--cores must be >= 1 for a provisioned workbook")


def test_workbook_parsing_needs_no_target():
    args = cli._parse_args(["workbook", "--ssh-pubkey", "k"])
    assert args.command == "workbook"
    assert args.out is None and args.with_passwords is False
    assert args.language == "en"  # English unless asked otherwise
    pinned = cli._parse_args(["workbook", "--ssh-pubkey", "k",
                              "--out", "w.md", "--with-passwords",
                              "--virt", "kvm", "--discard"])
    assert pinned.out == "w.md" and pinned.with_passwords is True
    assert pinned.virt == "kvm" and pinned.discard is True


def test_workbook_language_flag_parsing():
    argv = ["workbook", "--ssh-pubkey", "k"]
    assert cli._parse_args(argv + ["--language", "ru"]).language == "ru"
    try:
        cli._parse_args(argv + ["--language", "de"])
    except SystemExit:
        return
    raise AssertionError("--language must be choice-validated")


def test_transport_flags_rejected_for_workbook():
    try:
        cli._parse_args(["workbook", "--ssh-pubkey", "k", "--target", "t"])
    except SystemExit:
        return
    raise AssertionError("--target must be install-only")


def test_install_requires_target():
    try:
        cli._parse_args(["install", "--ssh-pubkey", "k"])
    except SystemExit:
        return
    raise AssertionError("install without --target must fail")


def test_state_roundtrip(tmp_path: Path):
    args = make_args()
    args.target = "192.168.56.113"
    state = cli._state_object(
        args, "testhost", "rootpw", "userpw", "opencodepw", "zcodetoken",
        ["Root password:  rootpw"], "/home/user/.ssh/id_ed25519",
        cli.JumpConfig("10.0.0.1", 2222, "root", "jpw"),
    )
    path = tmp_path / "archinstaller-state-testhost.json"
    cli._save_state(str(path), state)
    assert path.stat().st_mode & 0o777 == 0o600
    assert cli._load_state(str(path)) == state
    assert state["graphical"] is False  # resume needs it for zcode_desktop


def test_ssh_encrypted_key_falls_back_to_agent(monkeypatch, capsys, tmp_path: Path):
    """An encrypted private key must not kill the stage-two reconnect:
    paramiko raises PasswordRequiredException before ever trying the agent,
    so connect_target drops the explicit key up front."""
    from archinstaller import ssh as ssh_mod

    unencrypted = tmp_path / "plain_key"
    unencrypted.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n"
                           "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB\n"
                           "-----END OPENSSH PRIVATE KEY-----\n")
    encrypted = tmp_path / "locked_key"
    encrypted.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n"
                         "b3BlbnNzaC1rZXktdjEAAAAABGJjcnlwdAAAAAAAAAABCds2\n"
                         "-----END OPENSSH PRIVATE KEY-----\n")
    assert not ssh_mod._key_is_encrypted(str(unencrypted))
    assert ssh_mod._key_is_encrypted(str(encrypted))

    captured = {}
    monkeypatch.setattr(ssh_mod, "_connect_single",
                        lambda host, port, username, password, **kw:
                        captured.update(kw) or "client")
    conn = ssh_mod.connect_target("t", 22, "u", None, key_filename=str(encrypted))
    assert conn.client == "client"
    assert captured["key_filename"] is None  # dropped: the agent takes over
    assert "passphrase-protected" in capsys.readouterr().out

    conn = ssh_mod.connect_target("t", 22, "u", None, key_filename=str(unencrypted))
    assert captured["key_filename"] == str(unencrypted)  # kept as-is


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


def test_healthy_dns_probes_once_and_never_repairs(monkeypatch, capsys):
    captured = []
    monkeypatch.setattr(cli, "run_capture",
                        lambda client, cmd, **kw: captured.append(cmd) or (0, ""))
    cli._ensure_live_dns(None)
    cli._ensure_installed_dns(None, "pw")
    assert captured == [cli.DNS_PROBE, cli.DNS_PROBE]
    assert "broken" not in capsys.readouterr().out


def test_live_dns_falls_back_to_public_resolvers(monkeypatch, capsys):
    state = {"probes": 0}
    captured = []

    def fake_capture(client, cmd, **kw):
        captured.append(cmd)
        if cmd == cli.DNS_PROBE:
            state["probes"] += 1
            return (0 if state["probes"] > 1 else 1, "")
        if "ip route" in cmd:
            return (0, "enp0s3\n")  # post-awk interface name
        return (0, "")

    monkeypatch.setattr(cli, "run_capture", fake_capture)
    cli._ensure_live_dns(None)
    assert "resolvectl dns enp0s3 1.1.1.1 8.8.8.8" in captured
    assert state["probes"] == 2
    assert "DNS fallback is active" in capsys.readouterr().out


def test_live_dns_aborts_install_when_fallback_does_not_help(monkeypatch):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (1, ""))
    with pytest.raises(SystemExit):
        cli._ensure_live_dns(None)


def test_primary_lan_address_parses_ip_route(monkeypatch):
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda cmd, **kw: SimpleNamespace(
            returncode=0,
            stdout="1.1.1.1 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 1000\n"))
    assert cli._primary_lan_address() == ("eth0", "192.168.1.10")


def test_primary_lan_address_aborts_without_dev_src(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(SystemExit):
        cli._primary_lan_address()


def test_primary_lan_address_aborts_on_non_ip_source(monkeypatch):
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="dev eth0 src bogus\n"))
    with pytest.raises(SystemExit):
        cli._primary_lan_address()


def test_local_mirror_url_off_by_default(capsys):
    assert cli._local_mirror_url(make_args()) is None
    assert capsys.readouterr().out == ""


def test_local_mirror_url_uses_primary_interface_and_mirror_port(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_primary_lan_address", lambda: ("eth0", "192.168.1.10"))
    url = cli._local_mirror_url(make_args(local_mirror=True))
    assert url == f"http://192.168.1.10:{cli.LOCAL_MIRROR_PORT}"
    assert f"Local mirror: {url} (primary interface eth0)" in capsys.readouterr().out


def test_local_mirror_preflight_probes_healthz(monkeypatch):
    captured = []
    monkeypatch.setattr(cli, "run_capture",
                        lambda client, cmd, **kw: captured.append(cmd) or (0, ""))
    cli._ensure_local_mirror(None, "http://192.168.1.10:8282")
    assert captured == ["curl -fsS --max-time 8 http://192.168.1.10:8282/healthz"]


def test_local_mirror_preflight_aborts_when_unreachable(monkeypatch):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (7, ""))
    with pytest.raises(SystemExit):
        cli._ensure_local_mirror(None, "http://192.168.1.10:8282")


def test_local_mirror_preflight_falls_back_to_lan_url(monkeypatch, capsys):
    # VBox 7.2.22 NAT refuses guest TCP to the 10.0.2.2 gateway alias while
    # the host LAN IP stays reachable: probe once, fall back, return it
    seen = []
    def fake_run(client, cmd, **kw):
        seen.append(cmd)
        return (7 if "10.0.2.2" in cmd else 0, "")
    monkeypatch.setattr(cli, "run_capture", fake_run)
    url = cli._ensure_local_mirror(None, "http://10.0.2.2:8282",
                                   fallback_url="http://192.168.1.10:8282")
    assert url == "http://192.168.1.10:8282"
    assert len(seen) == 2
    assert "trying the host LAN IP mirror http://192.168.1.10:8282" \
        in capsys.readouterr().out


def test_local_mirror_preflight_aborts_when_both_urls_fail(monkeypatch):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (7, ""))
    with pytest.raises(SystemExit):
        cli._ensure_local_mirror(None, "http://10.0.2.2:8282",
                                 fallback_url="http://192.168.1.10:8282")


def test_zcode_post_boot_uploads_payload_and_builds(monkeypatch):
    """--zcode stage two: payload upload + the on-target build steps."""
    uploaded = {}
    monkeypatch.setattr(cli, "upload_text",
                        lambda client, text, path: uploaded.update(path=path, text=text))

    class FakeConn:
        client = None

    monkeypatch.setattr(cli, "_ensure_installed_dns", lambda client, pw: None)
    monkeypatch.setattr(cli, "_run_step", lambda conn, step, pw: None)
    monkeypatch.setattr(cli, "_wait_user_service_active",
                        lambda client, unit, **kw: None)
    cli._post_boot(FakeConn(), "up", "alice", "hst", "TZ", None,
                   zcode_token="tok", zcode_desktop=True)
    assert uploaded["path"] == "/home/alice/zcode-build.tar.b64"
    assert uploaded["text"] == zcode_build_payload()

    steps = post_boot_steps("alice", "hst", "TZ", False, None,
                            True, "tok", zcode_desktop=True)
    titles = [s.title for s in steps]
    assert "Preparing the zcode repository location and build dependencies" in titles
    build = next(s for s in steps if s.id == "zcode-build")
    assert build.timeout == ZCODE_BUILD_TIMEOUT
    assert "ZCODE_DESKTOP=1" in build.commands[0]
    assert "ZCODE_OUT=/var/cache/zcode-build/out" in build.commands[0]
    assert not build.root
    repo = next(s for s in steps if "Registering the local zcode repository" in s.title)
    assert "file:///var/cache/zcode-build/out" in repo.commands[0]
    assert "zcode zcode-desktop" in repo.commands[1]
    assert repo.root
    # deps step bootstraps the world-readable repo location (pacman's
    # DownloadUser=alpm sandbox cannot read the 0700 home)
    deps = next(s for s in steps
                if "Preparing the zcode repository location" in s.title)
    assert "install -d -o alice -g alice /var/cache/zcode-build/out" in deps.commands[1]
    assert "pacman -Sy --needed" in deps.commands[-1]
    assert deps.root
    timer = next(s for s in steps if s.id == "zcode-update")
    assert "enable --now zcode-update.timer" in timer.commands[-1]
    # console installs: no ruby build dep, no zcode-desktop package
    console_steps = post_boot_steps("alice", "hst", "TZ", False, None,
                                    True, "tok", zcode_desktop=False)
    console_deps = next(s for s in console_steps
                        if "Preparing the zcode repository location" in s.title)
    assert "ruby" not in console_deps.commands[-1]
    console_repo = next(s for s in console_steps
                        if "Registering the local zcode repository" in s.title)
    assert console_repo.commands[1].endswith("noconfirm zcode")


def test_run_installation_zcode_smoke(monkeypatch, capsys):
    """Regression: the provisioned --zcode path used to die with NameError
    (undefined zcode_token) at the InstallConfig construction — this exact
    combination had never been exercised. The install script itself stays
    zcode-free (everything zcode lives in stage two now)."""
    uploaded = {}

    class FakeConn:
        client = None

        def close(self):
            pass

    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (0, ""))
    monkeypatch.setattr(cli, "upload_text",
                        lambda client, text, path: uploaded.update(text=text))
    monkeypatch.setattr(cli, "run_streaming", lambda client, cmd, **kw: 0)
    monkeypatch.setattr(cli, "connect_target", lambda *a, **kw: FakeConn())
    args = make_args(virt="kvm", discard=True, zcode=True)
    cli._run_installation(args, "testhost", None, "rootpw", "userpw", None,
                          "key", jump=None, guest_reboot=False, local_mirror=None)
    assert "Uploading installation script" in capsys.readouterr().out
    assert "[zcode]" not in uploaded["text"]
    assert "zcode-repo" not in uploaded["text"]


def test_run_step_fails_fast_on_nonzero_exit(monkeypatch):
    """A failed stage-two command must abort the run (the zcode build once
    failed silently and the flow 'finished' without zcode installed)."""
    from archinstaller.steps import Step

    monkeypatch.setattr(cli, "run_streaming", lambda client, cmd, **kw: 1)
    conn = SimpleNamespace(client=None)
    step = Step("Building zcode", ("cd ~/zcode-build && ./build.sh",),
                context="post-boot", id="zcode-build", timeout=60)
    try:
        cli._run_step(conn, step, "pw")
    except SystemExit as exc:
        assert "Building zcode" in str(exc)
        assert "code 1" in str(exc)
    else:
        raise AssertionError("nonzero exit did not abort the run")


def test_run_step_fails_fast_on_nonzero_exit_root(monkeypatch):
    from archinstaller.steps import Step

    seen = {}
    monkeypatch.setattr(cli, "run_streaming",
                        lambda client, cmd, **kw: seen.update(cmd=cmd) or 0)
    conn = SimpleNamespace(client=None)
    step = Step("Root step", ("pacman -Sy zcode",), context="post-boot", root=True)
    cli._run_step(conn, step, "pw")
    assert seen["cmd"].startswith("sudo -S -p '' ")


def test_target_gateway_parsed_from_default_route(monkeypatch):
    monkeypatch.setattr(
        cli, "run_capture",
        lambda client, cmd, **kw:
            (0, "default via 192.168.1.225 dev enp1s0 proto dhcp src 192.168.1.236\n"))
    assert cli._target_gateway(SimpleNamespace(client=None)) == "192.168.1.225"


def test_target_gateway_none_without_route_or_garbage(monkeypatch):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (0, ""))
    assert cli._target_gateway(SimpleNamespace(client=None)) is None
    monkeypatch.setattr(
        cli, "run_capture",
        lambda client, cmd, **kw: (0, "default via not-an-ip dev eth0\n"))
    assert cli._target_gateway(SimpleNamespace(client=None)) is None


def test_analyze_discard_supported_on_ssd_like_disk(monkeypatch, capsys):
    commands = []
    monkeypatch.setattr(
        cli, "run_capture",
        lambda client, cmd, **kw: commands.append(cmd) or (0, "0\n2147450880\n"))
    assert cli._analyze_discard(LIVE_CONN, "/dev/vda") is True
    assert "/sys/block/vda/queue/discard_max_bytes" in commands[0]
    out = capsys.readouterr().out
    assert "non-rotational (SSD-like)" in out
    assert "discard-capable" in out


def test_analyze_discard_skipped_on_rotational_disk(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (0, "1\n0\n"))
    assert cli._analyze_discard(LIVE_CONN, "/dev/sda") is False
    out = capsys.readouterr().out
    assert "rotational (HDD-like)" in out
    assert "no discard support" in out


def test_analyze_discard_defaults_to_disabled_when_probe_fails(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (1, ""))
    assert cli._analyze_discard(LIVE_CONN, "/dev/vda") is False
    assert "unknown" in capsys.readouterr().out


def test_installed_dns_kicks_dispatcher_hook_when_broken(monkeypatch, capsys):
    state = {"probes": 0}
    captured = []
    streamed = []

    def fake_capture(client, cmd, **kw):
        captured.append(cmd)
        if cmd == cli.DNS_PROBE:
            state["probes"] += 1
            return (0 if state["probes"] > 1 else 1, "")
        return (0, "enp0s3\n")

    def fake_stream(client, cmd, **kw):
        streamed.append(cmd)

    monkeypatch.setattr(cli, "run_capture", fake_capture)
    monkeypatch.setattr(cli, "run_streaming", fake_stream)
    cli._ensure_installed_dns(None, "pw")
    assert len(streamed) == 1
    hook = streamed[0]
    assert "sudo -S -p '' /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback" in hook
    assert "manual --worker" in hook and "ip route show default" in hook
    assert not any("nmcli" in c for c in streamed)  # no direct profile edits from the cli
    assert state["probes"] == 2
    assert "DNS works via the fallback resolvers" in capsys.readouterr().out


def test_installed_dns_reports_when_hook_does_not_help(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_capture", lambda client, cmd, **kw: (1, ""))

    def fake_stream(client, cmd, **kw):
        pass

    monkeypatch.setattr(cli, "run_streaming", fake_stream)
    cli._ensure_installed_dns(None, "pw")
    assert "warning: DNS is still broken" in capsys.readouterr().out


WORKBOOK_KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
                " nameless@example")


def test_run_workbook_placeholders_write_0644_without_secrets(tmp_path, capsys):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out))
    cli._run_workbook(args)
    assert out.stat().st_mode & 0o777 == 0o644
    text = out.read_text()
    assert "{{ROOT_PASSWORD}}" in text and "{{USER_PASSWORD}}" in text
    assert "Caution" not in text
    captured = capsys.readouterr().out
    assert "Workbook written to" in captured
    assert "password:" not in captured  # placeholders mode prints no secrets


def test_run_workbook_with_passwords_embeds_and_locks_file(tmp_path, capsys):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out),
                     with_passwords=True)
    cli._run_workbook(args)
    assert out.stat().st_mode & 0o777 == 0o600
    text = out.read_text()
    assert "{{ROOT_PASSWORD}}" not in text
    assert "Caution — live credentials" in text
    captured = capsys.readouterr().out
    root_line = next(line for line in captured.splitlines()
                     if line.startswith("Root password:"))
    assert root_line.split()[-1] in text  # the printed generated password is embedded
    assert "rotate the passwords once convenient" in captured


def test_run_workbook_explicit_passwords_win_over_generation(tmp_path, capsys):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out),
                     with_passwords=True, root_password="explicit1")
    cli._run_workbook(args)
    assert "printf 'root:%s\\n' 'explicit1' | chpasswd" in out.read_text()
    captured = capsys.readouterr().out
    assert "Root password:" not in captured  # explicit values are not re-printed


def test_run_workbook_opencode_password_embedded_only_with_flag(tmp_path):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out),
                     with_passwords=True, opencode=True)
    cli._run_workbook(args)
    text = out.read_text()
    assert "OPENCODE_SERVER_PASSWORD=" in text
    assert "{{OPENCODE_PASSWORD}}" not in text


def test_run_workbook_zcode_build_steps_and_token_rendering(tmp_path, monkeypatch, capsys):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out),
                     zcode=True)
    cli._run_workbook(args)
    text = out.read_text()
    assert "ZCODE_OUT=/var/cache/zcode-build/out ZCODE_DESKTOP=0 ./build.sh" in text
    assert "Server = file:///var/cache/zcode-build/out" in text
    assert "--token {{ZCODE_TOKEN}}" in text
    assert "zcode-update.timer" in text

    embedded = tmp_path / "w2.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(embedded),
                     with_passwords=True, zcode=True)
    cli._run_workbook(args)
    text = embedded.read_text()
    assert "{{ZCODE_TOKEN}}" not in text
    assert re.search(r"--token [A-Za-z0-9_-]{32}", text)
    captured = capsys.readouterr().out
    assert "zcode token:" in captured


def test_run_workbook_language_ru_renders_russian_prose(tmp_path, capsys):
    out = tmp_path / "w.md"
    args = make_args(command="workbook", ssh_pubkey=WORKBOOK_KEY, out=str(out),
                     language="ru")
    cli._run_workbook(args)
    text = out.read_text()
    assert "# Руководство archinstaller —" in text
    assert "Установка загрузчика GRUB" in text
    assert "Generating /etc/fstab" not in text
    # commands and mode are language-independent
    assert "genfstab -U /mnt/new-root >> /mnt/new-root/etc/fstab" in text
    assert out.stat().st_mode & 0o777 == 0o644
    captured = capsys.readouterr().out
    assert "Workbook written to" in captured
