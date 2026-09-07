from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import shlex
import string
import sys
from datetime import date

import paramiko

from archinstaller.pubkey import resolve_public_key
from archinstaller.script import InstallConfig, build_install_script
from archinstaller.ssh import (
    JumpConfig,
    SshConnection,
    clear_stale_host_key,
    connect_target,
    run_capture,
    run_streaming,
    upload_text,
    wait_for_ssh,
)

INSTALL_SCRIPT_PATH = "/root/archinstaller.sh"
DEFAULT_LOGIN_PASSWORD = "local0instaLl"
GENERATED_PASSWORD_LENGTH = 10


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    public_key = resolve_public_key(args.ssh_pubkey)
    hostname = args.hostname or default_hostname()
    login_password, root_password, user_password = _resolve_passwords(args)
    jump = _resolve_jump(args)
    private_key = _private_key_path(args.ssh_pubkey)

    clear_stale_host_key(args.target, args.target_port)
    _run_installation(args, hostname, login_password, root_password, user_password, public_key, jump)

    print(f"\nTarget is rebooting; waiting up to {args.reboot_timeout}s for SSH ...")
    clear_stale_host_key(args.target, args.target_port)
    if not wait_for_ssh(args.target, args.target_port, args.username, None, args.reboot_timeout, jump,
                        key_filename=private_key):
        sys.exit(f"target did not come back within {args.reboot_timeout}s; connect manually and inspect")
    conn = connect_target(args.target, args.target_port, args.username, None, jump, key_filename=private_key)
    try:
        _post_boot(conn, user_password, args.username, hostname, args.timezone)
        _print_summary(conn, args, hostname)
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="archinstaller",
        description=(
            "Connect over SSH to an Arch Linux live ISO environment and run an "
            "automated unattended installation, then reboot and print the "
            "resulting host IPs, created user and its new SSH public key."
        ),
    )
    parser.add_argument("--target", required=True, help="host running the Arch ISO live environment")
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
    parser.add_argument("--ssh-pubkey", required=True,
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
                        help="also install graphical packages and the SDDM desktop session")
    parser.add_argument("--install-timeout", type=int, default=7200,
                        help="seconds to wait for the install script (default: 7200)")
    parser.add_argument("--reboot-timeout", type=int, default=900,
                        help="seconds to wait for SSH after reboot (default: 900)")
    args = parser.parse_args(argv)
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
    return f"arch-host-{date.today().isoformat()}"


def _resolve_passwords(args: argparse.Namespace) -> tuple[str, str, str]:
    login = args.login_password or DEFAULT_LOGIN_PASSWORD
    root = args.root_password or _generated_password()
    user = args.user_password or _generated_password()
    for label, value in (("--login-password", login), ("--root-password", root), ("--user-password", user)):
        if not value or "\n" in value:
            sys.exit(f"{label} must be non-empty and contain no newlines")
    if not args.root_password:
        print(f"Generated root password: {root}")
    if not args.user_password:
        print(f"Generated {args.username} password: {user}")
    return login, root, user


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


def _resolve_jump(args: argparse.Namespace) -> JumpConfig | None:
    if not args.jump_host:
        return None
    username = args.jump_user or "root"
    password = args.jump_password or getpass.getpass(f"Password for {username}@{args.jump_host} (jump host): ")
    if not password:
        sys.exit("jump host password must be non-empty")
    return JumpConfig(args.jump_host, args.jump_port, username, password)


def _run_installation(
    args: argparse.Namespace,
    hostname: str,
    login_password: str,
    root_password: str,
    user_password: str,
    public_key: str,
    jump: JumpConfig | None,
) -> None:
    print(f"Connecting to live environment {args.target}:{args.target_port} ...")
    conn = connect_target(args.target, args.target_port, args.login_user, login_password, jump)
    try:
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
        print("Installation finished. Rebooting target ...")
        _reboot(conn)
    finally:
        conn.close()


def _reboot(conn: SshConnection) -> None:
    try:
        run_capture(conn.client, "systemctl reboot", timeout=30)
    except (TimeoutError, EOFError, OSError, paramiko.SSHException):
        pass


def _post_boot(conn: SshConnection, user_password: str, username: str, hostname: str, timezone: str) -> None:
    run_streaming(
        conn.client,
        "sudo -S -p '' ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf",
        stdin_text=user_password + "\n",
        timeout=60,
    )
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


def _print_summary(conn: SshConnection, args: argparse.Namespace, hostname: str) -> None:
    code, private = run_capture(conn.client, "ip -4 -o addr show scope global")
    public_code, public = run_capture(conn.client, "curl -4 -sf --max-time 15 https://ifconfig.me")
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
    print(f"Connect with:\n    {jump_note}")
