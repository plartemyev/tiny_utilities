from __future__ import annotations

import dataclasses
import ipaddress
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko

CONNECT_TIMEOUT = 30
POLL_SECONDS = 10
PUMP_INTERVAL = 0.1
RECV_CHUNK = 4096
SCAN_PORT_TIMEOUT = 0.5
SCAN_CONNECT_TIMEOUT = 5
SCAN_COMMAND_TIMEOUT = 15
SCAN_MAX_WORKERS = 64
SCAN_HOSTNAME_COMMAND = "cat /etc/hostname"


@dataclasses.dataclass(frozen=True)
class JumpConfig:
    host: str
    port: int
    username: str
    password: str


@dataclasses.dataclass
class SshConnection:
    client: paramiko.SSHClient
    jump_client: paramiko.SSHClient | None = None

    def close(self) -> None:
        self.client.close()
        if self.jump_client is not None:
            self.jump_client.close()


def connect_target(
    host: str,
    port: int,
    username: str,
    password: str | None,
    jump: JumpConfig | None = None,
    key_filename: str | None = None,
    timeout: float = CONNECT_TIMEOUT,
) -> SshConnection:
    sock = None
    jump_client = None
    if jump is not None:
        jump_client = _connect_single(jump.host, jump.port, jump.username, jump.password)
        sock = jump_client.get_transport().open_channel(
            "direct-tcpip", (host, port), (jump.host, jump.port),
        )
    try:
        client = _connect_single(host, port, username, password, sock=sock,
                                 key_filename=key_filename, timeout=timeout)
    except (OSError, paramiko.SSHException, EOFError):
        if jump_client is not None:
            jump_client.close()
        raise
    return SshConnection(client, jump_client)


def upload_text(client: paramiko.SSHClient, text: str, path: str) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.open(path, "wb") as fh:
            fh.write(text.encode())
        sftp.chmod(path, 0o700)
    finally:
        sftp.close()


def run_streaming(
    client: paramiko.SSHClient,
    command: str,
    *,
    stdin_text: str = "",
    timeout: float,
    pty: bool = False,
) -> int:
    chan = _exec(client, command, pty)
    try:
        _send_stdin(chan, stdin_text)
        deadline = time.monotonic() + timeout
        while _pending(chan):
            if time.monotonic() > deadline:
                raise TimeoutError(f"command timed out after {timeout}s: {command}")
            _drain(chan)
            time.sleep(PUMP_INTERVAL)
        _drain(chan)
        return chan.recv_exit_status()
    finally:
        chan.close()


def run_capture(
    client: paramiko.SSHClient,
    command: str,
    *,
    stdin_text: str = "",
    timeout: float = 60,
) -> tuple[int, str]:
    chan = _exec(client, command, pty=False)
    try:
        _send_stdin(chan, stdin_text)
        chunks: list[bytes] = []
        deadline = time.monotonic() + timeout
        while _pending(chan):
            if time.monotonic() > deadline:
                raise TimeoutError(f"command timed out after {timeout}s: {command}")
            if chan.recv_ready():
                chunks.append(chan.recv(RECV_CHUNK))
            else:
                time.sleep(PUMP_INTERVAL)
        while chan.recv_ready():
            chunks.append(chan.recv(RECV_CHUNK))
        return chan.recv_exit_status(), b"".join(chunks).decode(errors="replace")
    finally:
        chan.close()


def wait_for_ssh(
    host: str,
    port: int,
    username: str,
    password: str | None,
    timeout: float,
    jump: JumpConfig | None = None,
    key_filename: str | None = None,
) -> bool:
    attempts = max(1, int(timeout // POLL_SECONDS))
    for _ in range(attempts):
        try:
            conn = connect_target(host, port, username, password, jump, key_filename=key_filename)
            conn.close()
            return True
        except (OSError, paramiko.SSHException, EOFError):
            time.sleep(POLL_SECONDS)
    return False


def subnet_addresses(address: str) -> list[str]:
    """Usable host addresses of the /24 that contains address (at most 254)."""
    network = ipaddress.ip_network(f"{address}/24", strict=False)
    return [str(host) for host in network.hosts()]


def find_host_in_subnet(
    address: str,
    port: int,
    username: str,
    hostname: str,
    key_filename: str | None,
) -> str | None:
    """Look for the rebooted target in the /24 around address.

    An address matches when its SSH server authenticates username with the
    install key and reports hostname; returns the first match or None.
    """
    candidates = subnet_addresses(address)
    with ThreadPoolExecutor(max_workers=SCAN_MAX_WORKERS) as pool:
        listening = [
            ip for ip, opened in zip(candidates, pool.map(lambda ip: _port_open(ip, port), candidates))
            if opened
        ]
        matched = [
            ip for ip, hit in zip(listening, pool.map(
                lambda ip: _matches_host(ip, port, username, hostname, key_filename), listening))
            if hit
        ]
    return matched[0] if matched else None


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=SCAN_PORT_TIMEOUT):
            return True
    except OSError:
        return False


def _matches_host(
    host: str,
    port: int,
    username: str,
    hostname: str,
    key_filename: str | None,
) -> bool:
    try:
        conn = connect_target(host, port, username, None, None,
                              key_filename=key_filename, timeout=SCAN_CONNECT_TIMEOUT)
    except (OSError, paramiko.SSHException, EOFError):
        return False
    try:
        code, out = run_capture(conn.client, SCAN_HOSTNAME_COMMAND, timeout=SCAN_COMMAND_TIMEOUT)
    finally:
        conn.close()
    return code == 0 and out.strip() == hostname


def clear_stale_host_key(host: str, port: int) -> None:
    """Drop saved known_hosts entries so a reinstall does not break connecting."""
    names = (host,) if port == 22 else (f"[{host}]:{port}", host)
    for name in names:
        subprocess.run(["ssh-keygen", "-R", name], capture_output=True, check=False)


def _connect_single(
    host: str,
    port: int,
    username: str,
    password: str | None,
    sock: paramiko.Channel | None = None,
    key_filename: str | None = None,
    timeout: float = CONNECT_TIMEOUT,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=username,
        password=password,
        key_filename=key_filename,
        sock=sock,
        look_for_keys=password is None,
        allow_agent=password is None,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def _exec(client: paramiko.SSHClient, command: str, pty: bool) -> paramiko.Channel:
    chan = client.get_transport().open_session()
    if pty:
        chan.get_pty()
    chan.exec_command(command)
    return chan


def _send_stdin(chan: paramiko.Channel, stdin_text: str) -> None:
    if stdin_text:
        chan.sendall(stdin_text.encode())
        chan.shutdown_write()


def _pending(chan: paramiko.Channel) -> bool:
    return not (
        chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready()
    )


def _drain(chan: paramiko.Channel) -> None:
    while chan.recv_ready():
        sys.stdout.write(chan.recv(RECV_CHUNK).decode(errors="replace"))
        sys.stdout.flush()
    while chan.recv_stderr_ready():
        sys.stdout.write(chan.recv_stderr(RECV_CHUNK).decode(errors="replace"))
        sys.stdout.flush()
