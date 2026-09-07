from archinstaller.script import InstallConfig, build_install_script

KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
       " pasha@p-745-g5")


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
    assert "useradd -m --groups video,scanner,optical,kvm,sys,wheel,uucp,games,docker 'nameless'" in script
    assert f"printf '%s\\n' '{KEY}' > /home/nameless/.ssh/authorized_keys" in script


def test_script_shells_out_passwords():
    script = build_install_script(make_cfg(root_password="ro'ot", user_password="us;er"))
    assert "printf 'root:%s\\n' 'ro'\\''ot' | chpasswd" in script
    assert "printf '%s:%s\\n' 'nameless' 'us;er' | chpasswd" in script


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
    assert "User=nameless' > /etc/sddm.conf.d/10-archinstaller.conf" in script


def test_no_sddm_autologin_without_graphical():
    script = build_install_script(make_cfg())
    assert "sddm.conf.d" not in script


def test_pacman_tuning_and_repos_present():
    script = build_install_script(make_cfg())
    assert "IgnorePkg = kweather kweathercore akonadi kmix kalarm kget ktorrent kalk" in script
    assert "ParallelDownloads = 10" in script
    assert "sed -i 's/^#\\[multilib\\]/[multilib]/' /etc/pacman.conf" in script
    assert "[xlibre]" in script
    assert "[sonicde]" in script
    assert "pacman-key --lsign-key B97F7C613F359424" in script
    assert "pacman-key --recv-keys 73580DE2EDDFA6D6" in script
    assert "pacman-key --lsign-key 3B87898C73F11DF5" in script


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
