"""Provision a fresh VirtualBox VM for archinstaller.

The VM carries the future host's name and is configured for an
unattended, TRIM-aware install: UEFI firmware, one NVMe disk (a fresh VDI
presented as a solid-state drive with discard enabled, so guest TRIM
compacts the image; VirtualBox 7.2.22 rejects the previous virtio-scsi
controller through VBoxManage, and NVMe is in the open-source base package
since 7.2.0), a virtio-net
NIC on NAT with an SSH
port forward to the host, a serial port exposed as a host TCP listener
(the blind boot-menu injection and the console session run through it),
an HDA audio device on the default host audio driver (the guest side
pins snd-hda-intel to position_fix=1, presupposing the device), UTC RTC
and the shared clipboard. USB 3.0 (xHCI) requires the Extension Pack;
the graphical flag selects a desktop-capable video stack (VMSVGA with
256 MB) over the 16 MB console one.
"""
from __future__ import annotations

import os
import re
import shlex

from archinstaller import vbox
from archinstaller.i18n import tr
from archinstaller.provision import pick_free_ports

OSTYPE = "ArchLinux_64"
DISK_CONTROLLER = "archinstaller-nvme"
GUEST_ADDRESS = "10.0.2.15"  # first lease of the per-VM NAT engine, deterministic
GRAPHICAL_VRAM_MB = 256
CONSOLE_VRAM_MB = 16
EXT_PACK_NAME = "Oracle VirtualBox Extension Pack"


def provision(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
              iso_path: str, graphical: bool) -> tuple[int, int]:
    """Create, configure and start the VM; return (serial, ssh-forward) ports."""
    if vbox.vm_exists(name):
        raise vbox.VboxError(
            f"VirtualBox VM {name!r} already exists; pass a different --hostname "
            f"or remove the VM (vboxmanage unregistervm {name!r} --delete)")
    serial_port, ssh_port = pick_free_ports(2)
    extpack = extpack_installed()
    if not extpack:
        print("warning: VirtualBox Extension Pack not found; "
              "USB 3.0 (xHCI) stays off")
    for arguments in plan(name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                          cores=cores, iso_path=iso_path, graphical=graphical,
                          serial_port=serial_port, ssh_port=ssh_port,
                          extpack=extpack, machine_folder=_machine_folder(name)):
        vbox._run(*arguments)
    print(f"Starting VM {name!r} headless ...")
    vbox.start(name, headless=True)
    return serial_port, ssh_port


def plan(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
         iso_path: str, graphical: bool, serial_port: int, ssh_port: int,
         extpack: bool, machine_folder: str) -> list[tuple[str, ...]]:
    """The exact VBoxManage calls provision() executes, in order.

    Workbook rendering (workbook_section) shares this list, so a workbook
    always matches what the tool would run.
    """
    commands = [
        ("createvm", "--name", name, "--ostype", OSTYPE, "--register"),
        ("modifyvm", name,
         "--firmware", "efi",
         "--cpus", str(cores), "--memory", str(ram_gib * 1024),
         "--vram", str(GRAPHICAL_VRAM_MB if graphical else CONSOLE_VRAM_MB),
         "--graphicscontroller", "vmsvga",
         "--rtc-use-utc", "on",
         "--pae", "on", "--hwvirtex", "on", "--nested-paging", "on",
         "--nictype1", "virtio", "--nic1", "nat", "--cableconnected1", "on",
         "--nat-pf1", f"ssh,tcp,127.0.0.1,{ssh_port},{GUEST_ADDRESS},22",
         "--uart1", "0x3F8", "4", "--uart-type1", "16550A",
         "--uart-mode1", "tcpserver", str(serial_port),
         "--clipboard-mode", "bidirectional",
         "--audio-driver", "default",
         "--audio-controller", "hda",
         "--audio-out", "on", "--audio-in", "on"),
    ]
    if extpack:
        commands.append(("modifyvm", name, "--usb-xhci", "on"))
    vdi = os.path.join(machine_folder, f"{name}.vdi")
    commands += [
        ("createmedium", "disk", "--filename", vdi,
         "--size", str(disk_size_gib * 1024), "--variant", "standard"),
        ("storagectl", name, "--name", DISK_CONTROLLER,
         "--add", "pcie", "--controller", "NVMe", "--hostiocache", "on"),
        ("storageattach", name, "--storagectl", DISK_CONTROLLER,
         "--port", "0", "--device", "0", "--type", "hdd",
         "--medium", vdi, "--nonrotational", "on", "--discard", "on"),
        ("storagectl", name, "--name", "IDE", "--add", "ide"),
        ("storageattach", name, "--storagectl", "IDE", "--port", "1",
         "--device", "0", "--type", "dvddrive", "--medium", iso_path),
        ("modifyvm", name, "--boot1", "dvd", "--boot2", "disk",
         "--boot3", "floppy"),
    ]
    return commands


def workbook_section(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
                     iso_path: str, graphical: bool, serial_port: int,
                     ssh_port: int, language: str = "en") -> str:
    """Render plan() as copy-paste shell lines for the workbook."""
    extpack = extpack_installed()
    note = ""
    if not extpack:
        note = tr(language,
                  "> The VirtualBox Extension Pack is not installed on this host;"
                  " USB 3.0 (xHCI) is not enabled. After installing it, run"
                  f" `vboxmanage modifyvm {name} --usb-xhci on` (VM powered off).\n\n")
    body = "\n".join(shlex.join(("vboxmanage", *arguments))
                     for arguments in plan(
                         name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                         cores=cores, iso_path=iso_path, graphical=graphical,
                         serial_port=serial_port, ssh_port=ssh_port,
                         extpack=extpack, machine_folder=_machine_folder(name)))
    intro = tr(language,
               f"Provision the VirtualBox VM {name!r} (serial line on TCP"
               f" {serial_port}, SSH port forward 127.0.0.1:{ssh_port}):")
    return (intro + "\n\n" + note + "```bash\n" + body + "\n```\n")


def restart(name: str) -> None:
    vbox.poweroff(name)
    vbox.start(name, headless=True)


def finalize(name: str) -> None:
    """Host-side post-install reboot: power off, eject the ISO, boot the disk.

    Guest-written EFI boot entries do not survive a guest-initiated
    reboot (NVRAM flushes on power-off only), but a host-side poweroff
    flushes them — after ejecting the DVD and preferring the disk, the
    installed GRUB boots directly.
    """
    vbox.poweroff(name)
    vbox._run("storageattach", name, "--storagectl", "IDE", "--port", "1",
              "--device", "0", "--type", "dvddrive", "--medium", "emptydrive")
    vbox._run("modifyvm", name, "--boot1", "disk", "--boot2", "dvd",
              "--boot3", "floppy")
    vbox.start(name, headless=True)


def extpack_installed() -> bool:
    return EXT_PACK_NAME in vbox._run("list", "extpacks")


def ensure_nat_address(guest_ip: str) -> None:
    """Abort early when the guest did not get the pinned NAT address.

    The SSH port-forward rule targets GUEST_ADDRESS explicitly; a guest
    at any other address (a changed VirtualBox NAT default?) would leave
    the forward silently dead and the SSH connect timing out much later.
    """
    if guest_ip.split("/")[0] != GUEST_ADDRESS:
        raise vbox.VboxError(
            f"guest reports {guest_ip}, expected {GUEST_ADDRESS}/24 — the NAT "
            "port-forward pins the latter, so SSH would never connect")


def _machine_folder(name: str) -> str:
    """The VM's folder (createvm made it under the default machines dir)."""
    out = vbox._run("list", "systemproperties")
    match = re.search(r"Default machine folder:\s*(.+)", out)
    if match is None:
        raise vbox.VboxError("cannot read the default machine folder from "
                             "vboxmanage list systemproperties")
    return os.path.join(match.group(1).strip(), name)


def find_booted_target(name: str) -> str | None:
    """The NAT port forward is fixed; there is nothing to rediscover."""
    return None
