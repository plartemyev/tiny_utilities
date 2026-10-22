from pathlib import Path

import subprocess

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
    monkeypatch.setattr(vbox, "_run", lambda *args: 'VMState="poweroff"\n')
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
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": "poweroff"})
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands == []


def test_poweroff_skips_when_frontend_crashed_to_aborted(monkeypatch):
    # a VirtualBoxVM GUI crash leaves VMState="aborted": the VM is not
    # running, so the ACPI dance and the hard stop would only error out
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": "aborted"})
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands == []


def test_poweroff_survives_the_vm_exiting_before_the_hard_stop(monkeypatch):
    # the VM can enter its own shutdown (or exit) between the state checks
    # and the hard stop; controlvm then errors with "not currently running"
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 2) + ["poweroff"] * 5)

    def fake_run(*args):
        commands.append(args)
        if args == ("controlvm", "vm", "poweroff"):
            raise vbox.VboxError("vboxmanage controlvm vm poweroff failed: "
                                 "VBoxManage: error: Machine 'vm' is not "
                                 "currently running.")

    states_iter = states
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states_iter)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", fake_run)
    vbox.poweroff("vm")  # must not raise
    assert commands == [
        ("controlvm", "vm", "acpipowerbutton"),
        ("controlvm", "vm", "poweroff"),
    ]


def test_poweroff_falls_back_to_hard_stop(monkeypatch):
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 2) + ["poweroff"] * 10)
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands == [
        ("controlvm", "vm", "acpipowerbutton"),
        ("controlvm", "vm", "poweroff"),
    ]


def test_poweroff_escalates_to_emergency_stop_when_the_hard_stop_wont_land(monkeypatch):
    # hit 2026-10-22: the hard stop failed transiently mid-teardown while the
    # archiso live guest was still finishing its own ~90s ACPI shutdown; the
    # old code then only waited passively and crashed before the goal state.
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 2
                                 + vbox.HARD_STOP_POLL_TRIES + 1) + ["aborted"])
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", lambda *args: commands.append(args))
    vbox.poweroff("vm")
    assert commands == [
        ("controlvm", "vm", "acpipowerbutton"),
        ("controlvm", "vm", "poweroff"),
        ("startvm", "vm", "--type", "emergencystop"),
    ]


def test_poweroff_emergency_stop_skipped_when_the_vm_goes_off_first(monkeypatch):
    # the VM powers off (here: frontend died to "aborted") while the ladder
    # is between its stages; the escalation must then do nothing at all
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 2
                                 + vbox.HARD_STOP_POLL_TRIES) + ["aborted"] * 5)

    def fake_run(*args):
        commands.append(args)
        if args == ("controlvm", "vm", "poweroff"):
            raise vbox.VboxError("vboxmanage controlvm vm poweroff failed: "
                                 "VBoxManage: error: Machine 'vm' is not "
                                 "currently running.")

    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", fake_run)
    vbox.poweroff("vm")
    assert commands == [
        ("controlvm", "vm", "acpipowerbutton"),
        ("controlvm", "vm", "poweroff"),
    ]


def test_poweroff_tolerates_the_emergency_stop_losing_the_race(monkeypatch):
    # the VM exits in the instant between the off-check and the emergency
    # stop; VBoxManage refuses with "not locked by a session" - that is the
    # goal state already reached, not a failure
    states = iter(["running"] * (vbox.VMSTATE_POLL_TRIES + 2
                                 + vbox.HARD_STOP_POLL_TRIES + 1) + ["poweroff"] * 5)

    def fake_run(*args):
        commands.append(args)
        if args == ("startvm", "vm", "--type", "emergencystop"):
            raise vbox.VboxError("vboxmanage startvm vm --type emergencystop "
                                 "failed: VBoxManage: error: The machine 'vm' "
                                 "is not locked by a session")

    monkeypatch.setattr(vbox, "vm_info", lambda vm: {"VMState": next(states)})
    monkeypatch.setattr(vbox.time, "sleep", lambda seconds: None)
    commands = []
    monkeypatch.setattr(vbox, "_run", fake_run)
    vbox.poweroff("vm")  # must not raise
    assert commands[-1] == ("startvm", "vm", "--type", "emergencystop")


def test_run_times_out_and_raises_vbox_error(monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="vboxmanage", timeout=60)

    monkeypatch.setattr(vbox.subprocess, "run", hang)
    try:
        vbox._run("showvminfo", "vm", "--machinereadable")
    except vbox.VboxError as exc:
        assert "timed out" in str(exc)
        return
    raise AssertionError("expected VboxError on a hung VBoxManage call")


def test_enable_discard_reattaches_hdd_attachments_only(monkeypatch):
    monkeypatch.setattr(vbox, "vm_info", lambda vm: {
        "name": "testvm",
        "VMState": "poweroff",
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
