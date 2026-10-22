import os

from archinstaller import provision_libvirt


def test_cpu_topology_mirrors_host_smt_shape():
    assert provision_libvirt.cpu_topology(4, 2) == (2, 2)
    assert provision_libvirt.cpu_topology(8, 2) == (4, 2)
    assert provision_libvirt.cpu_topology(4, 1) == (4, 1)  # no host SMT
    assert provision_libvirt.cpu_topology(3, 2) == (3, 1)  # uneven split
    assert provision_libvirt.cpu_topology(1, 2) == (1, 1)
    assert provision_libvirt.cpu_topology(4, 4) == (1, 4)


def test_pin_cpuset_takes_the_high_host_cpus():
    assert provision_libvirt.pin_cpuset(4, 8) == "4-7"
    assert provision_libvirt.pin_cpuset(1, 8) == "7"
    assert provision_libvirt.pin_cpuset(8, 8) == "0-7"
    assert provision_libvirt.pin_cpuset(2, 2) == "0-1"


def test_cpus_field_parses_kernel_cpu_lists():
    assert provision_libvirt._cpus_field("0-3\n") == (0, 1, 2, 3)
    assert provision_libvirt._cpus_field("0,4") == (0, 4)
    assert provision_libvirt._cpus_field("2") == (2,)
    assert provision_libvirt._cpus_field("0-1,4,6-7") == (0, 1, 4, 6, 7)


def test_host_cores_groups_smt_siblings_from_sysfs(monkeypatch, tmp_path):
    for cpu, siblings in ((0, "0,2"), (1, "1,3"), (2, "0,2"), (3, "1,3")):
        topo = tmp_path / f"cpu{cpu}" / "topology"
        topo.mkdir(parents=True)
        (topo / "thread_siblings_list").write_text(siblings)
    monkeypatch.setattr(provision_libvirt, "SYS_CPU_BASE", str(tmp_path))
    assert provision_libvirt.host_cores() == [(0, 2), (1, 3)]


def test_host_cores_falls_back_to_single_cpu_cores(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "SYS_CPU_BASE", "/nonexistent/cpu")
    assert provision_libvirt.host_cores() == [(i,) for i in range(os.cpu_count() or 1)]


def test_cpu_pins_preserve_smt_siblings_with_adjacent_numbering():
    cores = [(0, 1), (2, 3), (4, 5), (6, 7)]
    assert provision_libvirt.cpu_pins(4, cores) == [4, 5, 6, 7]
    assert provision_libvirt.emulator_cpus(4, cores) == (2, 3)


def test_cpu_pins_preserve_smt_siblings_with_split_numbering():
    cores = [(0, 4), (1, 5), (2, 6), (3, 7)]
    assert provision_libvirt.cpu_pins(4, cores) == [2, 6, 3, 7]
    assert provision_libvirt.emulator_cpus(4, cores) == (1, 5)


def test_cpu_pins_single_threaded_cores_take_one_sibling_per_core():
    cores = [(0, 1), (2, 3), (4, 5), (6, 7)]
    assert provision_libvirt.cpu_pins(3, cores) == [2, 4, 6]
    assert provision_libvirt.emulator_cpus(3, cores) == (0, 1)


def test_cpu_pins_none_when_the_host_has_too_few_cores():
    assert provision_libvirt.cpu_pins(8, [(0,), (1,)]) is None


def test_emulator_is_unpinned_when_the_guest_takes_every_core():
    cores = [(0, 1), (2, 3)]
    assert provision_libvirt.cpu_pins(4, cores) == [0, 1, 2, 3]
    assert provision_libvirt.emulator_cpus(4, cores) is None


def test_format_cpuset_compresses_consecutive_runs():
    assert provision_libvirt.format_cpuset((2, 3)) == "2-3"
    assert provision_libvirt.format_cpuset((7,)) == "7"
    assert provision_libvirt.format_cpuset((1, 5)) == "1,5"
    assert provision_libvirt.format_cpuset((0, 1, 2, 4, 6, 7)) == "0-2,4,6-7"


def test_domain_xml_matches_the_spec_graphical():
    xml = provision_libvirt.domain_xml(
        "testvm", disk_size_gib=45, ram_gib=4, cores=4, graphical=True,
        serial_port=23950, iso_path="/iso/arch.iso", network=("bridge", "lan0"),
        host_cores=[(0, 1), (2, 3), (4, 5), (6, 7)])
    for expected in (
        "<domain type='kvm'>",
        "<name>testvm</name>",
        "<memory unit='GiB'>4</memory>",
        "<currentMemory unit='GiB'>4</currentMemory>",
        "<vcpu placement='static'>4</vcpu>",
        "<os firmware='efi'>",
        "<type arch='x86_64' machine='q35'>hvm</type>",
        "<boot dev='cdrom'/>",
        "<cpu mode='host-passthrough' migratable='off'><topology sockets='1' cores='2' threads='2'/></cpu>",
        "<vcpupin vcpu='0' cpuset='4'/>",
        "<vcpupin vcpu='1' cpuset='5'/>",
        "<vcpupin vcpu='2' cpuset='6'/>",
        "<vcpupin vcpu='3' cpuset='7'/>",
        "<emulatorpin cpuset='2-3'/>",
        "discard='unmap' detect_zeroes='unmap'",
        "<source volume='testvm.qcow2' pool='default'/>",
        "<target dev='vda' bus='virtio'/>",
        "<source file='/iso/arch.iso'/>",
        "<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>",
        "<channel type='spicevmc'><target type='virtio' name='com.redhat.spice.0'/></channel>",
        "<source bridge='lan0'/>",
        "<model type='virtio'/>",
        "service='23950'",
        "<listen type='none'/>",
        "<gl enable='yes'/>",
        "<acceleration accel3d='yes'/>",
        "<audio id='1' type='spice'/>",
        "<sound model='ich9'>",
        "<audio id='1'/>",
        "<memballoon model='virtio' freePageReporting='on' autodeflate='on'/>",
    ):
        assert expected in xml, expected


def test_domain_xml_console_variant():
    xml = provision_libvirt.domain_xml(
        "testvm", disk_size_gib=45, ram_gib=4, cores=4, graphical=False,
        serial_port=23950, iso_path="/iso/arch.iso",
        network=("network", "default"),
        host_cores=[(0, 1), (2, 3), (4, 5), (6, 7)])
    assert "<listen type='address' address='127.0.0.1'/>" in xml
    assert "<acceleration accel3d='no'/>" in xml
    assert "<gl enable='no'/>" in xml
    assert "<interface type='network'>" in xml
    assert "<source network='default'/>" in xml
    assert "<audio id='1' type='spice'/>" in xml
    assert "<sound model='ich9'>" in xml
    assert "<audio id='1'/>" in xml


def test_domain_xml_falls_back_to_shared_cpuset_on_tiny_hosts():
    xml = provision_libvirt.domain_xml(
        "testvm", disk_size_gib=45, ram_gib=4, cores=4, graphical=False,
        serial_port=23950, iso_path="/iso/arch.iso",
        network=("network", "default"), host_cores=[(0,), (1,)])
    assert "<vcpupin vcpu='0' cpuset='0-1'/>" in xml
    assert "<vcpupin vcpu='3' cpuset='0-1'/>" in xml
    assert "<emulatorpin cpuset='0-1'/>" in xml


def test_select_network_prefers_a_physical_bridge(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "physical_bridge", lambda: "lan0")
    assert provision_libvirt.select_network() == ("bridge", "lan0")


def test_select_network_falls_back_to_lan_routed_then_default(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "physical_bridge", lambda: None)
    monkeypatch.setattr(provision_libvirt, "_net_names",
                        lambda uri: {"lan-routed": "inactive", "default": "active"})
    started = []
    monkeypatch.setattr(provision_libvirt, "_run",
                        lambda uri, *args: started.append(args) or "")
    assert provision_libvirt.select_network() == ("network", "lan-routed")
    assert started == [("net-start", "lan-routed")]


def test_select_network_skips_missing_networks(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "physical_bridge", lambda: None)
    monkeypatch.setattr(provision_libvirt, "_net_names",
                        lambda uri: {"default": "active"})
    assert provision_libvirt.select_network() == ("network", "default")


def test_select_network_fails_without_any_network(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "physical_bridge", lambda: None)
    monkeypatch.setattr(provision_libvirt, "_net_names", lambda uri: {})
    try:
        provision_libvirt.select_network()
    except provision_libvirt.LibvirtError:
        return
    raise AssertionError("expected LibvirtError without a usable network")


def test_strip_cdrom_removes_device_and_boot_entry():
    xml = ("<domain><os firmware='efi'><boot dev='cdrom'/><boot dev='hd'/></os>"
           "<devices>"
           "<disk type='file' device='cdrom'>"
           "<source file='/iso/arch.iso'/><target dev='sda' bus='sata'/>"
           "</disk>"
           "<disk type='volume' device='disk'><target dev='vda'/></disk>"
           "</devices></domain>")
    stripped = provision_libvirt._strip_cdrom(xml)
    assert "cdrom" not in stripped
    assert "<boot dev='hd'/>" in stripped
    assert "<target dev='vda'/>" in stripped


def test_plan_network_probes_without_side_effects(monkeypatch):
    monkeypatch.setattr(provision_libvirt, "physical_bridge", lambda: None)
    monkeypatch.setattr(provision_libvirt, "_net_names",
                        lambda uri: {"lan-routed": "inactive", "default": "active"})
    network, needs_start = provision_libvirt.plan_network()
    assert network == ("network", "lan-routed")
    assert needs_start is True


def test_workbook_section_renders_commands_and_xml():
    section = provision_libvirt.workbook_section(
        "testvm", disk_size_gib=45, ram_gib=4, cores=4, graphical=True,
        iso_path="/iso/arch.iso", serial_port=23950,
        network=("network", "lan-routed"), network_start=True)
    assert "virsh -c qemu:///system net-start lan-routed" in section
    assert "virsh -c qemu:///system vol-create-as default testvm.qcow2 " \
        "45G --format qcow2" in section
    assert "virsh -c qemu:///system define archinstaller-provision-testvm.xml" \
        in section
    assert "virsh -c qemu:///system start testvm" in section
    assert "```xml" in section and "machine='q35'>hvm" in section


def test_find_booted_target_parses_the_lease(monkeypatch):
    def fake_run(uri, *args):
        if args[0] == "dumpxml":
            return "<mac address='52:54:00:68:c0:68'/>"
        if args[0] == "net-list":
            return " Name     State\n---------\n default    active\n"
        if args[0] == "net-dhcp-leases":
            return (" Expiry Time   MAC address   Protocol   IP address\n"
                    " Tue 21 Oct   52:54:00:68:c0:68   ipv4       "
                    "192.168.122.118/24   testvm\n")
        raise AssertionError(args)

    monkeypatch.setattr(provision_libvirt, "_run", fake_run)
    assert provision_libvirt.find_booted_target("testvm") == "192.168.122.118"


def test_find_booted_target_returns_none_without_lease(monkeypatch):
    def fake_run(uri, *args):
        if args[0] == "dumpxml":
            return "<mac address='52:54:00:68:c0:68'/>"
        if args[0] == "net-list":
            return " Name     State\n---------\n default    active\n"
        return "no leases"

    monkeypatch.setattr(provision_libvirt, "_run", fake_run)
    assert provision_libvirt.find_booted_target("testvm") is None
