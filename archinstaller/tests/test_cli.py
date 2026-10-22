import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from archinstaller import cli


LIVE_CONN = SimpleNamespace(client=None)  # probe target: only .client is used


def make_args(**overrides):
    defaults = {
        "command": "install",
        "target": "t", "target_port": 22, "login_user": "root", "login_password": None,
        "jump_host": None, "jump_port": 22, "jump_user": None, "jump_password": None,
        "disk": "/dev/vda", "hostname": None, "username": "nameless",
        "ssh_pubkey": "key", "locale": "en_US.UTF-8", "swap_size": "16G",
        "root_password": None, "user_password": None, "timezone": "Asia/Bangkok",
        "graphical": False, "devel": False, "opencode": False, "local_mirror": False,
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
    from archinstaller.steps import OPENCODE_PORT, opencode_unit
    unit = opencode_unit("secret01")
    assert "OPENCODE_SERVER_USERNAME" not in unit
    assert "Environment=OPENCODE_SERVER_PASSWORD=secret01" in unit
    assert f"ExecStart=/usr/bin/opencode serve --hostname 0.0.0.0 --port {OPENCODE_PORT}" in unit
    assert "WantedBy=default.target" in unit


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
        args, "testhost", "rootpw", "userpw", "opencodepw",
        ["Root password:  rootpw"], "/home/user/.ssh/id_ed25519",
        cli.JumpConfig("10.0.0.1", 2222, "root", "jpw"),
    )
    path = tmp_path / "archinstaller-state-testhost.json"
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
