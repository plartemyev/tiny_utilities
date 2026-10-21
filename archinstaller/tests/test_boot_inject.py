from archinstaller import boot_inject
from archinstaller.boot_inject import (
    InjectionError,
    SERIAL_CONSOLE_ARGS,
    VBoxKeys,
    VirshKeys,
    _key_calls,
    inject,
)


class RecordingKeys(boot_inject.Keys):
    def __init__(self):
        self.typed = []
        self.ents = 0

    def type_text(self, text):
        self.typed.append(text)

    def press_enter(self):
        self.ents += 1


def test_serial_console_args_are_the_proven_ones():
    assert SERIAL_CONSOLE_ARGS == " console=ttyS0,115200"


def test_key_calls_keeps_plain_run_in_one_call():
    assert _key_calls(" console=") == [[
        "KEY_SPACE", "KEY_C", "KEY_O", "KEY_N", "KEY_S", "KEY_O", "KEY_L",
        "KEY_E", "KEY_EQUAL",
    ]]


def test_key_calls_ends_call_on_shifted_key():
    # t t y S(shifted) 0 , 1 1 5 2 0 0 — the digits must NOT share the
    # call with KEY_LEFTSHIFT (they would be capitalised).
    assert _key_calls("ttyS0,115200") == [
        ["KEY_T", "KEY_T", "KEY_Y", "KEY_LEFTSHIFT", "KEY_S"],
        ["KEY_0", "KEY_COMMA", "KEY_1", "KEY_1", "KEY_5", "KEY_2",
         "KEY_0", "KEY_0"],
    ]


def test_key_calls_shifted_symbols():
    assert _key_calls("a:b_c") == [
        ["KEY_A", "KEY_LEFTSHIFT", "KEY_SEMICOLON"],
        ["KEY_B", "KEY_LEFTSHIFT", "KEY_MINUS"],
        ["KEY_C"],
    ]


def test_key_calls_rejects_unsupported_characters():
    try:
        _key_calls("console=ä")
    except InjectionError:
        return
    raise AssertionError("expected InjectionError for a non-typable character")


def test_virsh_keys_send_one_call_per_group(monkeypatch):
    commands = []
    monkeypatch.setattr(boot_inject, "_run",
                        lambda *args: commands.append(args) or "")
    VirshKeys("testvm").type_text("ttyS0")
    assert commands == [
        ("virsh", "-c", "qemu:///system", "send-key", "testvm",
         "KEY_T", "KEY_T", "KEY_Y", "KEY_LEFTSHIFT", "KEY_S"),
        ("virsh", "-c", "qemu:///system", "send-key", "testvm", "KEY_0"),
    ]


def test_virsh_keys_press_enter(monkeypatch):
    commands = []
    monkeypatch.setattr(boot_inject, "_run",
                        lambda *args: commands.append(args) or "")
    VirshKeys("testvm", uri="qemu:///session").press_enter()
    assert commands == [(
        "virsh", "-c", "qemu:///session", "send-key", "testvm", "KEY_ENTER",
    )]


def test_vbox_keys_types_string_and_enter_scancodes(monkeypatch):
    commands = []
    monkeypatch.setattr(boot_inject, "_run",
                        lambda *args: commands.append(args) or "")
    keys = VBoxKeys("testvm")
    keys.type_text(SERIAL_CONSOLE_ARGS)
    keys.press_enter()
    assert commands == [
        ("vboxmanage", "controlvm", "testvm",
         "keyboardputstring", " console=ttyS0,115200"),
        ("vboxmanage", "controlvm", "testvm",
         "keyboardputscancode", "1c", "9c"),
    ]


def test_inject_sequence_edit_args_enter(monkeypatch):
    sleeps = []
    monkeypatch.setattr(boot_inject.time, "sleep",
                        lambda seconds: sleeps.append(seconds))
    keys = RecordingKeys()
    inject(keys, menu_delay_s=9.0)
    assert keys.typed == ["e", SERIAL_CONSOLE_ARGS]
    assert keys.ents == 1
    assert sleeps == [9.0, boot_inject.EDIT_SETTLE_S, boot_inject.TYPE_SETTLE_S]
