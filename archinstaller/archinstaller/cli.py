from __future__ import annotations

import argparse
import dataclasses
import getpass
import ipaddress
import json
import os
import re
import secrets
import shlex
import string
import subprocess
import sys
import time
from datetime import datetime

import paramiko

from archinstaller import vbox
from archinstaller.pubkey import resolve_public_key
from archinstaller.script import InstallConfig, build_install_script
from archinstaller.ssh import (
    JumpConfig,
    SshConnection,
    clear_stale_host_key,
    connect_target,
    find_host_in_subnet,
    run_capture,
    run_streaming,
    upload_text,
    wait_for_ssh,
)

INSTALL_SCRIPT_PATH = "/root/archinstaller.sh"
DEFAULT_LOGIN_PASSWORD = "local0instaLl"
GENERATED_PASSWORD_LENGTH = 10
OPENCODE_PORT = 49374
OPENCODE_UNIT_PATH = ".config/systemd/user/opencode.service"
OPENCODE_WEB_USER = "opencode"  # server-side basic-auth username, fixed by opencode v2
LOCAL_MIRROR_PORT = 8282  # arch-cache-mirror sibling project, host-published port


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.resume:
        _resume_stage(args.resume)
        return
    if args.vbox_vm is not None and not vbox.vm_exists(args.vbox_vm):
        sys.exit(f"VirtualBox VM {args.vbox_vm!r} not found via vboxmanage showvminfo")
    local_mirror = _local_mirror_url(args)
    public_key = resolve_public_key(args.ssh_pubkey)
    hostname = args.hostname or default_hostname()
    login_password, root_password, user_password, opencode_password, generated_notes = _resolve_passwords(args)
    jump = _resolve_jump(args)
    private_key = _private_key_path(args.ssh_pubkey)

    clear_stale_host_key(args.target, args.target_port)
    _run_installation(args, hostname, login_password, root_password, user_password, public_key, jump,
                      guest_reboot=args.vbox_vm is None, local_mirror=local_mirror)

    state_path = _state_path(hostname)
    _save_state(state_path, _state_object(args, hostname, root_password, user_password,
                                          opencode_password, generated_notes, private_key, jump))
    if args.vbox_vm is not None:
        _host_side_reboot(args.vbox_vm)
    print(f"\nWaiting up to {args.reboot_timeout}s for SSH ...")
    clear_stale_host_key(args.target, args.target_port)
    if not wait_for_ssh(args.target, args.target_port, args.username, None, args.reboot_timeout, jump,
                        key_filename=private_key):
        found = _find_target_after_reboot(args, hostname, private_key, jump)
        if found is None:
            _print_recovery_instructions(state_path)
            sys.exit(1)
        args.target = found
    _finish_install(args, hostname, user_password, opencode_password, generated_notes,
                    private_key, jump, state_path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="archinstaller",
        description=(
            "Connect over SSH to an Arch Linux live ISO environment and run an "
            "automated unattended installation, then reboot and print the "
            "resulting host IPs, created user and its new SSH public key."
        ),
    )
    parser.add_argument("--target", help="host running the Arch ISO live environment")
    parser.add_argument("--target-port", type=int, default=22)
    parser.add_argument("--login-user", default="root", help="user on the live ISO (default: root)")
    parser.add_argument("--login-password", default=DEFAULT_LOGIN_PASSWORD,
                        help=f"live ISO password (default: {DEFAULT_LOGIN_PASSWORD}, used only briefly)")
    parser.add_argument("--jump-host", help="optional SSH jump host")
    parser.add_argument("--jump-port", type=int, default=22)
    parser.add_argument("--jump-user", help="jump host user (default: root)")
    parser.add_argument("--jump-password", help="jump host password (prompted if omitted)")
    parser.add_argument("--disk", default="/dev/vda",
                        help="disk to wipe: plain sdX/vdX/hdX device, e.g. /dev/vda (no NVMe)")
    parser.add_argument("--hostname", help="hostname for the new system (default: arch-host-YYYY-MM-DD)")
    parser.add_argument("--username", default="nameless", help="user account to create (default: nameless)")
    parser.add_argument("--ssh-pubkey",
                        help="ssh public key: literal key string or path to a file containing one")
    parser.add_argument("--locale", default="en_US.UTF-8", help="e.g. en_US.UTF-8")
    parser.add_argument("--swap-size", default="16G", help="e.g. 16G")
    parser.add_argument("--root-password",
                        help="root password for the installed system (generated and printed if omitted)")
    parser.add_argument("--user-password",
                        help="password for the created user (generated and printed if omitted)")
    parser.add_argument("--timezone", default="Asia/Bangkok",
                        help="timezone to set on the installed system (default: Asia/Bangkok)")
    parser.add_argument("--graphical", action="store_true",
                        help="also install graphical packages and the sonic-login-manager desktop session")
    parser.add_argument("--opencode", action="store_true",
                        help="also deploy the opencode web server as a systemd user service on "
                             f"port {OPENCODE_PORT} (opens the port in firewalld)")
    parser.add_argument("--local-mirror", "--local_mirror", action="store_true",
                        help="point pacman at the local arch-cache-mirror on this host "
                             f"(http://<host-ip>:{LOCAL_MIRROR_PORT}/$repo/os/$arch) for both "
                             "the live install and the installed system; the mirror must "
                             "answer from the target or the install aborts")
    parser.add_argument("--install-timeout", type=int, default=7200,
                        help="seconds to wait for the install script (default: 7200)")
    parser.add_argument("--reboot-timeout", type=int, default=900,
                        help="seconds to wait for SSH after reboot (default: 900)")
    parser.add_argument("--no-subnet-scan", action="store_true",
                        help="do not scan the target's /24 for the machine if it came back "
                             "at a different address (the scan verifies the configured hostname)")
    parser.add_argument("--vbox-vm", metavar="NAME",
                        help="VirtualBox VM name for a host-side reboot: clean power-off, NVRAM "
                             "store backed up (fresh firmware defaults on next boot), boot order "
                             "disk before DVD, start. Makes the first boot work out of the box")
    parser.add_argument("--resume", metavar="STATE_FILE",
                        help="skip the install and finish a previous run post-reboot from its "
                             "state file (all other arguments are ignored)")
    args = parser.parse_args(argv)
    if args.resume:
        return args
    if not args.target:
        parser.error("--target is required (unless --resume is used)")
    if not args.ssh_pubkey:
        parser.error("--ssh-pubkey is required (unless --resume is used)")
    _validate(parser, args)
    return args


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not re.fullmatch(r"(sd|vd|hd)[a-z]+", args.disk.rsplit("/", 1)[-1]):
        parser.error(f"--disk must be a device like /dev/vda or /dev/sda (got {args.disk!r})")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", args.hostname or default_hostname()):
        parser.error(f"--hostname contains invalid characters (got {args.hostname!r})")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.username):
        parser.error(f"--username is not a valid user name (got {args.username!r})")
    if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?\.UTF-8", args.locale):
        parser.error(f"--locale must look like en_US.UTF-8 (got {args.locale!r})")
    if not re.fullmatch(r"\d+[KMGT]?", args.swap_size):
        parser.error(f"--swap-size must look like 16G (got {args.swap_size!r})")
    if not re.fullmatch(r"[A-Za-z]+/[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)?", args.timezone):
        parser.error(f"--timezone must look like Area/City, e.g. Asia/Bangkok (got {args.timezone!r})")


def default_hostname() -> str:
    return f"arch-host-{datetime.now().astimezone().date().isoformat()}"


def _resolve_passwords(args: argparse.Namespace) -> tuple[str, str, str, str | None, list[str]]:
    login = args.login_password or DEFAULT_LOGIN_PASSWORD
    root = args.root_password or _generated_password()
    user = args.user_password or _generated_password()
    opencode = _generated_password() if args.opencode else None
    required = [("--login-password", login), ("--root-password", root), ("--user-password", user)]
    if opencode is not None:
        required.append(("opencode password", opencode))
    for label, value in required:
        if not value or "\n" in value:
            sys.exit(f"{label} must be non-empty and contain no newlines")
    generated_notes = []
    if not args.root_password:
        generated_notes.append(f"{'Root password:':<16}{root}")
    if not args.user_password:
        generated_notes.append(f"{args.username + ' password:':<16}{user}")
    return login, root, user, opencode, generated_notes


def _generated_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(GENERATED_PASSWORD_LENGTH))


def _private_key_path(pubkey_arg: str) -> str | None:
    """Private key matching --ssh-pubkey when it was given as a file path."""
    path = os.path.expanduser(pubkey_arg.strip())
    if not os.path.isfile(path):
        return None
    if path.endswith(".pub"):
        candidate = path[:-4]
    else:
        candidate = path
    return candidate if os.path.isfile(candidate) else None


def _primary_lan_address() -> tuple[str, str]:
    """Interface and IPv4 source address of the host's default route.

    The local arch-cache-mirror is published on this address, and it is
    what a same-LAN target can reach.
    """
    proc = subprocess.run(["ip", "-4", "route", "get", "1.1.1.1"],
                          capture_output=True, text=True, timeout=10, check=False)
    match = re.search(r"\bdev (\S+) .*\bsrc (\S+)", proc.stdout)
    if proc.returncode != 0 or match is None:
        sys.exit("cannot determine the primary LAN interface (no dev/src in "
                 "`ip -4 route get 1.1.1.1` output); --local-mirror needs it "
                 "to advertise the local arch-cache-mirror address")
    iface, ip = match.group(1), match.group(2)
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        sys.exit(f"`ip -4 route get 1.1.1.1` reported a non-IPv4 source {ip!r}")
    return iface, ip


def _local_mirror_url(args: argparse.Namespace) -> str | None:
    """Base URL of the host's arch-cache-mirror when --local-mirror is set."""
    if not args.local_mirror:
        return None
    iface, ip = _primary_lan_address()
    url = f"http://{ip}:{LOCAL_MIRROR_PORT}"
    print(f"Local mirror: {url} (primary interface {iface})")
    return url


def _resolve_jump(args: argparse.Namespace) -> JumpConfig | None:
    if not args.jump_host:
        return None
    username = args.jump_user or "root"
    password = args.jump_password or getpass.getpass(f"Password for {username}@{args.jump_host} (jump host): ")
    if not password:
        sys.exit("jump host password must be non-empty")
    return JumpConfig(args.jump_host, args.jump_port, username, password)


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def _find_target_after_reboot(args: argparse.Namespace, hostname: str,
                              private_key: str | None, jump: JumpConfig | None) -> str | None:
    """Fallback after a reboot timeout: probe the target's /24 by hostname."""
    if args.no_subnet_scan:
        reason = "subnet scan disabled (--no-subnet-scan)"
    elif jump is not None:
        reason = "subnet scan is not supported with a jump host"
    elif not _is_ipv4(args.target):
        reason = f"{args.target} is not a scannable IPv4 address"
    else:
        reason = None
    if reason:
        print(f"Target did not come back within {args.reboot_timeout}s ({reason}).")
        return None
    print(f"Scanning the /24 around {args.target} for an SSH host named {hostname!r} ...")
    found = find_host_in_subnet(args.target, args.target_port, args.username, hostname, private_key)
    if found is None:
        print(f"Target did not come back within {args.reboot_timeout}s and nothing in its"
              f" /24 reports hostname {hostname!r}.")
        return None
    print(f"Target found at {found} (was {args.target}).")
    clear_stale_host_key(found, args.target_port)
    return found


def _detect_virt(conn: SshConnection) -> str:
    """Hypervisor of the target per systemd-detect-virt in the live env."""
    _code, out = run_capture(conn.client, "systemd-detect-virt || true", timeout=30)
    virt = out.strip().splitlines()[0].strip() if out.strip() else "none"
    print(f"Detected virtualization: {virt}")
    return virt


def _analyze_discard(conn: SshConnection, disk: str) -> bool:
    """TRIM/discard feasibility of the target disk, probed in the live env.

    discard_max_bytes > 0 means the guest kernel sees a discard-capable
    device: real SSD/NVMe hardware, or a VM disk whose hypervisor forwards
    guest TRIM. Rotational is reported for context only (VirtualBox disks
    report rotational=1 until --nonrotational is set on the attachment).
    """
    dev = disk.rsplit("/", 1)[-1]
    _code, out = run_capture(
        conn.client,
        (f"cat /sys/block/{dev}/queue/rotational"
         f" /sys/block/{dev}/queue/discard_max_bytes 2>/dev/null"),
        timeout=30,
    )
    values = out.split()
    kind = {"0": "non-rotational (SSD-like)", "1": "rotational (HDD-like)"}.get(
        values[0] if values else "", "unknown")
    supported = len(values) == 2 and values[1].isdigit() and int(values[1]) > 0
    verdict = ("discard-capable: fstrim.timer, swapfile discard and (on VMs)"
               " root discard will be enabled"
               if supported else
               "no discard support: TRIM stays disabled")
    print(f"TRIM/discard analysis of {disk}: {kind}, {verdict}")
    return supported


def _host_side_reboot(vm: str) -> None:
    print(f"VirtualBox assist: powering off VM {vm!r} ...")
    vbox.poweroff(vm)
    try:
        changed = vbox.enable_discard(vm)
        print(f"Discard/TRIM forwarding (--discard, --nonrotational) enabled on: "
              f"{', '.join(changed)}.")
    except vbox.VboxError as exc:
        print(f"warning: could not enable discard forwarding ({exc}); "
              f"guest TRIM will not compact the drive images")
    backup = vbox.reset_nvram(vm)
    print(f"NVRAM store moved to {backup}; next boot gets fresh firmware defaults.")
    vbox.order_disk_before_dvd(vm)
    vbox.start(vm)
    print(f"VM {vm!r} started with boot order: floppy, disk, dvd (disk first).")


def _state_path(hostname: str) -> str:
    return f"archinstaller-state-{hostname}.json"


def _state_object(args: argparse.Namespace, hostname: str, root_password: str, user_password: str,
                  opencode_password: str | None, generated_notes: list[str],
                  private_key: str | None, jump: JumpConfig | None) -> dict:
    return {
        "version": 1,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": args.target,
        "target_port": args.target_port,
        "username": args.username,
        "hostname": hostname,
        "timezone": args.timezone,
        "reboot_timeout": args.reboot_timeout,
        "private_key": private_key,
        "jump": dataclasses.asdict(jump) if jump is not None else None,
        "opencode": opencode_password is not None,
        "opencode_password": opencode_password,
        "root_password": root_password,
        "user_password": user_password,
        "generated_notes": generated_notes,
    }


def _save_state(path: str, state: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def _load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"cannot read state file {path}: {exc}")
    missing = [key for key in REQUIRED_STATE_KEYS if key not in state]
    if missing:
        sys.exit(f"state file {path} is missing keys: {', '.join(missing)}")
    return state


REQUIRED_STATE_KEYS = (
    "target", "target_port", "username", "hostname", "timezone", "reboot_timeout",
    "private_key", "jump", "opencode", "opencode_password", "root_password",
    "user_password", "generated_notes",
)


def _resume_stage(path: str) -> None:
    state = _load_state(path)
    jump = JumpConfig(**state["jump"]) if state.get("jump") is not None else None
    print(f"Resuming from {path}: waiting for {state['username']}@{state['target']} ...")
    clear_stale_host_key(state["target"], state["target_port"])
    if not wait_for_ssh(state["target"], state["target_port"], state["username"], None,
                        state["reboot_timeout"], jump, key_filename=state["private_key"]):
        found = None
        if jump is None and _is_ipv4(state["target"]):
            print(f"Scanning the /24 around {state['target']} for an SSH host named"
                  f" {state['hostname']!r} ...")
            found = find_host_in_subnet(state["target"], state["target_port"], state["username"],
                                        state["hostname"], state["private_key"])
        if found is None:
            _print_recovery_instructions(path)
            sys.exit(1)
        print(f"Target found at {found} (was {state['target']}).")
        state["target"] = found
        _save_state(path, state)
        clear_stale_host_key(found, state["target_port"])
    args = argparse.Namespace(
        target=state["target"],
        username=state["username"],
        jump_host=state["jump"]["host"] if state.get("jump") is not None else None,
    )
    opencode_password = state["opencode_password"] if state["opencode"] else None
    _finish_install(args, state["hostname"], state["user_password"], opencode_password,
                    state["generated_notes"], state["private_key"], jump, path)


def _finish_install(args: argparse.Namespace, hostname: str, user_password: str,
                    opencode_password: str | None, generated_notes: list[str],
                    private_key: str | None, jump: JumpConfig | None, state_path: str) -> None:
    conn = connect_target(args.target, args.target_port, args.username, None, jump,
                          key_filename=private_key)
    try:
        _post_boot(conn, user_password, args.username, hostname, args.timezone)
        if opencode_password is not None:
            _setup_opencode(conn, args.username, user_password, opencode_password)
        _print_summary(conn, args, hostname, generated_notes, opencode_password)
    finally:
        conn.close()
    os.unlink(state_path)  # finished: the file holds passwords, do not keep it


def _print_recovery_instructions(state_path: str) -> None:
    print(f"\nThe install itself is complete; state saved to {state_path}.")
    print("Recovery steps:")
    print("  1. Check the machine's console:")
    print("     - If it sits in the EFI boot manager, pick the hard disk entry; the")
    print("       installer left a fallback bootloader at \\EFI\\BOOT\\BOOTX64.EFI.")
    print("     - VirtualBox: guest-written boot entries die on guest reboots and a")
    print("       stale BootOrder can trap the boot. One-time host-side reset:")
    print('           vboxmanage controlvm "<vm>" acpipowerbutton')
    print("           mv '<nvram-file>' '<nvram-file>.bak'")
    print('           vboxmanage modifyvm "<vm>" --boot2 disk --boot3 dvd')
    print('           vboxmanage startvm "<vm>"')
    print('       (next time pass --vbox-vm "<vm>" to automate this)')
    print("  2. When the installed system is up (at any address), finish the setup:")
    print(f"         archinstaller --resume {state_path}")


def _run_installation(
    args: argparse.Namespace,
    hostname: str,
    login_password: str,
    root_password: str,
    user_password: str,
    public_key: str,
    jump: JumpConfig | None,
    guest_reboot: bool = True,
    local_mirror: str | None = None,
) -> None:
    print(f"Connecting to live environment {args.target}:{args.target_port} ...")
    conn = connect_target(args.target, args.target_port, args.login_user, login_password, jump)
    try:
        _code, _ = run_capture(conn.client, "test -d /sys/firmware/efi", timeout=30)
        if _code != 0:
            sys.exit("target is not booted in UEFI mode; the install script registers GRUB "
                     "for x86_64-efi and requires an ESP (boot the live ISO in UEFI mode)")
        virt = _detect_virt(conn)
        discard = _analyze_discard(conn, args.disk)
        if args.vbox_vm is not None and not discard:
            # The attachment flags are flipped host-side after the install
            # (only safe while the VM is powered off), so the live-env probe
            # cannot yet see the discards the installed system will get:
            # configure the guest for them right away.
            print("VirtualBox assist: disk attachments get --discard on; "
                  "enabling guest discard support.")
            discard = True
        _ensure_live_dns(conn.client)
        if local_mirror is not None:
            _ensure_local_mirror(conn.client, local_mirror)
        cfg = InstallConfig(
            disk=args.disk,
            hostname=hostname,
            locale=args.locale,
            swap_size=args.swap_size,
            username=args.username,
            root_password=root_password,
            user_password=user_password,
            public_key=public_key,
            graphical=args.graphical,
            virt=virt,
            discard=discard,
            local_mirror=local_mirror,
        )
        print(f"Uploading installation script to {INSTALL_SCRIPT_PATH} ...")
        upload_text(conn.client, build_install_script(cfg), INSTALL_SCRIPT_PATH)
        print("Starting installation; full output follows ...")
        code = run_streaming(
            conn.client,
            f"bash {shlex.quote(INSTALL_SCRIPT_PATH)}",
            timeout=args.install_timeout,
            pty=True,
        )
        if code != 0:
            sys.exit(f"installation script exited with code {code}")
        if guest_reboot:
            print("Installation finished. Rebooting target ...")
            _reboot(conn)
        else:
            print("Installation finished; the VM will be rebooted from the host side.")
    finally:
        conn.close()


def _reboot(conn: SshConnection) -> None:
    try:
        run_capture(conn.client, "systemctl reboot", timeout=30)
    except (TimeoutError, EOFError, OSError, paramiko.SSHException):
        pass


DNS_PROBE = "timeout 15 getent hosts archlinux.org >/dev/null"


def _dns_works(client: paramiko.SSHClient) -> bool:
    code, _out = run_capture(client, DNS_PROBE, timeout=30)
    return code == 0


def _ensure_live_dns(client: paramiko.SSHClient) -> None:
    """Verify DNS on the live ISO before the (destructive) install starts.

    pacstrap needs working resolution; a target whose DHCP hands out an
    unusable DNS server would die deep inside pacstrap with unrelated
    mirror errors. Fall back to public resolvers on the default-route
    interface (transient — the live environment dies at reboot anyway).
    """
    if _dns_works(client):
        return
    print("DNS resolution is broken on the target; pointing the default-route "
          "interface at public resolvers for the install.")
    _code, iface = run_capture(client, "ip route show default | awk '{print $5; exit}'",
                               timeout=30)
    if _code == 0 and iface.strip():
        run_capture(client,
                    f"resolvectl dns {shlex.quote(iface.strip())} 1.1.1.1 8.8.8.8",
                    timeout=30)
    if not _dns_works(client):
        sys.exit("target DNS is broken and the public-resolver fallback did not "
                 "help; fix the target's DNS (check the hypervisor NAT/DHCP "
                 "settings) and rerun")
    print("DNS fallback is active; continuing.")


def _ensure_local_mirror(client: paramiko.SSHClient, base_url: str) -> None:
    """Verify the live environment can reach the local arch-cache-mirror.

    With --local-mirror the mirror is the only pacman source (the
    mirrorlist keeps no upstream fallback), so a dead mirror must abort
    before pacstrap starts instead of failing deep inside it.
    """
    _code, _ = run_capture(client, f"curl -fsS --max-time 8 {base_url}/healthz", timeout=30)
    if _code != 0:
        sys.exit(f"the local mirror {base_url} is not reachable from the target "
                 "(is the arch-cache-mirror container running and publishing port "
                 f"{LOCAL_MIRROR_PORT} on the primary interface?); rerun with a "
                 "working mirror or without --local-mirror")


def _ensure_installed_dns(client: paramiko.SSHClient, user_password: str) -> None:
    """Post-boot DNS health check.

    The persistent fallback logic lives in the NetworkManager dispatcher hook
    installed by the install script: it probes the lease's DNS servers on
    every network event and uses them only while at least one answers, so
    router DNS tuning applies on healthy networks. At stage-two time the
    lease events have already fired, so when resolution is broken right now
    the hook is invoked once directly (synchronously, as root).
    """
    if _dns_works(client):
        return
    print("DNS resolution is broken; running the DNS fallback dispatcher hook ...")
    run_streaming(
        client,
        "sudo -S -p '' /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback"
        " \"$(ip route show default | awk '{print $5; exit}')\" manual --worker",
        stdin_text=user_password + "\n",
        timeout=60,
    )
    if _dns_works(client):
        print("DNS works via the fallback resolvers now.")
    else:
        print("warning: DNS is still broken after the fallback hook; fix it manually")


def _post_boot(conn: SshConnection, user_password: str, username: str, hostname: str, timezone: str) -> None:
    run_streaming(
        conn.client,
        "sudo -S -p '' ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf",
        stdin_text=user_password + "\n",
        timeout=60,
    )
    _ensure_installed_dns(conn.client, user_password)
    run_streaming(
        conn.client,
        f"sudo -S -p '' timedatectl set-timezone {shlex.quote(timezone)}",
        stdin_text=user_password + "\n",
        timeout=60,
    )
    comment = shlex.quote(f"{username}@{hostname}")
    run_streaming(
        conn.client,
        "test -f $HOME/.ssh/id_ed25519.pub || ssh-keygen -q -t ed25519 -N ''"
        f" -f $HOME/.ssh/id_ed25519 -C {comment}",
        timeout=60,
    )


def _opencode_unit(opencode_password: str) -> str:
    return "\n".join([
        "[Unit]",
        "Description=OpenCode web server",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f"Environment=OPENCODE_SERVER_PASSWORD={opencode_password}",
        f"ExecStart=/usr/bin/opencode serve --hostname 0.0.0.0 --port {OPENCODE_PORT}",
        "Restart=on-failure",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]) + "\n"


def _setup_opencode(conn: SshConnection, username: str, user_password: str, opencode_password: str) -> None:
    print("Setting up the opencode web service ...")
    run_streaming(conn.client, f"sudo -S -p '' loginctl enable-linger {shlex.quote(username)}",
                  stdin_text=user_password + "\n", timeout=60)
    run_streaming(conn.client, "mkdir -p ~/.config/systemd/user", timeout=60)
    upload_text(conn.client, _opencode_unit(opencode_password), OPENCODE_UNIT_PATH)
    run_streaming(conn.client, f"chmod 644 $HOME/{OPENCODE_UNIT_PATH}", timeout=60)
    run_streaming(conn.client, "systemctl --user daemon-reload", timeout=60)
    run_streaming(conn.client, "systemctl --user enable opencode.service", timeout=60)
    run_streaming(conn.client, "systemctl --user start --no-block opencode.service", timeout=60)
    _wait_user_service_active(conn.client, "opencode.service")
    run_streaming(conn.client, f"sudo -S -p '' firewall-cmd --permanent --add-port={OPENCODE_PORT}/tcp",
                  stdin_text=user_password + "\n", timeout=60)
    run_streaming(conn.client, "sudo -S -p '' firewall-cmd --reload",
                  stdin_text=user_password + "\n", timeout=60)


def _wait_user_service_active(client: paramiko.SSHClient, unit: str,
                              tries: int = 10, delay: float = 1.0) -> None:
    """Poll `systemctl --user is-active` until unit reports active.

    `systemctl --user start` may occasionally hold the SSH channel open
    until the read timeout, so the start is queued with --no-block and
    the result is verified here instead.
    """
    for _ in range(tries):
        code, out = run_capture(client, f"systemctl --user is-active {unit}", timeout=30)
        if code == 0 and out.strip() == "active":
            return
        time.sleep(delay)
    sys.exit(f"{unit} did not become active after {tries} attempts")


def _print_summary(conn: SshConnection, args: argparse.Namespace, hostname: str,
                   generated_notes: list[str], opencode_password: str | None = None) -> None:
    print()
    print("=" * 60)
    print("INSTALLATION COMPLETE")
    print("=" * 60)
    for note in generated_notes:
        print(note)
    _code, private = run_capture(conn.client, "ip -4 -o addr show scope global")
    public_code, public = run_capture(
        conn.client,
        "attempt=1; while true; do curl -4 -sf --max-time 15 https://ifconfig.me && break;"
        " [ \"$attempt\" -ge 3 ] && exit 1;"
        " echo \"curl failed (attempt $attempt/3), retrying in 5s...\";"
        " attempt=$((attempt + 1)); sleep 5; done",
    )
    key_code, public_key = run_capture(conn.client, "cat $HOME/.ssh/id_ed25519.pub")
    if key_code != 0:
        sys.exit("failed to read the newly generated public key on the target")
    interfaces = [
        f"{fields[1]} {fields[3]}"
        for fields in (line.split() for line in private.splitlines())
        if len(fields) >= 4
    ]
    jump_note = f"ssh -J {args.jump_host} {args.username}@{args.target}" if args.jump_host \
        else f"ssh {args.username}@{args.target}"
    print()
    print("=" * 60)
    print("INSTALLATION COMPLETE")
    print("=" * 60)
    print(f"Target host:    {args.target} (hostname: {hostname})")
    print(f"Private IP(s):  {'; '.join(interfaces) if interfaces else '(none found)'}")
    if public_code == 0 and public.strip():
        print(f"Public IP:      {public.strip()}")
    else:
        print("Public IP:      (unavailable)")
    print(f"Created user:   {args.username}")
    print("New SSH key:    $HOME/.ssh/id_ed25519 (ed25519, empty passphrase)")
    print(f"Public key:\n{public_key.strip()}")
    if opencode_password is not None:
        print(f"opencode web:   http://{args.target}:{OPENCODE_PORT}")
        print(f"opencode user:  {OPENCODE_WEB_USER}")
        print(f"opencode pass:  {opencode_password}")
    print(f"Connect with:\n    {jump_note}")
