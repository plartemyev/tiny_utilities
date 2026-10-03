from archinstaller.script import InstallConfig, build_install_script

KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
       " nameless@example")


def make_cfg(**overrides):
    defaults = {
        "disk": "/dev/vda",
        "hostname": "arch-host-2026-09-06",
        "locale": "en_US.UTF-8",
        "swap_size": "16G",
        "username": "nameless",
        "root_password": "rootpw",
        "user_password": "userpw",
        "public_key": KEY,
        "graphical": False,
        "virt": "oracle",
    }
    defaults.update(overrides)
    return InstallConfig(**defaults)


def test_script_contains_configured_values():
    script = build_install_script(make_cfg())
    assert "sfdisk '/dev/vda'" in script
    assert "mkfs.fat -F 32 '/dev/vda1'" in script
    assert "mount --mkdir '/dev/vda2' /mnt/new-root" in script
    assert "printf '%s\\n' 'arch-host-2026-09-06' > /etc/hostname" in script
    assert "mkswap -U clear --size 16G --file /swapfile" in script


def test_grub_install_registers_entry_and_removable_fallback():
    script = build_install_script(make_cfg())
    entry = "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB"
    assert entry + "\n" + entry + " --removable" in script
    assert "useradd -m --groups video,scanner,optical,kvm,sys,wheel,uucp,games,docker 'nameless'" in script
    assert f"printf '%s\\n' '{KEY}' > /home/nameless/.ssh/authorized_keys" in script


def test_script_shells_out_passwords():
    script = build_install_script(make_cfg(root_password="ro'ot", user_password="us;er"))
    assert "printf 'root:%s\\n' 'ro'\\''ot' | chpasswd" in script
    assert "printf '%s:%s\\n' 'nameless' 'us;er' | chpasswd" in script


def test_graphical_seeds_default_look_and_feel():
    script = build_install_script(make_cfg(graphical=True))
    assert "install -d -m 700 -o 'nameless' -g 'nameless' /home/nameless/.config/kdedefaults" in script
    assert ("printf '%s\\n' '[General]' 'ColorScheme=SilverLight' '' '[Icons]'"
            " 'Theme=silver' '' '[KDE]' 'widgetStyle=Silver'"
            " > /home/nameless/.config/kdedefaults/kdeglobals") in script
    assert "printf '%s' 'org.kde.silverlightbottompanel.desktop' > /home/nameless/.config/kdedefaults/package" in script
    assert ("printf '%s\\n' '[KDE]'"
            " 'LookAndFeelPackage=org.kde.silverlightbottompanel.desktop'"
            " > /home/nameless/.config/kdeglobals") in script
    assert "chown -R 'nameless':'nameless' /home/nameless/.config" in script


def test_console_only_seeds_no_look_and_feel():
    script = build_install_script(make_cfg())
    assert "LookAndFeelPackage" not in script


def test_dns_fallback_dispatcher_installed_in_base_system():
    script = build_install_script(make_cfg())
    assert ("cat > /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback"
            " <<'DNS_HOOK'") in script
    assert 'setsid "$0" "$iface" "$event" --worker' in script
    assert 'drill archlinux.org @"$s"' in script
    assert 'nmcli con modify "$conn" ipv4.ignore-auto-dns "$mode"' in script
    assert "chmod 755 /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback" in script
    # the hook body must be inside the chroot heredoc
    assert script.index("90-archinstaller-dns-fallback <<'DNS_HOOK'") < script.index("chmod 755") < script.rindex("CHROOT")


def test_console_only_by_default():
    script = build_install_script(make_cfg())
    assert "systemctl enable sddm" not in script
    assert "blender" not in script
    assert "pacman -Sy --needed --noconfirm" in script


def test_graphical_flag_installs_desktop():
    script = build_install_script(make_cfg(graphical=True))
    assert "systemctl enable sddm" in script
    assert "pacman -S --needed --noconfirm" in script
    assert "blender" in script
    assert "virtualbox-guest-utils" in script.split()
    assert "[Autologin]" in script
    assert "'User=nameless' \"Session=$session_name\"" in script


def test_sddm_autologin_session_is_detected_from_installed_sessions():
    script = build_install_script(make_cfg(graphical=True))
    assert "find /usr/share/xsessions /usr/share/wayland-sessions" in script
    assert 'session_name=$(basename "$session")' in script


def test_graphical_uses_full_virtualbox_guest_utils():
    script = build_install_script(make_cfg(graphical=True))
    tokens = script.split()
    assert "virtualbox-guest-utils" in tokens
    assert "virtualbox-guest-utils-nox" not in tokens


def test_console_only_uses_nox_virtualbox_guest_utils():
    script = build_install_script(make_cfg())
    tokens = script.split()
    assert "virtualbox-guest-utils-nox" in tokens
    assert "virtualbox-guest-utils" not in tokens


def test_non_virtualbox_targets_drop_virtualbox_guest_utils():
    for virt in ("none", "kvm", "qemu", "vmware", "microsoft", "parallels"):
        tokens = build_install_script(make_cfg(virt=virt, graphical=True)).split()
        assert not any(t.startswith("virtualbox-guest-utils") for t in tokens), virt


def test_qemu_guest_agent_enabled_only_for_kvm_targets():
    for virt in ("kvm", "qemu"):
        assert "systemctl enable qemu-guest-agent" in build_install_script(make_cfg(virt=virt))
    for virt in ("oracle", "none", "vmware", "microsoft"):
        assert "systemctl enable qemu-guest-agent" not in build_install_script(make_cfg(virt=virt))


def test_vboxservice_enabled_only_for_virtualbox_targets():
    assert "systemctl enable vboxservice" in build_install_script(make_cfg(virt="oracle"))
    for virt in ("none", "kvm", "qemu", "vmware", "microsoft", "parallels"):
        assert "systemctl enable vboxservice" not in build_install_script(make_cfg(virt=virt))


def test_open_vm_tools_only_for_vmware_targets():
    assert "open-vm-tools" in build_install_script(make_cfg(virt="vmware", graphical=True)).split()
    for virt in ("oracle", "none", "kvm", "qemu", "microsoft"):
        tokens = build_install_script(make_cfg(virt=virt, graphical=True)).split()
        assert "open-vm-tools" not in tokens, virt


def test_graphical_installs_sonicde_stack_before_graphical_packages():
    script = build_install_script(make_cfg(graphical=True))
    tokens = script.split()
    assert "sonicde-meta" in tokens
    assert "sonic-ecco" in tokens
    assert "sonic-win" in tokens
    assert "sonic-workspace" in tokens
    assert script.index("Installing Xlibre X server") < script.index("Installing Sonic DE base")
    assert script.index("Installing Sonic DE base") < script.index("Installing graphical packages")
    assert script.index("Installing graphical packages") < script.index("blender")
    assert "dolphin" not in tokens
    assert "sonic-x11-session" not in tokens


def test_no_sddm_autologin_without_graphical():
    script = build_install_script(make_cfg())
    assert "sddm.conf.d" not in script


def test_pacman_tuning_and_repos_present():
    script = build_install_script(make_cfg())
    assert "IgnorePkg = kweather kweathercore akonadi kmix kalarm kget ktorrent kalk" in script
    assert "ParallelDownloads = 10" in script
    assert "sed -i 's/^#\\[multilib\\]/[multilib]/' /etc/pacman.conf" in script
    assert "sed -i '/^\\[multilib\\]$/,/^$/ s/^#Include/Include/' /etc/pacman.conf" in script
    assert "'s/^#Include/Include/'" not in script
    assert "[xlibre-stable]" in script
    assert "[sonicde]" in script
    assert "pacman-key --lsign-key B97F7C613F359424" in script
    assert "recv-keys" not in script
    assert "3B87898C73F11DF5" in script
    assert "retry pacman -Sy --needed --noconfirm" in script
    assert "retry curl -O https://xlibre-arch.github.io/xlibre-archlinux.asc" in script


def test_locale_line_is_escaped_for_sed():
    script = build_install_script(make_cfg(locale="de_DE.UTF-8"))
    assert "s/^#de_DE\\.UTF-8 UTF-8$/de_DE.UTF-8 UTF-8/" in script
    assert "printf 'LANG=%s\\n' 'de_DE.UTF-8' > /etc/locale.conf" in script


def test_sudoers_and_services():
    script = build_install_script(make_cfg())
    assert "%wheel ALL=(ALL:ALL) ALL" in script
    assert "nameless ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/20-archinstaller" in script
    assert "systemctl enable systemd-resolved" in script
    assert "systemctl enable NetworkManager" in script
    assert "systemctl disable systemd-networkd" in script
    assert "systemctl enable sshd" in script


def test_ssh_password_auth_disabled_after_user_creation():
    script = build_install_script(make_cfg())
    assert "PasswordAuthentication no" in script
    assert "KbdInteractiveAuthentication no" in script
    assert script.index("authorized_keys") < script.index("PasswordAuthentication no")


def test_firewalld_installed_and_enabled_by_default():
    script = build_install_script(make_cfg())
    assert "retry pacman -S --needed --noconfirm firewalld" in script
    assert "systemctl enable firewalld" in script
    assert script.index("pacman -S --needed --noconfirm firewalld") < script.rindex("CHROOT")
