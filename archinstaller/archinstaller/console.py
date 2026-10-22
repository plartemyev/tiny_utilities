"""Serial console session with an Arch ISO live environment.

Provisioned VMs have no human at the (VGA) console, so the live ISO is
driven through its serial port: the stock ISO's bootloader menu gets
console=ttyS0 injected at boot (boot_inject), after which the kernel's
systemd-getty-generator spawns a login prompt on the serial line. The
session logs in as root (passwordless on the ISO), sets the root
password for the SSH transport and reports the guest's DHCP address —
replacing both video-console keystroke automation and target-IP
scanning.

On the host side the serial endpoint is a plain byte stream: a TCP
listener for both VirtualBox (--uart-mode1 tcpserver) and libvirt
(<serial type='tcp'>).
"""
from __future__ import annotations

import re
import shlex
import socket
import time

ANSI_RE = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")
LOGIN_PROMPT = rb"login:"
LOGIN_OR_SHELL = rb"login:|archiso[^#]*#"
SHELL_PROMPT = rb"archiso[^#]*#"
BEGIN_MARKER = b"AIBEGIN"
END_MARKER = b"AIEND"
# Quoted split: the command ECHO must never contain the literal marker,
# or read_until matches the echo and the real marker line leaks into the
# next block's buffer (observed live: every second block then failed).
BEGIN_COMMAND = 'echo AI"BEGIN"'
END_COMMAND = 'echo AI"END"'
CONNECT_TRIES = 30
CONNECT_DELAY_S = 1.0
BOOT_TIMEOUT_S = 420.0
LOGIN_TIMEOUT_S = 60.0
IP_POLL_TRIES = 15
IP_POLL_DELAY_S = 2.0
COMMAND_TIMEOUT_S = 120.0
SETTLE_S = 0.5


class SerialError(RuntimeError):
    pass


class SerialTimeout(SerialError):
    pass


class SerialConsole:
    """One serial connection: byte I/O plus a full transcript."""

    def __init__(self, host: str | None = None, port: int | None = None,
                 unix_path: str | None = None) -> None:
        if unix_path is not None:
            self.address: str | tuple[str, int] = unix_path
        elif host is not None and port is not None:
            self.address = (host, port)
        else:
            raise SerialError("serial endpoint: pass host+port or unix_path")
        self.sock: socket.socket | None = None
        self.transcript = bytearray()

    def connect(self) -> None:
        """Connect, retrying while the hypervisor creates the listener."""
        last: OSError | None = None
        for _ in range(CONNECT_TRIES):
            try:
                self.sock = self._open()
                return
            except OSError as exc:
                last = exc
                time.sleep(CONNECT_DELAY_S)
        raise SerialError(f"cannot connect to serial {self.address!r}: {last}")

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def send(self, text: str) -> None:
        if self.sock is None:
            raise SerialError("serial is not connected")
        self.sock.sendall(text.encode())

    def read_until(self, pattern: bytes, timeout_s: float,
                   ping: bytes = b"", ping_interval: float = 0.0) -> bytes:
        """Receive until `pattern` matches; return the whole buffer.

        `ping` is sent every `ping_interval` seconds while waiting — a
        newline re-displays an agetty prompt that was printed before the
        connection existed.
        """
        if self.sock is None:
            raise SerialError("serial is not connected")
        compiled = re.compile(pattern)
        end = time.monotonic() + timeout_s
        last_ping = time.monotonic()
        buf = bytearray()
        self.sock.settimeout(1.0)
        while time.monotonic() < end:
            if ping and ping_interval and time.monotonic() - last_ping >= ping_interval:
                self.sock.sendall(ping)
                last_ping = time.monotonic()
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise SerialError("serial closed unexpectedly")
            buf += chunk
            self.transcript += chunk
            if compiled.search(bytes(buf)):
                return bytes(buf)
        raise SerialTimeout(
            f"timeout ({timeout_s}s) waiting for {compiled.pattern!r} on serial")

    def _open(self) -> socket.socket:
        if isinstance(self.address, str):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.address)
            return sock
        return socket.create_connection(self.address, timeout=3.0)


def strip_ansi(data: bytes) -> bytes:
    """Drop ANSI/VT escapes; the ISO console colorizes tool output."""
    return ANSI_RE.sub(b"", data)


def login_root(console: SerialConsole, timeout_s: float = BOOT_TIMEOUT_S) -> None:
    """Wait for the live ISO's serial login prompt and log in as root.

    Resumes cleanly when the console already sits at a root shell (a
    previous session): whichever marker matches last decides.
    """
    state = console.read_until(LOGIN_OR_SHELL, timeout_s,
                               ping=b"\n", ping_interval=15.0)
    if LOGIN_PROMPT in strip_ansi(state)[-40:]:
        time.sleep(SETTLE_S)
        console.send("root\n")
        console.read_until(SHELL_PROMPT, LOGIN_TIMEOUT_S)


def run_marked(console: SerialConsole, commands: list[str],
               timeout_s: float = COMMAND_TIMEOUT_S) -> bytes:
    """Run commands between echo markers; return the in-between output.

    Echoed input, prompts and progress noise stay outside the markers.
    """
    script = "\n".join([BEGIN_COMMAND, *commands, END_COMMAND])
    time.sleep(SETTLE_S)
    console.send(script + "\n")
    raw = console.read_until(END_MARKER, timeout_s)
    _head, sep, section = raw.partition(BEGIN_MARKER)
    if not sep:
        raise SerialError("begin marker not found in serial output")
    return section


def set_live_password(console: SerialConsole, password: str,
                      timeout_s: float = COMMAND_TIMEOUT_S) -> None:
    """Set the live environment's root password for the SSH transport."""
    section = run_marked(console, [f"passwd -s <<< {shlex.quote(password)}",
                                   "echo PASSWD_RC=$?"], timeout_s)
    match = re.search(rb"PASSWD_RC=(\d+)", strip_ansi(section))
    if match is None or match.group(1) != b"0":
        raise SerialError(f"passwd failed over serial (rc: {match and match.group(1)})")


def await_guest_ip(console: SerialConsole) -> str:
    """Poll the guest's global IPv4 until DHCP lands (bounded).

    DHCP races the serial login, and a dead link (e.g. an unbridged tap)
    never answers at all — hence a fixed poll budget instead of one shot.
    """
    for _ in range(IP_POLL_TRIES):
        section = run_marked(console,
                             ["ip -4 -o addr show scope global | grep inet"],
                             COMMAND_TIMEOUT_S)
        addresses = parse_ips(section)
        if addresses:
            return addresses[0]
        time.sleep(IP_POLL_DELAY_S)
    raise SerialTimeout(
        f"no global IPv4 on the guest after {IP_POLL_TRIES} serial polls")


def parse_ips(section: bytes) -> list[str]:
    """Addresses from `ip -4 -o addr show scope global` output."""
    found = re.findall(rb"inet (\d+(?:\.\d+){3})/\d+", strip_ansi(section))
    return [ip.decode() for ip in found]
