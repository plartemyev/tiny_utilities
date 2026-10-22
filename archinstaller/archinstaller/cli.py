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
import traceback
from datetime import datetime

import paramiko

from archinstaller import boot_inject
from archinstaller import vbox
from archinstaller import provision
from archinstaller import provision_libvirt
from archinstaller import provision_vbox
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
from archinstaller.steps import (
    DNS_FALLBACK_WORKER,
    OPENCODE_PORT,
    post_boot_steps,
)
from archinstaller.workbook import build_workbook

INSTALL_SCRIPT_PATH = "/root/archinstaller.sh"
DEFAULT_LOGIN_PASSWORD = "local0instaLl"
GENERATED_PASSWORD_LENGTH = 10
OPENCODE_WEB_USER = "opencode"  # server-side basic-auth username, fixed by opencode v2
LOCAL_MIRROR_PORT = 8282  # arch-cache-mirror sibling project, host-published port
PF_FALLBACK_TIMEOUT_S = 90  # NAT port-forward retry after a host-only miss


def _hostonly_mirror_hint(hostonly) -> str:
    """The one-time host firewall command the fast mirror path needs.

    Guest→host traffic ingresses on the host-only interface, which lands
    in the default firewalld zone; the NAT-hairpin fallback bypasses the
    host firewall entirely (host-local delivery), which is why the fast
    path alone needs this exception.
    """
    return ("guest→host on the host-only network is firewalled by default; run "
            "once on the host: firewall-cmd --permanent --add-rich-rule="
            f"'rule family=ipv4 source address={hostonly.network} port "
            f"port={LOCAL_MIRROR_PORT} protocol=tcp accept' && firewall-cmd --reload")

# workbook placeholders: rendered instead of passwords unless --with-passwords
PLACEHOLDER_ROOT = "{{ROOT_PASSWORD}}"
PLACEHOLDER_USER = "{{USER_PASSWORD}}"
PLACEHOLDER_OPENCODE = "{{OPENCODE_PASSWORD}}"


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "resume":
        _resume_stage(args.state_file)
        return
    if args.command == "workbook":
        _run_workbook(args)
        return
    if args.provision != "none":
        _run_provisioned(args)
        return
    _run_install(args)


def _run_install(args: argparse.Namespace) -> None:
    if args.vbox_vm is not None and not vbox.vm_exists(args.vbox_vm):
        sys.exit(f"VirtualBox VM {args.vbox_vm!r} not found via vboxmanage showvminfo")
    local_mirror = _local_mirror_url(args)
    public_key = _resolve_public_key(args.ssh_pubkey)
    hostname = args.hostname or default_hostname()
    login_password, root_password, user_password, opencode_password, generated_notes = _resolve_passwords(args)
    jump = _resolve_jump(args)
    private_key = _private_key_path(args.ssh_pubkey)

    clear_stale_host_key(args.target, args.target_port)
    _run_installation(args, hostname, login_password, root_password, user_password,
                      opencode_password, public_key, jump,
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
            "Automated unattended Arch Linux installation driven over SSH into "
            "the live ISO environment; or render the same run as a markdown "
            "workbook for manual, copy-paste use."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="{install,workbook,resume}")

    # system configuration: shared by install and workbook
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--disk", default="/dev/vda",
                        help="disk to wipe: plain sdX/vdX/hdX device (e.g. /dev/vda) "
                             "or NVMe nvmeXnY device (e.g. /dev/nvme0n1)")
    common.add_argument("--hostname", help="hostname for the new system (default: arch-host-YYYY-MM-DD)")
    common.add_argument("--username", default="nameless", help="user account to create (default: nameless)")
    common.add_argument("--ssh-pubkey", default="~/.ssh/id_ed25519.pub",
                        help="ssh public key: literal key string or path to a file containing one "
                             "(default: ~/.ssh/id_ed25519.pub)")
    common.add_argument("--locale", default="en_US.UTF-8", help="e.g. en_US.UTF-8")
    common.add_argument("--swap-size", default="16G", help="e.g. 16G")
    common.add_argument("--root-password",
                        help="root password for the installed system (generated and printed if omitted)")
    common.add_argument("--user-password",
                        help="password for the created user (generated and printed if omitted)")
    common.add_argument("--timezone", default="Asia/Bangkok",
                        help="timezone to set on the installed system (default: Asia/Bangkok)")
    common.add_argument("--graphical", action="store_true",
                        help="also install graphical packages and the sonic-login-manager desktop session")
    common.add_argument("--devel", action="store_true",
                        help="also install the development package lists (console development; "
                             "graphical development too when --graphical is set)")
    common.add_argument("--opencode", action="store_true",
                        help="also deploy the opencode web server as a systemd user service on "
                             f"port {OPENCODE_PORT} (opens the port in firewalld)")
    common.add_argument("--local-mirror", "--local_mirror", action="store_true",
                        help="point pacman at the local arch-cache-mirror on this host "
                             f"(http://<host-ip>:{LOCAL_MIRROR_PORT}/$repo/os/$arch) for both "
                             "the live install and the installed system; the mirror must "
                             "answer from the target or the install aborts")
    common.add_argument("--virt", choices=("none", "kvm", "qemu", "oracle", "vmware", "microsoft"),
                        help="pin the hypervisor kind instead of probing the target with "
                             "systemd-detect-virt (workbook: default none)")
    common.add_argument("--discard", action="store_true",
                        help="force TRIM/discard enablement instead of probing the target disk "
                             "(without the flag: probe in install mode, off in workbook mode)")

    # provisioned-VM block: install-only, shared by the vbox|libvirt backends
    vm = argparse.ArgumentParser(add_help=False)
    vm.add_argument("--disk-size-gib", type=int, default=45,
                    help="provisioned VM disk size in GiB (default: 45)")
    vm.add_argument("--ram-gib", type=int, default=4,
                    help="provisioned VM memory in GiB (default: 4)")
    vm.add_argument("--cores", type=int, default=4,
                    help="provisioned VM vCPUs (default: 4)")
    vm.add_argument("--iso-path", default="~/Downloads/archlinux.iso",
                    help="Arch ISO to boot in the provisioned VM; must be an "
                         "existing, readable .iso file (default: ~/Downloads/archlinux.iso)")

    p_install = sub.add_parser("install", parents=[common, vm],
                               help="run the unattended installation over SSH")
    p_install.add_argument("--provision", choices=("none", "vbox", "libvirt"),
                           default="none",
                           help="provision a fresh local VM named --hostname and "
                                "install into it (vbox: VirtualBox on this host, "
                                "libvirt: qemu:///system); default 'none' installs "
                                "into an existing machine over SSH")
    p_install.add_argument("--target",
                           help="host running the Arch ISO live environment "
                                "(required without --provision)")
    p_install.add_argument("--target-port", type=int, default=22)
    p_install.add_argument("--login-user", default="root", help="user on the live ISO (default: root)")
    p_install.add_argument("--login-password", default=DEFAULT_LOGIN_PASSWORD,
                           help=f"live ISO password (default: {DEFAULT_LOGIN_PASSWORD}, used only briefly)")
    p_install.add_argument("--jump-host", help="optional SSH jump host")
    p_install.add_argument("--jump-port", type=int, default=22)
    p_install.add_argument("--jump-user", help="jump host user (default: root)")
    p_install.add_argument("--jump-password", help="jump host password (prompted if omitted)")
    p_install.add_argument("--install-timeout", type=int, default=7200,
                           help="seconds to wait for the install script (default: 7200)")
    p_install.add_argument("--reboot-timeout", type=int, default=900,
                           help="seconds to wait for SSH after reboot (default: 900)")
    p_install.add_argument("--no-subnet-scan", action="store_true",
                           help="do not scan the target's /24 for the machine if it came back "
                                "at a different address (the scan verifies the configured hostname)")
    p_install.add_argument("--vbox-vm", metavar="NAME",
                           help="VirtualBox VM name for a host-side reboot: clean power-off, NVRAM "
                                "store backed up (fresh firmware defaults on next boot), boot order "
                                "disk before DVD, start. Makes the first boot work out of the box")

    p_workbook = sub.add_parser("workbook", parents=[common, vm],
                                help="render the run as a markdown workbook (no target needed)")
    p_workbook.add_argument("--provision", choices=("none", "vbox", "libvirt"),
                            default="none",
                            help="also render the VM provisioning commands and the "
                                 "boot/serial instructions (vbox: VirtualBox, libvirt: "
                                 "qemu:///system); host-side facts (ports, network, "
                                 "machine folder) are probed at render time")
    p_workbook.add_argument("--out", metavar="PATH",
                            help="output .md path (default: archinstaller-workbook-<hostname>.md)")
    p_workbook.add_argument("--with-passwords", action="store_true",
                            help="embed real passwords (explicit ones, generated for the rest) "
                                 "instead of placeholders; the file is then written with mode 0600 "
                                 "and must be handled as a secret")
    p_workbook.add_argument("--language", choices=("en", "ru"), default="en",
                            help="prose language of the rendered workbook; commands stay "
                                 "language-independent (default: en)")

    p_resume = sub.add_parser("resume",
                              help="finish a previous install post-reboot from its state file")
    p_resume.add_argument("state_file", metavar="STATE_FILE",
                          help="archinstaller-state-<hostname>.json written before the reboot")

    args = parser.parse_args(argv)
    _validate(parser, args)
    return args


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command == "resume":
        return  # every other value comes from the state file
    if args.command == "install":
        if args.provision != "none":
            _validate_provision(parser, args)
        elif not args.target:
            parser.error("install needs --target (or --provision vbox|libvirt "
                         "to provision a fresh local VM)")
    if args.command == "workbook" and args.provision != "none":
        # no target to boot the ISO from: --iso-path is rendered as given
        if args.virt:
            parser.error("--virt is implied by --provision "
                         "(oracle for vbox, kvm for libvirt)")
        if min(args.cores, args.ram_gib, args.disk_size_gib) < 1:
            parser.error("--cores, --ram-gib and --disk-size-gib must be >= 1")
    if not re.fullmatch(r"(sd|vd|hd)[a-z]+|nvme\d+n\d+", args.disk.rsplit("/", 1)[-1]):
        parser.error(f"--disk must be a device like /dev/vda or /dev/nvme0n1 (got {args.disk!r})")
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


def _validate_provision(parser: argparse.ArgumentParser,
                        args: argparse.Namespace) -> None:
    """--provision owns the transport: the VM's address comes from serial."""
    if args.target:
        parser.error("--target cannot be combined with --provision (the "
                     "provisioned VM's address is discovered over its serial console)")
    if args.jump_host:
        parser.error("--jump-* cannot be combined with --provision "
                     "(provisioned VMs run on this host)")
    if args.vbox_vm:
        parser.error("--vbox-vm reinstalls an existing VM and cannot be "
                     "combined with --provision")
    if args.virt:
        parser.error("--virt is implied by --provision "
                     "(oracle for vbox, kvm for libvirt)")
    if min(args.cores, args.ram_gib, args.disk_size_gib) < 1:
        parser.error("--cores, --ram-gib and --disk-size-gib must be >= 1")
    iso = os.path.expanduser(args.iso_path)
    if not iso.endswith(".iso") or not os.path.isfile(iso):
        parser.error(f"--iso-path must be an existing .iso file (got {args.iso_path!r})")
    if not os.access(iso, os.R_OK):
        parser.error(f"--iso-path is not readable: {iso!r}")


def _run_provisioned(args: argparse.Namespace) -> None:
    """Provision a fresh local VM, install into it, finalize on the host side."""
    hostname = args.hostname or default_hostname()
    public_key = _resolve_public_key(args.ssh_pubkey)
    private_key = _private_key_path(args.ssh_pubkey)
    login_password, root_password, user_password, opencode_password, \
        generated_notes = _resolve_passwords(args)
    if args.provision == "vbox":
        backend = provision_vbox
        keys: boot_inject.Keys = boot_inject.VBoxKeys(hostname)
        args.virt, args.disk = "oracle", "/dev/nvme0n1"
    else:
        backend = provision_libvirt
        keys = boot_inject.VirshKeys(hostname)
        args.virt, args.disk = "kvm", "/dev/vda"
    args.discard = True  # both backends are provisioned for TRIM forwarding
    print(f"Provisioning {args.provision} VM {hostname!r} ({args.cores} vCPUs, "
          f"{args.ram_gib} GiB RAM, {args.disk_size_gib} GiB disk) ...")
    serial_port, ssh_port, hostonly = backend.provision(
        hostname, disk_size_gib=args.disk_size_gib, ram_gib=args.ram_gib,
        cores=args.cores, iso_path=os.path.expanduser(args.iso_path),
        graphical=args.graphical)
    guest_addresses = provision.boot_with_serial(
        restart=lambda: backend.restart(hostname), keys=keys,
        serial_port=serial_port, password=login_password)
    mirror_override = None
    mirror_hint = None
    if args.provision == "vbox":
        nat_ip, hostonly_ip = provision_vbox.select_guest_addresses(
            guest_addresses, hostonly)
        print(f"Guest addresses (serial): NAT {nat_ip}, host-only {hostonly_ip}; "
              f"SSH goes over the host-only path, 127.0.0.1:{ssh_port} "
              "(the NAT port-forward) stays as the fallback")
        args.target = hostonly_ip
        args.target_port = 22
    else:
        args.target = guest_addresses[0]
        args.target_port = ssh_port
    lan_mirror = _local_mirror_url(args)
    if hostonly is not None and lan_mirror is not None:
        # NIC2's gateway is the host itself at a forever-static address;
        # the LAN-IP URL stays as the (slower, NAT-hairpin) fallback for
        # hosts without the one-time firewall exception.
        mirror_override = f"http://{hostonly.gateway}:{LOCAL_MIRROR_PORT}"
        mirror_hint = _hostonly_mirror_hint(hostonly)
    _run_installation(args, hostname, login_password, root_password, user_password,
                      opencode_password, public_key, jump=None, guest_reboot=False,
                      local_mirror=lan_mirror, mirror_override=mirror_override,
                      mirror_hint=mirror_hint, hostonly=hostonly)
    state_path = _state_path(hostname)
    _save_state(state_path, _state_object(args, hostname, root_password,
                                          user_password, opencode_password,
                                          generated_notes, private_key, None))
    print("Finalizing on the host side: stopping the VM, ejecting the ISO, "
          "booting the installed disk ...")
    backend.finalize(hostname)
    print(f"\nWaiting up to {args.reboot_timeout}s for SSH ...")
    clear_stale_host_key(args.target, args.target_port)
    if not wait_for_ssh(args.target, args.target_port, args.username, None,
                        args.reboot_timeout, None, key_filename=private_key):
        recovered = False
        if args.provision == "vbox":
            # NIC1's NAT port-forward is the documented fallback path when
            # the host-only lease did not come back after the reboot.
            print(f"{args.target} did not come back; trying the NAT "
                  f"port-forward 127.0.0.1:{ssh_port} ...")
            clear_stale_host_key("127.0.0.1", ssh_port)
            recovered = wait_for_ssh("127.0.0.1", ssh_port, args.username,
                                     None, PF_FALLBACK_TIMEOUT_S, None,
                                     key_filename=private_key)
            if recovered:
                args.target, args.target_port = "127.0.0.1", ssh_port
        if not recovered:
            found = backend.find_booted_target(hostname)
            if not found:
                _print_recovery_instructions(state_path)
                sys.exit(1)
            print(f"Target found at {found} (was {args.target}).")
            args.target = found
            clear_stale_host_key(args.target, args.target_port)
    _finish_install(args, hostname, user_password, opencode_password,
                    generated_notes, private_key, None, state_path)


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


def _run_workbook(args: argparse.Namespace) -> None:
    """Render the run's commands as a copy-paste markdown workbook.

    Passwords stay placeholders unless --with-passwords is given: then
    explicit values are embedded and the missing ones are generated (the
    file is written 0600 and flagged for rotation).
    """
    public_key = _resolve_public_key(args.ssh_pubkey)
    hostname = args.hostname or default_hostname()
    embed = args.with_passwords
    root_password = args.root_password or (_generated_password() if embed else PLACEHOLDER_ROOT)
    user_password = args.user_password or (_generated_password() if embed else PLACEHOLDER_USER)
    opencode_password = None
    if args.opencode:
        opencode_password = _generated_password() if embed else PLACEHOLDER_OPENCODE
    for label, value in (("--root-password", root_password), ("--user-password", user_password)):
        if "\n" in value:
            sys.exit(f"{label} must contain no newlines")
    virt, discard, disk = args.virt or "none", bool(args.discard), args.disk
    provision_md = None
    if args.provision == "vbox":
        virt, discard, disk = "oracle", True, "/dev/nvme0n1"
        provision_md = _provision_workbook_section(args, hostname, args.language)
    elif args.provision == "libvirt":
        virt, discard, disk = "kvm", True, "/dev/vda"
        provision_md = _provision_workbook_section(args, hostname, args.language)
    cfg = InstallConfig(
        disk=disk,
        hostname=hostname,
        locale=args.locale,
        swap_size=args.swap_size,
        username=args.username,
        root_password=root_password,
        user_password=user_password,
        public_key=public_key,
        graphical=args.graphical,
        devel=args.devel,
        virt=virt,
        discard=discard,
        local_mirror=_local_mirror_url(args),
        timezone=args.timezone,
        opencode=args.opencode,
        opencode_password=opencode_password,
        # provisioned vbox: the MAC exists only after createvm, so the
        # rendered profile carries a placeholder like the passwords do
        hostonly_mac="{{HOSTONLY_MAC}}" if args.provision == "vbox" else "",
        hostonly_address=(f"{provision_vbox.HOSTONLY_GATEWAY.rsplit('.', 1)[0]}"
                          f".{provision_vbox.HOSTONLY_STATIC_FIRST}/24"
                          if args.provision == "vbox" else ""),
    )
    workbook = build_workbook(cfg, passwords_embedded=embed,
                              provision=provision_md, language=args.language)
    out = args.out or f"archinstaller-workbook-{hostname}.md"
    mode = 0o600 if embed else 0o644
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(workbook)
    print(f"Workbook written to {out} (mode {mode:o}).")
    if not embed:
        return
    if not args.root_password:
        print(f"{'Root password:':<16}{root_password}")
    if not args.user_password:
        print(f"{args.username + ' password:':<16}{user_password}")
    if args.opencode:
        print(f"{'opencode password:':<16}{opencode_password}")
    print("The file embeds these credentials: handle it as a secret and "
          "rotate the passwords once convenient.")


def _provision_workbook_section(args: argparse.Namespace, hostname: str,
                                language: str = "en") -> str:
    """The backend's provisioning commands plus the boot/serial instructions.

    Host-side facts (free ports, VirtualBox machine folder, Extension Pack,
    libvirt network) are probed at render time, like the mirror address.
    """
    iso_path = os.path.expanduser(args.iso_path)
    if args.provision == "vbox":
        serial_port, ssh_port = provision_vbox.pick_free_ports(2)
        section = provision_vbox.workbook_section(
            hostname, disk_size_gib=args.disk_size_gib, ram_gib=args.ram_gib,
            cores=args.cores, iso_path=iso_path, graphical=args.graphical,
            serial_port=serial_port, ssh_port=ssh_port, language=language)
        host_side = (f"{provision_vbox.HOSTONLY_GATEWAY.rsplit('.', 1)[0]}"
                     f".{provision_vbox.HOSTONLY_STATIC_FIRST} on the host-only"
                     " network (the NAT port-forward 127.0.0.1:"
                     f"{ssh_port} is the fallback; the guest's NAT address is "
                     f"{provision_vbox.GUEST_ADDRESS})")
    else:
        serial_port = provision_libvirt.pick_free_ports(1)[0]
        network, needs_start = provision_libvirt.plan_network()
        section = provision_libvirt.workbook_section(
            hostname, disk_size_gib=args.disk_size_gib, ram_gib=args.ram_gib,
            cores=args.cores, graphical=args.graphical, iso_path=iso_path,
            serial_port=serial_port, network=network,
            network_start=needs_start, language=language)
        host_side = "the address printed by the ip command above"
    boot = provision.workbook_boot_section(serial_port, host_side,
                                           DEFAULT_LOGIN_PASSWORD,
                                           language=language)
    return section + "\n" + boot


def _resolve_public_key(value: str) -> str:
    """resolve_public_key with a clean exit instead of a traceback.

    The --ssh-pubkey default makes a missing key file a normal preflight
    failure, so it gets the same one-line treatment as the other preflights.
    """
    try:
        return resolve_public_key(value)
    except ValueError as exc:
        sys.exit(f"--ssh-pubkey: {exc}")


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
        target_port=state["target_port"],
        username=state["username"],
        timezone=state["timezone"],
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
        _post_boot(conn, user_password, args.username, hostname, args.timezone,
                   opencode_password)
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
    print(f"         archinstaller resume {state_path}")


def _run_installation(
    args: argparse.Namespace,
    hostname: str,
    login_password: str,
    root_password: str,
    user_password: str,
    opencode_password: str | None,
    public_key: str,
    jump: JumpConfig | None,
    guest_reboot: bool = True,
    local_mirror: str | None = None,
    mirror_override: str | None = None,
    mirror_hint: str | None = None,
    hostonly: "provision_vbox.HostonlyConfig | None" = None,
) -> None:
    print(f"Connecting to live environment {args.target}:{args.target_port} ...")
    conn = connect_target(args.target, args.target_port, args.login_user, login_password, jump)
    try:
        _code, _ = run_capture(conn.client, "test -d /sys/firmware/efi", timeout=30)
        if _code != 0:
            sys.exit("target is not booted in UEFI mode; the install script registers GRUB "
                     "for x86_64-efi and requires an ESP (boot the live ISO in UEFI mode)")
        if args.virt is not None:
            virt = args.virt
            print(f"Virtualization pinned by --virt: {virt}")
        else:
            virt = _detect_virt(conn)
        if args.discard:
            discard = True
            print("TRIM/discard forced on by --discard")
        else:
            discard = _analyze_discard(conn, args.disk)
        if args.vbox_vm is not None and not discard:
            # The attachment flags are flipped host-side after the install
            # (only safe while the VM is powered off), so the live-env probe
            # cannot yet see the discards the installed system will get:
            # configure the guest for them right away.
            print("VirtualBox assist: disk attachments get --discard on; "
                  "enabling guest discard support.")
            discard = True
        lan_mirror = None
        if local_mirror is not None and mirror_override is not None:
            # Provisioned VirtualBox: NIC2's gateway is the host itself at
            # a forever-static address (the LAN-IP URL would roam); the
            # NAT-hairpin LAN URL remains the slower fallback.
            lan_mirror = local_mirror
            local_mirror = mirror_override
            print(f"VM target: advertising the local mirror via the host-only "
                  f"gateway {mirror_override} (static; survives host network "
                  f"roams)")
        elif local_mirror is not None and virt != "none":
            # VM targets: the guest's default gateway is the hypervisor host
            # with a per-backend static address - prefer it over the host's
            # roaming LAN IP so installs keep working after network changes.
            # VBox NAT does not proxy guest TCP to the 10.0.2.2 alias
            # (verified on 7.2.22: connect gets an instant refusal, while
            # ping and the 10.0.2.3 DNS alias work), so the gateway URL is
            # probed first and the LAN IP kept as fallback.
            lan_mirror = local_mirror
            gateway = _target_gateway(conn)
            if gateway is not None:
                print(f"VM target: advertising the local mirror via the guest "
                      f"gateway {gateway} (the hypervisor host) instead of the "
                      f"host LAN IP - valid across host network roams")
                local_mirror = f"http://{gateway}:{LOCAL_MIRROR_PORT}"
            else:
                print("VM target: no default gateway in the live environment; "
                      "keeping the host LAN IP mirror address")
        _ensure_live_dns(conn.client)
        if local_mirror is not None:
            local_mirror = _ensure_local_mirror(conn.client, local_mirror,
                                                fallback_url=lan_mirror,
                                                hint=mirror_hint)
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
            devel=args.devel,
            virt=virt,
            discard=discard,
            local_mirror=local_mirror,
            timezone=args.timezone,
            opencode=args.opencode,
            opencode_password=opencode_password,
            hostonly_mac=hostonly.mac if hostonly else "",
            hostonly_address=hostonly.guest_cidr if hostonly else "",
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


def _target_gateway(conn: SshConnection) -> str | None:
    """Default gateway of the live environment, or None when unresolvable.

    On every local-VM backend (libvirt NAT/routed, VBox NAT/hostonly, qemu
    user networking, Hyper-V) the gateway is the hypervisor host itself,
    and its address is static per backend - unlike the host's LAN IP,
    which roams with the network. Pointing VM installs at the gateway
    therefore survives host-side network changes.
    """
    code, out = run_capture(conn.client, "ip -4 route show default", timeout=30)
    match = re.search(r"^default via (\S+)", out, re.MULTILINE) if code == 0 else None
    if match is None:
        return None
    gateway = match.group(1)
    try:
        ipaddress.IPv4Address(gateway)
    except ValueError:
        return None
    return gateway


def _ensure_local_mirror(client: paramiko.SSHClient, base_url: str,
                         fallback_url: str | None = None,
                         hint: str | None = None) -> str:
    """Verify the live environment can reach the local arch-cache-mirror.

    With --local-mirror the mirror is the only pacman source (the
    mirrorlist keeps no upstream fallback), so a dead mirror must abort
    before pacstrap starts instead of failing deep inside it. Returns the
    URL that passed the probe; when the primary URL is unreachable and a
    fallback_url is given (VM targets: the host LAN IP behind the
    gateway-alias or host-only URL), the fallback is probed and returned
    instead - with a warning, because the fallback path is the slower
    NAT-hairpin one on dual-NIC VirtualBox targets.
    """
    if run_capture(client, f"curl -fsS --max-time 8 {base_url}/healthz",
                   timeout=30)[0] == 0:
        return base_url
    if fallback_url is not None and fallback_url != base_url:
        print(f"mirror {base_url} is not reachable from the target; "
              f"trying the host LAN IP mirror {fallback_url} ...")
        if run_capture(client,
                       f"curl -fsS --max-time 8 {fallback_url}/healthz",
                       timeout=30)[0] == 0:
            print(f"WARNING: continuing over the slower NAT-hairpin path."
                  + (f" {hint}" if hint else ""))
            return fallback_url
    message = (f"the local mirror {base_url} is not reachable from the target "
               "(is the arch-cache-mirror container running and publishing port "
               f"{LOCAL_MIRROR_PORT} on the primary interface?)")
    if hint:
        message += f"; {hint}"
    sys.exit(message + "; rerun with a working mirror or without --local-mirror")


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
        f"sudo -S -p '' {DNS_FALLBACK_WORKER}",
        stdin_text=user_password + "\n",
        timeout=60,
    )
    if _dns_works(client):
        print("DNS works via the fallback resolvers now.")
    else:
        print("warning: DNS is still broken after the fallback hook; fix it manually")


def _post_boot(conn: SshConnection, user_password: str, username: str, hostname: str,
               timezone: str, opencode_password: str | None) -> None:
    """Stage two: run post_boot_steps() on the installed system, in order.

    The DNS probe/kick stays cli-side (it is conditional at runtime) and
    keeps its position between the resolv.conf stub and the timezone;
    the opencode service is polled right after its start step.
    """
    steps = post_boot_steps(username, hostname, timezone,
                            opencode_password is not None, opencode_password,
                            include_dns=False)
    _run_step(conn, steps[0], user_password)  # the resolv.conf stub
    _ensure_installed_dns(conn.client, user_password)
    for step in steps[1:]:
        _run_step(conn, step, user_password)
        if step.id == "opencode-service":
            _wait_user_service_active(conn.client, "opencode.service")


def _run_step(conn: SshConnection, step, user_password: str) -> None:
    for command in step.commands:
        if step.root:
            run_streaming(conn.client, f"sudo -S -p '' {command}",
                          stdin_text=user_password + "\n", timeout=60)
        else:
            run_streaming(conn.client, command, timeout=60)


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
    print("RUN COMPLETE")
    print("=" * 60)
    try:
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
        for note in generated_notes:
            print(note)
        print("New SSH key:    $HOME/.ssh/id_ed25519 (ed25519, empty passphrase)")
        print(f"Public key:\n{public_key.strip()}")
        if opencode_password is not None:
            print(f"opencode web:   http://{args.target}:{OPENCODE_PORT}")
            print(f"opencode user:  {OPENCODE_WEB_USER}")
            print(f"opencode pass:  {opencode_password}")
        print(f"Connect with:\n    {jump_note}")
    except Exception as e:
        print(f"Final result gathering error {e}: {traceback.format_exc()}")
