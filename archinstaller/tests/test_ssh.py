import archinstaller.ssh as ssh
from archinstaller.ssh import subnet_addresses


class _StderrOnlyChan:
    """Channel of a command that failed writing only to stderr (curl)."""

    def __init__(self):
        self._stderr = [b"curl: (7) Failed to connect to server"]
        self.closed = False

    def exec_command(self, command):
        self.command = command

    def exit_status_ready(self):
        return True

    def recv_ready(self):
        return False

    def recv_stderr_ready(self):
        return bool(self._stderr)

    def recv_stderr(self, size):
        return self._stderr.pop(0)

    def recv_exit_status(self):
        return 7

    def close(self):
        self.closed = True


def test_run_capture_drains_stderr_instead_of_spinning_to_timeout(monkeypatch):
    """Regression: _pending() waits for unread stderr, the loop read only
    stdout - any stderr-only command hung until the timeout (hit twice
    with the local-mirror healthz curl before its fallback could fire)."""
    chan = _StderrOnlyChan()
    monkeypatch.setattr(ssh, "PUMP_INTERVAL", 0.001)

    class FakeTransport:
        def open_session(self):
            return chan

    code, out = ssh.run_capture(type("C", (), {"get_transport": lambda self: FakeTransport()})(),
                                "curl -fsS http://10.0.2.2:8282/healthz", timeout=5)
    assert code == 7
    assert "Failed to connect" in out
    assert chan.closed


def test_subnet_addresses_covers_usable_hosts():
    addresses = subnet_addresses("192.168.56.113")
    assert len(addresses) == 254
    assert addresses[0] == "192.168.56.1"
    assert addresses[-1] == "192.168.56.254"
    assert "192.168.56.113" in addresses


def test_subnet_addresses_normalizes_non_network_base():
    addresses = subnet_addresses("10.0.2.77")
    assert addresses[0] == "10.0.2.1"
    assert addresses[-1] == "10.0.2.254"
