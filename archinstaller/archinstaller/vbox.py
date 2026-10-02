"""Host-side VirtualBox assist for deterministic post-install reboot.

Guest-written EFI boot entries do not survive a guest-initiated reboot
(the NVRAM store is flushed on power-off only), so the reboot after the
install is done from the host: clean power-off, NVRAM store backed up so
the firmware starts with fresh defaults, boot order changed to try the
disk before the DVD, and the VM started again. The installed system then
boots via the signature-less \\EFI\\BOOT\\BOOTX64.EFI fallback on its ESP.
"""
from __future__ import annotations

import os
import subprocess
import time

VBOX_MANAGE = "vboxmanage"
VMSTATE_POLL_SECONDS = 2
VMSTATE_POLL_TRIES = 30  # 30 * 2s per wait phase


class VboxError(RuntimeError):
    pass


def vm_exists(vm: str) -> bool:
    try:
        vm_info(vm)
    except VboxError:
        return False
    return True


def vm_info(vm: str) -> dict[str, str]:
    """Key/value pairs of the VM's --machinereadable info."""
    out = _run("showvminfo", vm, "--machinereadable")
    info: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            info[key.strip('"')] = value.strip('"')
    return info


def poweroff(vm: str) -> None:
    """Cleanly power the VM off; falls back to a hard stop on timeout."""
    if vm_info(vm).get("VMState") == "poweroffed":
        return
    _run("controlvm", vm, "acpipowerbutton")
    try:
        _wait_powered_off(vm)
    except VboxError:
        _run("controlvm", vm, "poweroff")
        _wait_powered_off(vm)


def reset_nvram(vm: str) -> str:
    """Back up the NVRAM store so the next boot gets fresh firmware defaults.

    Only guest-written firmware entries are lost; VirtualBox regenerates
    the store. Returns the backup path.
    """
    nvram = vm_info(vm).get("NvramFile")
    if not nvram:
        raise VboxError(f"VM {vm!r} reports no NVRAM file (not EFI?)")
    backup = nvram + ".bak"
    os.replace(nvram, backup)
    return backup


def order_disk_before_dvd(vm: str) -> None:
    """Put the disk in front of the DVD for the fresh default boot order."""
    _run("modifyvm", vm, "--boot2", "disk", "--boot3", "dvd")


def start(vm: str) -> None:
    _run("startvm", vm)


def _wait_powered_off(vm: str) -> None:
    for _ in range(VMSTATE_POLL_TRIES):
        if vm_info(vm).get("VMState") == "poweroffed":
            return
        time.sleep(VMSTATE_POLL_SECONDS)
    raise VboxError(f"VM {vm!r} did not power off in time")


def _run(*args: str) -> str:
    proc = subprocess.run([VBOX_MANAGE, *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise VboxError(f"vboxmanage {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
