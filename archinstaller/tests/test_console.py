import shlex

from archinstaller import console
from archinstaller.console import (
    SerialConsole,
    SerialError,
    SerialTimeout,
    parse_ips,
    strip_ansi,
)


class FakeSerial:
    """Duck-typed SerialConsole with scripted read_until replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def send(self, text):
        self.sent.append(text)

    def read_until(self, pattern, timeout_s, ping=b"", ping_interval=0.0):
        if not self.replies:
            raise SerialTimeout(f"no scripted reply for {pattern!r}")
        return self.replies.pop(0)


def test_strip_ansi_keeps_plain_output():
    raw = b"2: enp0s3    inet \x1b[1;35m10.0.2.15\x1b[0m/24 metric 100"
    assert strip_ansi(raw) == b"2: enp0s3    inet 10.0.2.15/24 metric 100"


def test_parse_ips_reads_colorized_addr_output():
    raw = (b"AIBEGIN\n2: enp0s3    inet \x1b[1;35m10.0.2.15\x1b[0m/24 "
           b"brd \x1b[1;35m10.0.2.255 \x1b[0mscope global dynamic enp0s3\\\n"
           b"AIEND")
    assert parse_ips(raw) == ["10.0.2.15"]


def test_login_root_logs_in_on_fresh_boot():
    fake = FakeSerial([
        b"Probing EDD...\r\narchiso login: ",
        b"root@archiso ~ # \x1b[K",
    ])
    console.login_root(fake, timeout_s=10.0)
    assert fake.sent == ["root\n"]


def test_login_root_skips_login_at_existing_shell():
    fake = FakeSerial([b"root@archiso ~ # "])
    console.login_root(fake, timeout_s=10.0)
    assert fake.sent == []


def test_run_marked_returns_section_between_markers():
    fake = FakeSerial([
        b"root@archiso ~ # echo AI\"BEGIN\"\r\nAIBEGIN\r\nhello world\r\nAIEND\r\n",
    ])
    section = console.run_marked(fake, ["echo hello world"], timeout_s=10.0)
    assert b"hello world" in section
    assert fake.sent[0].startswith(console.BEGIN_COMMAND + "\n")
    assert fake.sent[0].endswith(console.END_COMMAND + "\n")


def test_run_marked_script_hides_markers_from_the_echo():
    # The typed lines must not contain the literal markers: the tty echoes
    # them, and an echoed marker would satisfy read_until before the real
    # output line, poisoning the next block (observed live).
    fake = FakeSerial([b"AIBEGIN\nAIEND"])
    console.run_marked(fake, ["true"], timeout_s=10.0)
    assert console.BEGIN_MARKER not in fake.sent[0].encode()
    assert console.END_MARKER not in fake.sent[0].encode()


def test_run_marked_requires_begin_marker():
    fake = FakeSerial([b"AIEND\r\n"])
    try:
        console.run_marked(fake, ["true"], timeout_s=10.0)
    except SerialError:
        return
    raise AssertionError("expected SerialError without the begin marker")


def test_set_live_password_sends_command_and_checks_rc():
    fake = FakeSerial([b"AIBEGIN\nPASSWD_RC=0\nAIEND"])
    console.set_live_password(fake, "local0instaLl", timeout_s=10.0)
    # shlex.quote leaves a plain alphanumeric password unquoted
    assert "passwd -s <<< local0instaLl" in fake.sent[0]
    assert "echo PASSWD_RC=$?" in fake.sent[0]


def test_set_live_password_quotes_hostile_password():
    fake = FakeSerial([b"AIBEGIN\nPASSWD_RC=0\nAIEND"])
    password = "it's a'trick"
    console.set_live_password(fake, password, timeout_s=10.0)
    assert f"passwd -s <<< {shlex.quote(password)}" in fake.sent[0]


def test_set_live_password_fails_on_nonzero_rc():
    fake = FakeSerial([b"AIBEGIN\nPASSWD_RC=1\nAIEND"])
    try:
        console.set_live_password(fake, "pw", timeout_s=10.0)
    except SerialError:
        return
    raise AssertionError("expected SerialError on rc=1")


def test_await_guest_addresses_polls_until_dhcp_lands(monkeypatch):
    fake = FakeSerial([
        b"AIBEGIN\nAIEND",  # DHCP not there yet
        b"AIBEGIN\n2: enp1s0    inet 192.168.122.188/24 scope global\nAIEND",
    ])
    sleeps = []
    monkeypatch.setattr(console.time, "sleep", lambda seconds: sleeps.append(seconds))
    ips = console.await_guest_addresses(fake)
    assert ips == ["192.168.122.188"]
    assert len(fake.sent) == 2
    # run_marked's settle sleeps are in there too; exactly one is a poll delay
    assert sleeps.count(console.IP_POLL_DELAY_S) == 1


def test_await_guest_addresses_returns_every_dual_nic_lease(monkeypatch):
    fake = FakeSerial([
        b"AIBEGIN\nAIEND",  # DHCP not there yet
        b"AIBEGIN\n2: enp0s3    inet 10.0.2.15/24 scope global\n"
        b"    3: enp0s8    inet 192.168.56.50/24 scope global\nAIEND",
    ])
    monkeypatch.setattr(console.time, "sleep", lambda seconds: None)
    assert console.await_guest_addresses(fake) == ["10.0.2.15", "192.168.56.50"]


def test_await_guest_addresses_gives_up_after_bounded_polls(monkeypatch):
    fake = FakeSerial([b"AIBEGIN\nAIEND"] * (console.IP_POLL_TRIES + 5))
    monkeypatch.setattr(console.time, "sleep", lambda seconds: None)
    try:
        console.await_guest_addresses(fake)
    except SerialTimeout:
        assert len(fake.sent) == console.IP_POLL_TRIES
        return
    raise AssertionError("expected SerialTimeout without a guest address")


def test_console_requires_an_endpoint():
    try:
        SerialConsole()
    except SerialError:
        return
    raise AssertionError("expected SerialError without host/port or unix_path")


def test_connect_retries_while_listener_comes_up(monkeypatch):
    attempts = []

    def flaky(address, timeout):
        attempts.append(address)
        if len(attempts) < 3:
            raise OSError("connection refused")
        return "fake-socket"

    monkeypatch.setattr(console.socket, "create_connection", flaky)
    monkeypatch.setattr(console.time, "sleep", lambda seconds: None)
    sock = SerialConsole(host="127.0.0.1", port=23951)
    sock.connect()
    assert sock.sock == "fake-socket"
    assert attempts == [("127.0.0.1", 23951)] * 3


def test_connect_gives_up_after_bounded_tries(monkeypatch):
    def refuse(address, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(console.socket, "create_connection", refuse)
    monkeypatch.setattr(console.time, "sleep", lambda seconds: None)
    sock = SerialConsole(host="127.0.0.1", port=23951)
    try:
        sock.connect()
    except SerialError:
        return
    raise AssertionError("expected SerialError after the retry budget")
