from pathlib import Path

from archinstaller import vbox


def test_vm_info_parses_quoted_keys_and_values(monkeypatch):
    output = ('name="testvm"\n'
              'VMState="running"\n'
              '"IDE-0-0"="/home/user/Downloads/archlinux-x86_64.iso"\n')
    monkeypatch.setattr(vbox, "_run", lambda *args: output)
    info = vbox.vm_info("vm")
    assert info["name"] == "testvm"
    assert info["VMState"] == "running"
    assert info["IDE-0-0"] == "/home/user/Downloads/archlinux-x86_64.iso"


def test_vm_exists(monkeypatch):
    monkeypatch.setattr(vbox, "_run", lambda *args: 'VMState="poweroffed"\n')
    assert vbox.vm_exists("vm") is True

    def fail(*args):
        raise vbox.VboxError("no such VM")

    monkeypatch.setattr(vbox, "_run", fail)
    assert vbox.vm_exists("vm") is False


def test_reset_nvram_backs_up_store(tmp_path: Path, monkeypatch):
    nvram = tmp_path / "vm.nvram"
    nvram.write_bytes(b"NVRAM")
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"NvramFile": str(nvram)})
    backup = vbox.reset_nvram("vm")
    assert backup == str(nvram) + ".bak"
    assert not nvram.exists()
    assert Path(backup).read_bytes() == b"NVRAM"


def test_reset_nvram_requires_nvram_file(monkeypatch):
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {})
    try:
        vbox.reset_nvram("vm")
    except vbox.VboxError:
        return
    raise AssertionError("expected VboxError")


def test_poweroff_skips_when_already_off(monkeypatch):
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": "poweroffed"})
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands == []


def test_poweroff_falls_back_to_hard_stop(monkeypatch):
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 10) + ["poweroffed"])
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands[0] == ("controlvm", "vm", "acpipowerbutton")
    assert commands[1] == ("controlvm", "vm", "poweroff")
