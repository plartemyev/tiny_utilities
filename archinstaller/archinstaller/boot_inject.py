"""Blind systemd-boot menu injection on a stock Arch ISO.

The ISO's UEFI bootloader (systemd-boot) waits ~15 s at its menu and
opens a cmdline editor on `e`: typed text lands at the end of the entry
buffer, and `Enter` boots the edited entry for this boot only. The menu
lives on the (unattended) VGA console, so the keystrokes are sent blind
by the hypervisor at a fixed delay after VM start; success is verified
by kernel output appearing on the serial line (console.py).

libvirt's `virsh send-key` presses all listed keys down in order and
releases them in reverse, so a modifier capitalises every key pressed
after it in the same call: each shifted key terminates its call.
VirtualBox types whole strings instead (`keyboardputstring`) and needs
raw PS/2 scancodes only for Enter.

The caller owns retries: if the serial line stays silent after the
injection (missed menu window), restart the VM and inject again.
"""
from __future__ import annotations

import subprocess
import time

VIRSH = "virsh"
VBOX_MANAGE = "vboxmanage"
DEFAULT_URI = "qemu:///system"
MENU_DELAY_S = 10.0
EDIT_SETTLE_S = 1.5
TYPE_SETTLE_S = 0.5
SERIAL_CONSOLE_ARGS = " console=ttyS0,115200"
ENTER_SCANCODES = ("1c", "9c")  # PS/2 set 1: Enter make + break


class InjectionError(RuntimeError):
    pass


class Keys:
    """Keystroke sink for one running VM."""

    def type_text(self, text: str) -> None:
        raise NotImplementedError

    def press_enter(self) -> None:
        raise NotImplementedError


class VirshKeys(Keys):
    """Keystrokes via `virsh send-key` (libvirt qemu domains)."""

    def __init__(self, domain: str, uri: str = DEFAULT_URI) -> None:
        self.domain = domain
        self.uri = uri

    def type_text(self, text: str) -> None:
        for call in _key_calls(text):
            _run(VIRSH, "-c", self.uri, "send-key", self.domain, *call)

    def press_enter(self) -> None:
        _run(VIRSH, "-c", self.uri, "send-key", self.domain, "KEY_ENTER")


class VBoxKeys(Keys):
    """Keystrokes via `VBoxManage controlvm keyboardputstring`."""

    def __init__(self, vm: str) -> None:
        self.vm = vm

    def type_text(self, text: str) -> None:
        _run(VBOX_MANAGE, "controlvm", self.vm, "keyboardputstring", text)

    def press_enter(self) -> None:
        _run(VBOX_MANAGE, "controlvm", self.vm,
             "keyboardputscancode", *ENTER_SCANCODES)


def inject(injector: Keys, kernel_args: str = SERIAL_CONSOLE_ARGS,
           menu_delay_s: float = MENU_DELAY_S) -> None:
    """Send the blind menu keystrokes: `e`, the args, `Enter`."""
    time.sleep(menu_delay_s)
    injector.type_text("e")
    time.sleep(EDIT_SETTLE_S)
    injector.type_text(kernel_args)
    time.sleep(TYPE_SETTLE_S)
    injector.press_enter()


# evdev key names; shifted symbols send KEY_LEFTSHIFT first.
_PLAIN = {
    " ": "KEY_SPACE", "-": "KEY_MINUS", "=": "KEY_EQUAL", ",": "KEY_COMMA",
    ".": "KEY_DOT", "/": "KEY_SLASH", ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE", "\\": "KEY_BACKSLASH",
    "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE",
}
_SHIFTED = {
    "!": "KEY_1", "@": "KEY_2", "#": "KEY_3", "$": "KEY_4", "%": "KEY_5",
    "^": "KEY_6", "&": "KEY_7", "*": "KEY_8", "(": "KEY_9", ")": "KEY_0",
    "_": "KEY_MINUS", "+": "KEY_EQUAL", ":": "KEY_SEMICOLON",
    '"': "KEY_APOSTROPHE", "?": "KEY_SLASH", "<": "KEY_COMMA",
    ">": "KEY_DOT", "~": "KEY_GRAVE", "|": "KEY_BACKSLASH",
    "{": "KEY_LEFTBRACE", "}": "KEY_RIGHTBRACE",
}


def _key_calls(text: str) -> list[list[str]]:
    """Group text into send-key calls with one shifted key at most, last.

    A call's keys go down in order and up in reverse, so anything after
    KEY_LEFTSHIFT in the same call would be capitalised: a shifted key
    must end its call (this shape is what was proven live).
    """
    calls: list[list[str]] = []
    batch: list[str] = []
    for char in text:
        if char.isalpha() and char.isascii():
            key, shifted = f"KEY_{char.upper()}", char.isupper()
        elif char.isdigit():
            key, shifted = f"KEY_{char}", False
        elif char in _PLAIN:
            key, shifted = _PLAIN[char], False
        elif char in _SHIFTED:
            key, shifted = _SHIFTED[char], True
        else:
            raise InjectionError(f"cannot type {char!r} via send-key")
        if shifted:
            batch += ["KEY_LEFTSHIFT", key]
            calls.append(batch)
            batch = []
        else:
            batch.append(key)
    if batch:
        calls.append(batch)
    return calls


def _run(*args: str) -> str:
    proc = subprocess.run(list(args), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise InjectionError(f"{' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
