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


def test_enable_discard_reattaches_hdd_attachments_only(monkeypatch):
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {
        "name": "testvm",
        "VMState": "poweroffed",
        "storagecontrollername0": "IDE",
        "storagecontrollername1": "SATA",
        "IDE-1-0": "/tmp/archlinux-x86_64.iso",
        "IDE-1-0-UUID": "e6fe8b2a-0000-4000-8000-000000000001",
        "SATA-0-0": "/home/u/VirtualBox VMs/testvm/disk.vdi",
    })
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args) or "")
    changed = vbox.enable_discard("testvm")
    assert changed == ["SATA-0-0"]
    assert commands == [(
        "storageattach", "testvm", "--storagectl", "SATA", "--port", "0",
        "--device", "0", "--type", "hdd", "--medium",
        "/home/u/VirtualBox VMs/testvm/disk.vdi",
        "--discard", "on", "--nonrotational", "on",
    )]


def test_enable_discard_raises_without_hdd_attachment(monkeypatch):
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {
        "storagecontrollername0": "IDE",
        "IDE-1-0": "/tmp/archlinux-x86_64.iso",
    })
    try:
        vbox.enable_discard("vm")
    except vbox.VboxError:
        return
    raise AssertionError("expected VboxError without a hard-disk attachment")
