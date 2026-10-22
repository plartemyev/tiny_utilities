"""Provision a fresh VirtualBox VM for archinstaller.

The VM carries the future host's name and is configured for an
unattended, TRIM-aware install: UEFI firmware, one NVMe disk (a fresh VDI
presented as a solid-state drive with discard enabled, so guest TRIM
compacts the image; VirtualBox 7.2.22 rejects the previous virtio-scsi
controller through VBoxManage, and NVMe is in the open-source base package
since 7.2.0), two virtio-net NICs — NAT (NIC1: the internet uplink, with
an SSH port-forward kept as the fallback path) and a host-only adapter
(NIC2: the fast host↔guest path; the SSH transport and the local package
mirror ride it, and a per-MAC DHCP binding pins a deterministic address),
a serial port exposed as a host TCP listener (the blind boot-menu
injection and the console session run through it), an HDA audio device on
the default host audio driver (the guest side pins snd-hda-intel to
position_fix=1, presupposing the device), UTC RTC and the shared
clipboard. USB 3.0 (xHCI) requires the Extension Pack; the graphical flag
selects a desktop-capable video stack (VMSVGA with 256 MB) over the 16 MB
console one.

The split follows measured throughput (iperf2, VBox 7.2.22): every NAT
path tops out in the hundreds of Mbit/s (the userland NAT engine), while
the host-only bridge carries 1–2.5 Gbit/s both ways with the same virtio
NIC. The NAT NIC stays the default route and the only DNS source (the
host-only DHCP server hands out neither), so the roaming guarantees are
unchanged.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from archinstaller import vbox
from archinstaller.i18n import tr
from archinstaller.provision import pick_free_ports

OSTYPE = "ArchLinux_64"
DISK_CONTROLLER = "archinstaller-nvme"
GUEST_ADDRESS = "10.0.2.15"  # NIC1 (NAT) lease, deterministic; the SSH
                             # port-forward fallback pins it
HOSTONLY_IFACE = "vboxnet0"  # NIC2 backend; created when missing
HOSTONLY_GATEWAY = "192.168.56.1"  # the host itself on a fresh vboxnet0
HOSTONLY_NETMASK = "255.255.255.0"
HOSTONLY_STATIC_FIRST = 50   # per-MAC bindings start here ...
HOSTONLY_STATIC_LAST = 99    # ... and stay below the dynamic DHCP pool
HOSTONLY_POOL_LOW = 101
HOSTONLY_POOL_HIGH = 254
GRAPHICAL_VRAM_MB = 256
CONSOLE_VRAM_MB = 16
EXT_PACK_NAME = "Oracle VirtualBox Extension Pack"


@dataclass(frozen=True)
class HostonlyConfig:
    """NIC2 facts the install flow needs after provisioning."""

    iface: str
    gateway: str  # the host itself: the local-mirror address and router
    netmask: str
    guest_ip: str  # the address pinned for this VM's MAC
    mac: str = ""  # NIC2's MAC (the guest profile is keyed by it)

    @property
    def network(self) -> str:
        return str(ipaddress.ip_network(f"{self.gateway}/{self.netmask}",
                                        strict=False))

    @property
    def guest_cidr(self) -> str:
        prefix = ipaddress.ip_network(f"{self.gateway}/{self.netmask}",
                                      strict=False).prefixlen
        return f"{self.guest_ip}/{prefix}"


def provision(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
              iso_path: str, graphical: bool
              ) -> tuple[int, int, HostonlyConfig]:
    """Create, configure and start the VM.

    Returns (serial, ssh-forward) ports and the host-only network handle
    (NIC2: the fast host↔guest path with the VM's pinned address).
    """
    if vbox.vm_exists(name):
        raise vbox.VboxError(
            f"VirtualBox VM {name!r} already exists; pass a different --hostname "
            f"or remove the VM (vboxmanage unregistervm {name!r} --delete)")
    serial_port, ssh_port = pick_free_ports(2)
    extpack = extpack_installed()
    if not extpack:
        print("warning: VirtualBox Extension Pack not found; "
              "USB 3.0 (xHCI) stays off")
    iface, gateway, netmask = ensure_hostonly_network()
    for arguments in plan(name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                          cores=cores, iso_path=iso_path, graphical=graphical,
                          serial_port=serial_port, ssh_port=ssh_port,
                          extpack=extpack, machine_folder=_machine_folder(name),
                          hostonly_iface=iface):
        vbox._run(*arguments)
    mac = machine_mac(name)
    hostonly = HostonlyConfig(
        iface=iface, gateway=gateway, netmask=netmask,
        guest_ip=bind_hostonly_address(iface, gateway, netmask, mac),
        mac=mac)
    print(f"Starting VM {name!r} headless ...")
    vbox.start(name, headless=True)
    return serial_port, ssh_port, hostonly


def plan(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
         iso_path: str, graphical: bool, serial_port: int, ssh_port: int,
         extpack: bool, machine_folder: str,
         hostonly_iface: str = HOSTONLY_IFACE) -> list[tuple[str, ...]]:
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
         "--nic1", "nat", "--nic-type1", "virtio",
         "--cableconnected1", "on",
         "--nat-pf1", f"ssh,tcp,127.0.0.1,{ssh_port},{GUEST_ADDRESS},22",
         "--nic2", "hostonly", "--nic-type2", "virtio",
         "--host-only-adapter2", hostonly_iface, "--cableconnected2", "on",
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
    net = f"HostInterfaceNetworking-{HOSTONLY_IFACE}"
    body = "\n".join(shlex.join(("vboxmanage", *arguments))
                     for arguments in plan(
                         name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                         cores=cores, iso_path=iso_path, graphical=graphical,
                         serial_port=serial_port, ssh_port=ssh_port,
                         extpack=extpack, machine_folder=_machine_folder(name)))
    prereq = "\n".join((
        "# one-time host-side prerequisites (skip the pieces that exist):",
        f"vboxmanage list hostonlyifs  # is {HOSTONLY_IFACE} present?",
        f"# vboxmanage hostonlyif create  # only when {HOSTONLY_IFACE} is missing",
        f"# vboxmanage hostonlyif ipconfig {HOSTONLY_IFACE} --ip {HOSTONLY_GATEWAY}"
        f" --netmask {HOSTONLY_NETMASK}",
        f"# vboxmanage dhcpserver add --network {net} --server-ip"
        f" {HOSTONLY_GATEWAY.rsplit('.', 1)[0]}.100 --netmask {HOSTONLY_NETMASK}"
        f" --lower-ip {HOSTONLY_GATEWAY.rsplit('.', 1)[0]}.{HOSTONLY_POOL_LOW}"
        f" --upper-ip {HOSTONLY_GATEWAY.rsplit('.', 1)[0]}.{HOSTONLY_POOL_HIGH}"
        " --enable",
    ))
    binding = "\n".join((
        "# pin the VM's host-only address (NIC2's MAC exists after createvm):",
        f"vboxmanage showvminfo {name} --machinereadable | grep macaddress2",
        f"vboxmanage dhcpserver modify --network {net} --mac-address <MAC>"
        f" --fixed-address {HOSTONLY_GATEWAY.rsplit('.', 1)[0]}.{HOSTONLY_STATIC_FIRST}",
    ))
    intro = tr(language,
               f"Provision the VirtualBox VM {name!r} (serial line on TCP"
               f" {serial_port}, SSH over the host-only network at the pinned"
               f" address; NAT port-forward 127.0.0.1:{ssh_port} is the"
               " fallback):")
    return (intro + "\n\n" + note + "```bash\n" + prereq + "\n\n" + body
            + "\n\n" + binding + "\n```\n")


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


def ensure_hostonly_network() -> tuple[str, str, str]:
    """The host-only network pieces NIC2 needs; create the missing ones.

    vboxnet0 with a DHCP server is the only host-side prerequisite of the
    host-only path. Creating the interface (or setting its address) shells
    out to the setuid VBoxNetAdpCtl helper, so it normally works without
    root; a failure raises with the manual commands instead.
    """
    listing = vbox._run("list", "hostonlyifs")
    iface, address, netmask = _hostonly_iface(listing, HOSTONLY_IFACE)
    if iface is None:
        print(f"No {HOSTONLY_IFACE} host-only network; creating it ...")
        created = vbox._run("hostonlyif", "create")
        match = re.search(r"Interface '([^']+)' was successfully created", created)
        iface = match.group(1) if match else HOSTONLY_IFACE
        listing = vbox._run("list", "hostonlyifs")
        iface, address, netmask = _hostonly_iface(listing, iface)
        if iface is None:
            raise vbox.VboxError("the created host-only interface is missing "
                                 "from `vboxmanage list hostonlyifs` output")
    if not address:
        vbox._run("hostonlyif", "ipconfig", iface,
                  "--ip", HOSTONLY_GATEWAY, "--netmask", HOSTONLY_NETMASK)
        address, netmask = HOSTONLY_GATEWAY, HOSTONLY_NETMASK
    _ensure_hostonly_dhcp(iface, address, netmask)
    return iface, address, netmask


def _hostonly_iface(listing: str, wanted: str) -> tuple[str | None, str, str]:
    """(name, IPAddress, NetworkMask) of `wanted` in `list hostonlyifs`."""
    for block in listing.split("\n\n"):
        if re.search(rf"^Name:\s*{re.escape(wanted)}\s*$", block, re.MULTILINE):
            address = re.search(r"^IPAddress:\s*(\S*)", block, re.MULTILINE)
            netmask = re.search(r"^NetworkMask:\s*(\S*)", block, re.MULTILINE)
            return (wanted, address.group(1) if address else "",
                    netmask.group(1) if netmask else "")
    return None, "", ""


def _ensure_hostonly_dhcp(iface: str, gateway: str, netmask: str) -> None:
    """A DHCP server on the host-only network; add VBox's default one."""
    network_name = f"HostInterfaceNetworking-{iface}"
    servers = vbox._run("list", "dhcpservers")
    if re.search(rf"^NetworkName:\s*{re.escape(network_name)}\s*$",
                 servers, re.MULTILINE):
        return
    net = ipaddress.ip_network(f"{gateway}/{netmask}", strict=False)
    hosts = list(net.hosts())

    def host_at(offset: int) -> str:
        return str(hosts[min(offset, len(hosts) - 1)])

    vbox._run("dhcpserver", "add", "--network", network_name,
              "--server-ip", host_at(99), "--netmask", netmask,
              "--lower-ip", host_at(HOSTONLY_POOL_LOW - 1),
              "--upper-ip", host_at(HOSTONLY_POOL_HIGH - 1), "--enable")


def machine_mac(name: str) -> str:
    """The host-only NIC's (NIC2) MAC, for the DHCP binding."""
    out = vbox._run("showvminfo", name, "--machinereadable")
    match = re.search(r'^macaddress2="([0-9A-Fa-f]+)"', out, re.MULTILINE)
    if match is None:
        raise vbox.VboxError("cannot read macaddress2 from showvminfo output")
    return match.group(1)


def bind_hostonly_address(iface: str, gateway: str, netmask: str,
                          mac: str) -> str:
    """Pin a deterministic host-only address to the VM's MAC.

    The binding (not a pool lease) keeps the installed system's address
    stable across reboots, so stage two and the user's own SSH calls need
    no rediscovery. Candidates stay below the dynamic pool; addresses that
    answer a ping (other live VMs) are skipped.
    """
    net = ipaddress.ip_network(f"{gateway}/{netmask}", strict=False)
    gateway_ip = ipaddress.IPv4Address(gateway)
    order = ([HOSTONLY_STATIC_FIRST]
             + list(range(HOSTONLY_STATIC_LAST, HOSTONLY_STATIC_FIRST, -1))
             + list(range(2, HOSTONLY_STATIC_FIRST)))
    candidates = [str(net[n]) for n in order
                  if 0 < n < net.num_addresses - 1 and net[n] != gateway_ip]
    chosen = None
    for start in range(0, len(candidates), 20):
        batch = candidates[start:start + 20]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            free = [candidate for candidate, busy in
                    zip(batch, pool.map(_address_in_use, batch)) if not busy]
        if free:
            chosen = free[0]
            break
    if chosen is None:
        raise vbox.VboxError(f"no free static address in {net} for the "
                             "host-only binding")
    vbox._run("dhcpserver", "modify",
              "--network", f"HostInterfaceNetworking-{iface}",
              "--mac-address", mac, "--fixed-address", chosen)
    return chosen


def _address_in_use(address: str) -> bool:
    """One ICMP probe; an answering host-only address is taken."""
    probe = subprocess.run(["ping", "-c", "1", "-W", "1", address],
                           capture_output=True, timeout=5, check=False)
    return probe.returncode == 0


def select_guest_addresses(addresses: list[str],
                           hostonly: HostonlyConfig) -> tuple[str, str]:
    """Validate the dual-NIC leases; return (NAT, host-only) addresses.

    The NAT port-forward fallback pins GUEST_ADDRESS, so a foreign NAT
    lease would leave that path silently dead; the host-only address is
    the SSH target and must sit in the host-only subnet (any address —
    the archiso's DHCP client may miss the per-MAC binding and take a
    pool lease; the installed system lands on the bound one).
    """
    if not any(ip.split("/")[0] == GUEST_ADDRESS for ip in addresses):
        raise vbox.VboxError(
            f"no {GUEST_ADDRESS} among the guest addresses {addresses} — the "
            "NAT port-forward fallback pins it, so SSH would never connect")
    network = ipaddress.ip_network(f"{hostonly.gateway}/{hostonly.netmask}",
                                   strict=False)
    host_ip = next((ip.split("/")[0] for ip in addresses
                    if ipaddress.IPv4Address(ip.split("/")[0]) in network),
                   None)
    if host_ip is None:
        raise vbox.VboxError(
            f"no address in the host-only subnet among {addresses} — the "
            f"DHCP server on {hostonly.iface} did not answer; check "
            "`vboxmanage list dhcpservers`")
    return GUEST_ADDRESS, host_ip


def _machine_folder(name: str) -> str:
    """The VM's folder (createvm made it under the default machines dir)."""
    out = vbox._run("list", "systemproperties")
    match = re.search(r"Default machine folder:\s*(.+)", out)
    if match is None:
        raise vbox.VboxError("cannot read the default machine folder from "
                             "vboxmanage list systemproperties")
    return os.path.join(match.group(1).strip(), name)


def find_booted_target(name: str) -> str | None:
    """The host-only address is pinned; there is nothing to rediscover.

    The NAT port-forward (NIC1) stays as the documented fallback path and
    is probed by the caller before recovery instructions are printed.
    """
    return None
