from __future__ import annotations

import dataclasses
import sys
import time

import paramiko

CONNECT_TIMEOUT = 30
POLL_SECONDS = 10
PUMP_INTERVAL = 0.1
RECV_CHUNK = 4096


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
    password: str,
    jump: JumpConfig | None = None,
) -> SshConnection:
    sock = None
    jump_client = None
    if jump is not None:
        jump_client = _connect_single(jump.host, jump.port, jump.username, jump.password)
        sock = jump_client.get_transport().open_channel(
            "direct-tcpip", (host, port), (jump.host, jump.port),
        )
    try:
        client = _connect_single(host, port, username, password, sock=sock)
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
    password: str,
    timeout: float,
    jump: JumpConfig | None = None,
) -> bool:
    attempts = max(1, int(timeout // POLL_SECONDS))
    for _ in range(attempts):
        try:
            conn = connect_target(host, port, username, password, jump)
            conn.close()
            return True
        except (OSError, paramiko.SSHException, EOFError):
            time.sleep(POLL_SECONDS)
    return False


def _connect_single(
    host: str,
    port: int,
    username: str,
    password: str,
    sock: paramiko.Channel | None = None,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=username,
        password=password,
        sock=sock,
        look_for_keys=False,
        allow_agent=False,
        timeout=CONNECT_TIMEOUT,
        banner_timeout=CONNECT_TIMEOUT,
        auth_timeout=CONNECT_TIMEOUT,
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
