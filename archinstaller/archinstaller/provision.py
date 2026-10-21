"""Shared VM provisioning: free-port picking and the serial boot loop.

Both provisioners expose a VM whose serial port is a host-side TCP
listener; the unattended path injects console=ttyS0 into the stock
ISO's bootloader menu (boot_inject) and then drives the live
environment over that line (console). The menu window is finite, so a
missed injection is detected via serial silence and retried after a VM
restart.
"""
from __future__ import annotations

import socket

from archinstaller import boot_inject, console

# Unprivileged, rarely-assigned range, not associated with popular
# programs; the actual ports are probed for bindability at provision time.
PORT_RANGE_START = 23950
PORT_RANGE_END = 24000
BOOT_ATTEMPTS = 3
MENU_DELAYS_S = (10.0, 14.0, 7.0)
# Boot to serial login takes ~1 min under KVM; the budget also bounds the
# silent wait when the injection missed the menu window (stock boot stays
# mute on serial forever).
BOOT_TIMEOUT_S = 240.0


class ProvisionError(RuntimeError):
    pass


def pick_free_ports(count: int, host: str = "127.0.0.1") -> list[int]:
    """The first `count` bindable ports in the provision range."""
    ports: list[int] = []
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if len(ports) == count:
            break
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        ports.append(port)
    if len(ports) < count:
        raise ProvisionError(
            f"no {count} free ports in {host}:{PORT_RANGE_START}-{PORT_RANGE_END}")
    return ports


def boot_with_serial(restart, keys: boot_inject.Keys, serial_port: int,
                     password: str) -> str:
    """Boot the VM into a serial-driven live ISO; return the guest's IP.

    Injects console=ttyS0 at the bootloader menu, logs in as root, sets
    the live root password (the SSH transport uses it right after) and
    waits for the guest's DHCP address. A restart between attempts
    re-enters the menu window with a different delay.
    """
    for attempt in range(BOOT_ATTEMPTS):
        if attempt:
            print(f"boot attempt {attempt + 1}/{BOOT_ATTEMPTS}: "
                  "restarting the VM and re-injecting ...")
            restart()
        session = console.SerialConsole(host="127.0.0.1", port=serial_port)
        try:
            boot_inject.inject(keys, menu_delay_s=MENU_DELAYS_S[attempt])
            session.connect()
            console.login_root(session, timeout_s=BOOT_TIMEOUT_S)
            console.set_live_password(session, password)
            return console.await_guest_ip(session)
        except console.SerialError as exc:
            tail = bytes(session.transcript[-200:])
            print(f"boot attempt {attempt + 1}/{BOOT_ATTEMPTS} failed: {exc}"
                  + (f"; serial tail: {tail!r}" if tail else ""))
        finally:
            session.close()
    raise ProvisionError(
        f"the VM never reached a serial-driven live ISO in {BOOT_ATTEMPTS} attempts")
