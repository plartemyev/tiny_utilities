"""The ru catalog must cover every prose string the renderers produce.

tr() fails visible (returns its input unchanged), so asserting
tr("ru", s) != s over every title/rationale the step model emits — and
over the provision/workbook chrome prose — keeps a rendered ru workbook
free of English leaks. Adding a string without a translation fails here,
not in front of a reader.
"""
import pytest

from archinstaller import i18n
from archinstaller import provision
from archinstaller import provision_libvirt
from archinstaller import provision_vbox
from archinstaller.steps import InstallConfig, install_steps, post_boot_steps

KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
       " nameless@example")


def make_cfg(**overrides):
    defaults = {
        "disk": "/dev/vda",
        "hostname": "arch-host-2026-10-22",
        "locale": "en_US.UTF-8",
        "swap_size": "16G",
        "username": "nameless",
        "root_password": "{{ROOT_PASSWORD}}",
        "user_password": "{{USER_PASSWORD}}",
        "public_key": KEY,
        "graphical": False,
        "virt": "none",
        "discard": False,
        "timezone": "Asia/Bangkok",
        "opencode": False,
        "opencode_password": None,
    }
    defaults.update(overrides)
    return InstallConfig(**defaults)


def all_step_prose() -> list[str]:
    configs = [
        make_cfg(),
        make_cfg(virt="oracle", discard=True),
        make_cfg(virt="kvm", graphical=True, devel=True,
                 local_mirror="http://192.168.1.10:8282",
                 opencode=True, opencode_password="{{OPENCODE_PASSWORD}}"),
        make_cfg(virt="qemu", graphical=True),
        make_cfg(virt="vmware", graphical=True),
        make_cfg(virt="microsoft"),
    ]
    strings: list[str] = []
    for cfg in configs:
        steps = install_steps(cfg) + post_boot_steps(
            cfg.username, cfg.hostname, cfg.timezone,
            cfg.opencode, cfg.opencode_password)
        for step in steps:
            if step.title:
                strings.append(step.title)
            if step.rationale:
                strings.append(step.rationale)
    return strings


def test_ru_covers_every_step_title_and_rationale():
    missing = sorted(text for text in all_step_prose()
                     if i18n.tr("ru", text) == text)
    assert missing == []


def test_unknown_language_and_strings_pass_through():
    assert i18n.tr("en", "anything at all") == "anything at all"
    assert i18n.tr("de", "Installing GRUB bootloader") == "Installing GRUB bootloader"


def test_interpolated_titles_translate_with_values():
    assert i18n.tr("ru", "Partitioning /dev/vda (1G ESP + rest for root)") == (
        "Разметка диска /dev/vda (раздел ESP на 1 ГиБ, остальное — под корень)")
    assert i18n.tr("ru", "Setting hostname 'arch-host-x' and locale 'en_US.UTF-8'") == (
        "Задание имени узла 'arch-host-x' и локали 'en_US.UTF-8'")
    assert i18n.tr("ru", "Setting the timezone to Asia/Bangkok") == (
        "Установка часового пояса Asia/Bangkok")
    assert i18n.tr("ru", "Creating user 'nameless'") == (
        "Создание пользователя 'nameless'")
    assert i18n.tr("ru", "Opening port 49374 in firewalld") == (
        "Открытие порта 49374 в firewalld")
    assert i18n.tr("ru", "Generating an SSH keypair for nameless") == (
        "Генерация пары ключей SSH для nameless")


def test_workbook_chrome_patterns():
    assert i18n.tr("ru", "# archinstaller workbook — arch-host-2026-10-22") == (
        "# Руководство archinstaller — arch-host-2026-10-22")
    facts = i18n.tr("ru", "Rendered 2026-10-22 with: disk=/dev/vda, virt=none.")
    assert facts.startswith("Отображено 2026-10-22.")
    assert "disk=/dev/vda, virt=none" in facts
    caution = i18n.tr(
        "ru",
        "> **Caution — live credentials.** This workbook embeds real passwords"
        " (root, user, opencode). Treat the file as a secret: it was written"
        " with mode 0600 — do not commit, share or paste it. Rotate the"
        " passwords once convenient after use.")
    assert "(root, user, opencode)" in caution
    note = i18n.tr(
        "ru",
        "> After the install finishes, reboot, then log in over SSH as `nameless`"
        " (public-key only). Root-level commands below are prefixed with `sudo`"
        " (passwordless for `nameless`).")
    assert "`nameless`" in note


def test_provision_prose_patterns():
    vbox_intro = i18n.tr(
        "ru", "Provision the VirtualBox VM 'h1' (serial line on TCP 23950,"
              " SSH over the host-only network at the pinned address; NAT"
              " port-forward 127.0.0.1:23951 is the fallback):")
    assert "Создание ВМ VirtualBox 'h1'" in vbox_intro
    assert "TCP 23950" in vbox_intro and "127.0.0.1:23951" in vbox_intro
    assert "резервный путь" in vbox_intro
    libvirt_intro = i18n.tr(
        "ru", "Provision the libvirt domain 'h1' on qemu:///system (network:"
              " default active, serial line on TCP 23950):")
    assert "Создание libvirt-домена 'h1'" in libvirt_intro
    assert "qemu:///system" in libvirt_intro
    saved = i18n.tr("ru", "Save the domain XML as `archinstaller-provision-h1.xml`:")
    assert "archinstaller-provision-h1.xml" in saved
    boot = i18n.tr(
        "ru", "The live ISO then answers SSH at 127.0.0.1:23951 (the NAT port"
              " forward; the guest itself is 10.0.2.15). The sections below run"
              " inside that live environment — over the serial line or in the"
              " VM window's console, whichever you prefer.")
    assert boot.startswith("После этого live-ISO отвечает по SSH на"
                           " 127.0.0.1:23951")


def test_en_is_byte_identical_in_provision_workbook_sections(monkeypatch):
    monkeypatch.setattr(provision_vbox, "extpack_installed", lambda: True)
    monkeypatch.setattr(provision_vbox, "_machine_folder", lambda name: f"/vm/{name}")
    monkeypatch.setattr(provision_libvirt, "host_cores",
                        lambda: [(0, 1), (2, 3)])
    en = provision_vbox.workbook_section(
        "h1", disk_size_gib=45, ram_gib=4, cores=4, iso_path="/tmp/arch.iso",
        graphical=False, serial_port=23950, ssh_port=23951)
    assert provision_vbox.workbook_section(
        "h1", disk_size_gib=45, ram_gib=4, cores=4, iso_path="/tmp/arch.iso",
        graphical=False, serial_port=23950, ssh_port=23951,
        language="en") == en
    boot = provision.workbook_boot_section(23950, "127.0.0.1:23951", "pw")
    assert provision.workbook_boot_section(23950, "127.0.0.1:23951", "pw",
                                           language="en") == boot


def test_ru_renders_provision_workbook_sections_without_english_prose(monkeypatch):
    monkeypatch.setattr(provision_vbox, "extpack_installed", lambda: False)
    monkeypatch.setattr(provision_vbox, "_machine_folder", lambda name: f"/vm/{name}")
    monkeypatch.setattr(provision_libvirt, "host_cores",
                        lambda: [(0, 1), (2, 3)])
    vbox_md = provision_vbox.workbook_section(
        "h1", disk_size_gib=45, ram_gib=4, cores=4, iso_path="/tmp/arch.iso",
        graphical=False, serial_port=23950, ssh_port=23951, language="ru")
    assert "Создание ВМ VirtualBox 'h1'" in vbox_md
    assert "Extension Pack для VirtualBox не установлен" in vbox_md
    assert "Provision the VirtualBox VM" not in vbox_md
    # the commands themselves stay executable English
    assert "vboxmanage createvm" in vbox_md
    assert "--usb-xhci on" in vbox_md

    libvirt_md = provision_libvirt.workbook_section(
        "h1", disk_size_gib=45, ram_gib=4, cores=4, graphical=False,
        iso_path="/tmp/arch.iso", serial_port=23950,
        network=("default", "active"), network_start=True, language="ru")
    assert "Создание libvirt-домена 'h1'" in libvirt_md
    assert "Сохраните XML домена" in libvirt_md
    assert "Provision the libvirt domain" not in libvirt_md
    assert "virsh -c qemu:///system start h1" in libvirt_md

    boot_md = provision.workbook_boot_section(23950, "127.0.0.1:23951", "pw",
                                              language="ru")
    assert "Загрузите ВМ" in boot_md
    assert "Войдите как `root`" in boot_md
    assert "После этого live-ISO отвечает по SSH" in boot_md
    assert "socat - TCP:127.0.0.1:23950" in boot_md
    assert "passwd -s <<< 'pw'" in boot_md
    for english_prose in ("Boot the VM", "Log in as `root`",
                          "The live ISO then answers SSH"):
        assert english_prose not in boot_md
