from archinstaller import provision
from archinstaller import provision_vbox
from archinstaller.vbox import VboxError


def test_provision_commands_build_the_full_vm(monkeypatch):
    monkeypatch.setattr(provision_vbox.vbox, "vm_exists", lambda name: False)
    monkeypatch.setattr(provision_vbox, "extpack_installed", lambda: True)
    monkeypatch.setattr(provision_vbox, "pick_free_ports",
                        lambda count: [23950, 23951])
    def fake_run(*args):
        if args[:2] == ("list", "systemproperties"):
            return "Default machine folder: /home/u/VirtualBox VMs\n"
        commands.append(args)
        return ""

    monkeypatch.setattr(provision_vbox.vbox, "_run", fake_run)
    started = []
    monkeypatch.setattr(provision_vbox.vbox, "start",
                        lambda vm, headless=False: started.append((vm, headless)))
    commands = []
    serial, ssh = provision_vbox.provision(
        "testvm", disk_size_gib=45, ram_gib=4, cores=2,
        iso_path="/iso/arch.iso", graphical=True)
    assert (serial, ssh) == (23950, 23951)
    assert started == [("testvm", True)]
    assert ("createvm", "--name", "testvm", "--ostype",
            provision_vbox.OSTYPE, "--register") in commands
    modify = " ".join(a for args in commands if args[0] == "modifyvm" for a in args)
    for flag in ("--firmware efi", "--vram 256", "--graphicscontroller vmsvga",
                 "--rtc-use-utc on", "--pae on", "--hwvirtex on",
                 "--nested-paging on", "--nictype1 virtio --nic1 nat",
                 "--nat-pf1 ssh,tcp,127.0.0.1,23951,10.0.2.15,22",
                 "--uart1 0x3F8 4 --uart-type1 16550A",
                 "--uart-mode1 tcpserver 23950",
                 "--clipboard-mode bidirectional", "--usb-xhci on",
                 "--audio-driver default --audio-controller hda --audio-out on --audio-in on",
                 "--boot1 dvd --boot2 disk"):
        assert flag in modify, flag
    flat = [" ".join(args) for args in commands]
    assert any("--add pcie --controller NVMe --hostiocache on" in line
               for line in flat)
    assert any("createmedium disk --filename" in line and "--size 46080" in line
               for line in flat)
    attach = [line for line in flat if "storageattach" in line]
    assert any("--type hdd" in line and "--nonrotational on --discard on" in line
               for line in attach)
    assert any("--type dvddrive" in line and "--medium /iso/arch.iso" in line
               for line in attach)


def test_provision_without_extpack_skips_usb(monkeypatch, capsys):
    monkeypatch.setattr(provision_vbox.vbox, "vm_exists", lambda name: False)
    monkeypatch.setattr(provision_vbox, "extpack_installed", lambda: False)
    monkeypatch.setattr(provision_vbox, "pick_free_ports",
                        lambda count: [23950, 23951])
    def fake_run(*args):
        if args[:2] == ("list", "systemproperties"):
            return "Default machine folder: /home/u/VirtualBox VMs\n"
        commands.append(args)
        return ""

    monkeypatch.setattr(provision_vbox.vbox, "_run", fake_run)
    monkeypatch.setattr(provision_vbox.vbox, "start", lambda vm, headless=False: None)
    commands = []
    provision_vbox.provision("testvm", disk_size_gib=45, ram_gib=4, cores=2,
                             iso_path="/iso/arch.iso", graphical=False)
    modify = " ".join(a for args in commands if args[0] == "modifyvm" for a in args)
    assert "--usb-xhci" not in modify
    assert "--vram 16" in modify
    assert "--audio-driver default --audio-controller hda --audio-out on --audio-in on" in modify
    assert "Extension Pack not found" in capsys.readouterr().out


def test_provision_refuses_an_existing_vm_name(monkeypatch):
    monkeypatch.setattr(provision_vbox.vbox, "vm_exists", lambda name: True)
    try:
        provision_vbox.provision("testvm", disk_size_gib=45, ram_gib=4, cores=2,
                                 iso_path="/iso/arch.iso", graphical=False)
    except VboxError:
        return
    raise AssertionError("expected VboxError for an existing VM name")


def test_finalize_stops_ejects_and_boots_disk(monkeypatch):
    commands = []
    monkeypatch.setattr(provision_vbox.vbox, "poweroff",
                        lambda vm: commands.append(("poweroff", vm)))
    monkeypatch.setattr(provision_vbox.vbox, "_run",
                        lambda *args: commands.append(args) or "")
    started = []
    monkeypatch.setattr(provision_vbox.vbox, "start",
                        lambda vm, headless=False: started.append(headless))
    provision_vbox.finalize("testvm")
    assert commands[0] == ("poweroff", "testvm")
    assert ("storageattach", "testvm", "--storagectl", "IDE", "--port", "1",
            "--device", "0", "--type", "dvddrive", "--medium",
            "emptydrive") in commands
    assert ("modifyvm", "testvm", "--boot1", "disk", "--boot2", "dvd",
            "--boot3", "floppy") in commands
    assert started == [True]


def test_plan_matches_provision_and_gates_usb(monkeypatch):
    plan = provision_vbox.plan(
        "testvm", disk_size_gib=45, ram_gib=4, cores=2, iso_path="/iso/a.iso",
        graphical=True, serial_port=23950, ssh_port=23951, extpack=True,
        machine_folder="/machines/testvm")
    assert plan[0] == ("createvm", "--name", "testvm", "--ostype",
                       provision_vbox.OSTYPE, "--register")
    flat = [" ".join(args) for args in plan]
    assert any("--usb-xhci on" in line for line in flat)
    assert any("createmedium disk --filename /machines/testvm/testvm.vdi"
               in line for line in flat)
    assert any("--nonrotational on --discard on" in line for line in flat)
    plan_nousb = provision_vbox.plan(
        "testvm", disk_size_gib=45, ram_gib=4, cores=2, iso_path="/iso/a.iso",
        graphical=False, serial_port=23950, ssh_port=23951, extpack=False,
        machine_folder="/machines/testvm")
    assert not any("--usb-xhci" in " ".join(args) for args in plan_nousb)


def test_workbook_section_renders_shell_lines(monkeypatch):
    monkeypatch.setattr(provision_vbox, "extpack_installed", lambda: False)
    monkeypatch.setattr(provision_vbox, "_machine_folder",
                        lambda name: "/machines/testvm")
    section = provision_vbox.workbook_section(
        "testvm", disk_size_gib=45, ram_gib=4, cores=2, iso_path="/iso/a.iso",
        graphical=False, serial_port=23950, ssh_port=23951)
    assert "vboxmanage createvm --name testvm --ostype ArchLinux_64 --register" \
        in section
    assert "vboxmanage storageattach testvm --storagectl archinstaller-nvme" \
        in section
    assert "--nonrotational on --discard on" in section
    assert "Extension Pack is not installed" in section
    assert "modifyvm testvm --usb-xhci on" in section  # the manual add-on note


def test_extpack_detection(monkeypatch):
    with_pack = "Pack no. 1:   Oracle VirtualBox Extension Pack\nVersion: 7.2.22\n"
    without_pack = "Extension Packs: 1\nPack no. 0:   VNC\nVersion: 7.2.22\n"
    monkeypatch.setattr(provision_vbox.vbox, "_run",
                        lambda *args: with_pack)
    assert provision_vbox.extpack_installed() is True
    monkeypatch.setattr(provision_vbox.vbox, "_run",
                        lambda *args: without_pack)
    assert provision_vbox.extpack_installed() is False


def test_ensure_nat_address_accepts_the_pinned_lease():
    provision_vbox.ensure_nat_address("10.0.2.15/24")  # no exception


def test_ensure_nat_address_rejects_a_foreign_address():
    try:
        provision_vbox.ensure_nat_address("10.0.2.16/24")
    except VboxError:
        return
    raise AssertionError("expected VboxError for an unpinned guest address")
