"""Provision a fresh libvirt VM (qemu:///system) for archinstaller.

The domain XML matches the agreed spec: q35 chipset with UEFI firmware,
CPU topology mirroring the host SMT shape (vCPUs split into cores x
threads and pinned to the high host CPU numbers, emulator included),
the full memory allocation from the start (the virtio balloon with
freePageReporting and autodeflate hands unused pages back), a qcow2
volume on virtio with discard/detect-zeroes unmap, a virtio NIC on the
first usable network — physical bridge, then the lan-routed network,
then default NAT — spice per the graphical flag, and a TCP serial port
for the blind boot-menu injection and the console session.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

from archinstaller.provision import pick_free_ports

DEFAULT_URI = "qemu:///system"
VIRSH = "virsh"
PREFERRED_NETWORKS = ("lan-routed", "default")
VOLUME_POOL = "default"
SHUTDOWN_POLL_TRIES = 30
SHUTDOWN_POLL_S = 2.0


class LibvirtError(RuntimeError):
    pass


def provision(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
              iso_path: str, graphical: bool,
              uri: str = DEFAULT_URI) -> tuple[int, int]:
    """Create, define and start the VM; return (serial port, 22).

    The VM is reached from the host at its DHCP address directly (NAT
    and routed networks) or via the bridge, so no port forward exists.
    """
    if _domain_exists(name, uri):
        raise LibvirtError(
            f"libvirt domain {name!r} already exists; pass a different --hostname "
            f"or remove it (virsh undefine {name!r} --nvram)")
    volume = f"{name}.qcow2"
    if _volume_exists(volume, uri):
        raise LibvirtError(f"volume {volume!r} already exists in the "
                           f"{VOLUME_POOL!r} pool")
    serial_port = pick_free_ports(1)[0]
    network = select_network(uri)
    xml = domain_xml(name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                     cores=cores, graphical=graphical, serial_port=serial_port,
                     iso_path=iso_path, network=network,
                     host_tpc=host_threads_per_core(),
                     host_cpus=os.cpu_count() or 1)
    _run(uri, "vol-create-as", VOLUME_POOL, volume,
         f"{disk_size_gib}G", "--format", "qcow2")
    _define(uri, xml, f"archinstaller-provision-{name}.xml")
    print(f"libvirt network: {network[0]} {network[1]}; starting VM ...")
    _run(uri, "start", name)
    return serial_port, 22


def restart(name: str, uri: str = DEFAULT_URI) -> None:
    _stop(name, uri)
    _run(uri, "start", name)


def finalize(name: str, uri: str = DEFAULT_URI) -> None:
    """Host-side post-install reboot: stop, detach the ISO, boot the disk.

    pflash NVRAM survives destroy/start, so the guest-written GRUB entry
    boots directly; the cdrom device and its boot entry are removed from
    the persistent XML first.
    """
    _stop(name, uri)
    xml = _strip_cdrom(_run(uri, "dumpxml", name))
    _define(uri, xml)
    _run(uri, "start", name)


def find_booted_target(name: str, uri: str = DEFAULT_URI) -> str | None:
    """The domain's DHCP lease address, or None (stage-two fallback)."""
    xml = _run(uri, "dumpxml", name)
    mac = re.search(r"<mac address='([^']+)'", xml)
    if mac is None:
        return None
    for network, state in _net_names(uri).items():
        if state != "active":
            continue
        for line in _run(uri, "net-dhcp-leases", network).splitlines():
            if mac.group(1) in line:
                found = _ipv4_in(line)
                if found:
                    return found
    return None


def select_network(uri: str = DEFAULT_URI) -> tuple[str, str]:
    """(kind, name) of the first usable network: bridge, lan-routed, NAT."""
    network, needs_start = plan_network(uri)
    if needs_start:
        _run(uri, "net-start", network[1])
    return network


def plan_network(uri: str = DEFAULT_URI) -> tuple[tuple[str, str], bool]:
    """((kind, name), needs_start), probed without side effects.

    Workbook rendering uses the flag to render a net-start command instead
    of starting the network at render time.
    """
    bridge = physical_bridge()
    if bridge is not None:
        return ("bridge", bridge), False
    networks = _net_names(uri)
    for candidate in PREFERRED_NETWORKS:
        state = networks.get(candidate)
        if state is None:
            continue
        return ("network", candidate), state != "active"
    raise LibvirtError(
        "no usable libvirt network: no bridge with a physical NIC, and none "
        f"of {', '.join(PREFERRED_NETWORKS)} is defined")


def physical_bridge() -> str | None:
    """First host bridge with at least one non-virtual enslaved interface."""
    for name in sorted(os.listdir("/sys/class/net")):
        brif_dir = f"/sys/class/net/{name}/brif"
        if name.startswith("virbr") or not os.path.isdir(brif_dir):
            continue
        for port in sorted(os.listdir(brif_dir)):
            if not re.match(r"^(veth|vnet|tap|macvtap|macvlan)", port):
                return name
    return None


def cpu_topology(cores: int, host_threads_per_core: int) -> tuple[int, int]:
    """(cores, threads) presenting `cores` vCPUs in the host's SMT shape.

    E.g. 4 requested vCPUs on a 2-threads-per-core host become 2 cores x
    2 threads; requests that do not divide evenly stay single-threaded.
    """
    if cores <= 1 or host_threads_per_core <= 1:
        return cores, 1
    threads = min(host_threads_per_core, cores)
    if cores % threads:
        return cores, 1
    return cores // threads, threads


def pin_cpuset(vcpus: int, host_cpus: int) -> str:
    """cpuset of the last host CPUs, keeping the low ones for host IRQs."""
    start = max(0, host_cpus - vcpus)
    if start == host_cpus - 1:
        return str(start)
    return f"{start}-{host_cpus - 1}"


def host_threads_per_core() -> int:
    proc = subprocess.run(["lscpu"], capture_output=True, text=True, check=False)
    match = re.search(r"Thread\(s\) per core:\s+(\d+)", proc.stdout)
    return int(match.group(1)) if match else 1


def domain_xml(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
               graphical: bool, serial_port: int, iso_path: str,
               network: tuple[str, str], host_tpc: int, host_cpus: int) -> str:
    core_count, thread_count = cpu_topology(cores, host_tpc)
    lines = [
        "<domain type='kvm'>",
        f"  <name>{name}</name>",
        f"  <memory unit='GiB'>{ram_gib}</memory>",
        f"  <currentMemory unit='GiB'>{ram_gib}</currentMemory>",
        f"  <vcpu placement='static'>{cores}</vcpu>",
        *_cputune(cores, host_cpus),
        "  <os firmware='efi'>",
        "    <type arch='x86_64' machine='q35'>hvm</type>",
        "    <boot dev='cdrom'/>",
        "    <boot dev='hd'/>",
        "  </os>",
        "  <features><acpi/><apic/></features>",
        ("  <cpu mode='host-passthrough'>"
         f"<topology sockets='1' cores='{core_count}' "
         f"threads='{thread_count}'/></cpu>"),
        "  <clock offset='utc'/>",
        "  <on_poweroff>destroy</on_poweroff>",
        "  <on_reboot>restart</on_reboot>",
        "  <on_crash>destroy</on_crash>",
        "  <devices>",
        "    <emulator>/usr/bin/qemu-system-x86_64</emulator>",
        "    <disk type='volume' device='disk'>",
        ("      <driver name='qemu' type='qcow2' discard='unmap' "
         "detect_zeroes='unmap'/>"),
        f"      <source volume='{name}.qcow2' pool='{VOLUME_POOL}'/>",
        "      <target dev='vda' bus='virtio'/>",
        "    </disk>",
        "    <disk type='file' device='cdrom'>",
        "      <driver name='qemu' type='raw'/>",
        f"      <source file='{iso_path}'/>",
        "      <target dev='sda' bus='sata'/>",
        "      <readonly/>",
        "    </disk>",
        ("    <channel type='unix'><target type='virtio' "
         "name='org.qemu.guest_agent.0'/></channel>"),
        *_interface(network),
        "    <serial type='tcp'>",
        "      <source mode='bind' host='127.0.0.1' "
        f"service='{serial_port}'/>",
        "      <target port='0'/>",
        "    </serial>",
        "    <console type='tcp'>",
        "      <source mode='bind' host='127.0.0.1' "
        f"service='{serial_port}'/>",
        "      <target type='serial' port='0'/>",
        "    </console>",
        "    <input type='tablet' bus='usb'/>",
        *_graphics(graphical),
        "    <memballoon model='virtio' freePageReporting='on' "
        "autodeflate='on'/>",
        "  </devices>",
        "</domain>",
        "",
    ]
    return "\n".join(lines)


def workbook_section(name: str, *, disk_size_gib: int, ram_gib: int, cores: int,
                     graphical: bool, iso_path: str, serial_port: int,
                     network: tuple[str, str], network_start: bool,
                     uri: str = DEFAULT_URI) -> str:
    """Render the provisioning commands and the domain XML for the workbook.

    The XML comes from the same domain_xml() provision() uses, so the
    workbook always matches what the tool would define.
    """
    lines = []
    if network_start:
        lines.append(f"virsh -c {uri} net-start {network[1]}")
    lines += [
        (f"virsh -c {uri} vol-create-as {VOLUME_POOL} {name}.qcow2 "
         f"{disk_size_gib}G --format qcow2"),
        f"virsh -c {uri} define archinstaller-provision-{name}.xml",
        f"virsh -c {uri} start {name}",
    ]
    xml = domain_xml(name, disk_size_gib=disk_size_gib, ram_gib=ram_gib,
                     cores=cores, graphical=graphical, serial_port=serial_port,
                     iso_path=iso_path, network=network,
                     host_tpc=host_threads_per_core(),
                     host_cpus=os.cpu_count() or 1)
    return (f"Provision the libvirt domain {name!r} on {uri} (network:"
            f" {network[0]} {network[1]}, serial line on TCP {serial_port}):\n\n"
            "```bash\n" + "\n".join(lines) + "\n```\n\n"
            + f"Save the domain XML as `archinstaller-provision-{name}.xml`:\n\n"
            + "```xml\n" + xml + "```\n")


def _stop(name: str, uri: str) -> None:
    """Clean ACPI shutdown with a hard destroy fallback (like vbox.poweroff)."""
    try:
        _run(uri, "shutdown", name)
    except LibvirtError:
        pass
    for _ in range(SHUTDOWN_POLL_TRIES):
        if _domain_state(name, uri) == "shut off":
            return
        time.sleep(SHUTDOWN_POLL_S)
    _run(uri, "destroy", name)


def _domain_state(name: str, uri: str) -> str:
    return _run(uri, "domstate", name).strip()


def _domain_exists(name: str, uri: str) -> bool:
    proc = subprocess.run([VIRSH, "-c", uri, "dominfo", name],
                          capture_output=True, text=True, check=False)
    return proc.returncode == 0


def _volume_exists(volume: str, uri: str) -> bool:
    proc = subprocess.run(
        [VIRSH, "-c", uri, "vol-info", "--pool", VOLUME_POOL, volume],
        capture_output=True, text=True, check=False)
    return proc.returncode == 0


def _net_names(uri: str) -> dict[str, str]:
    """Network name → state ('active'/'inactive') from net-list --all."""
    networks: dict[str, str] = {}
    for line in _run(uri, "net-list", "--all").splitlines():
        columns = line.split()
        if len(columns) >= 2 and columns[1] in ("active", "inactive"):
            networks[columns[0]] = columns[1]
    return networks


def _cputune(vcpus: int, host_cpus: int) -> list[str]:
    cpuset = pin_cpuset(vcpus, host_cpus)
    return ["  <cputune>",
            *(f"    <vcpupin vcpu='{vcpu}' cpuset='{cpuset}'/>"
              for vcpu in range(vcpus)),
            f"    <emulatorpin cpuset='{cpuset}'/>",
            "  </cputune>"]


def _interface(network: tuple[str, str]) -> list[str]:
    kind, name = network
    source = (f"<source bridge='{name}'/>" if kind == "bridge"
              else f"<source network='{name}'/>")
    return ["    <interface type='bridge'>" if kind == "bridge"
            else "    <interface type='network'>",
            f"      {source}",
            "      <model type='virtio'/>",
            "    </interface>"]


def _graphics(graphical: bool) -> list[str]:
    accel = "yes" if graphical else "no"
    listen = ("<listen type='none'/>" if graphical else
              "<listen type='address' address='127.0.0.1'/>")
    return ["    <graphics type='spice'>",
            f"      {listen}",
            "      <image compression='off'/>",
            f"      <gl enable='{accel}'/>",
            "    </graphics>",
            "    <video>",
            "      <model type='virtio' heads='1' primary='yes' "
            "device='virtio-vga'>",
            f"        <acceleration accel3d='{accel}'/>",
            "      </model>",
            ("      <address type='pci' domain='0x0000' bus='0x00' "
             "slot='0x01' function='0x0'/>"),
            "    </video>"]


def _strip_cdrom(xml: str) -> str:
    xml = re.sub(r"\s*<boot dev='cdrom'/>", "", xml)
    return re.sub(r"\s*<disk type='file' device='cdrom'>.*?</disk>", "", xml,
                  flags=re.DOTALL)


def _ipv4_in(line: str) -> str | None:
    for column in line.split():
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+(/\d+)?", column):
            return column.split("/")[0]
    return None


def _define(uri: str, xml: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    try:
        _run(uri, "define", path)
    finally:
        os.unlink(path)


def _run(uri: str, *args: str) -> str:
    proc = subprocess.run([VIRSH, "-c", uri, *args],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise LibvirtError(f"virsh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout
