from __future__ import annotations

import dataclasses

BASE_PACKAGES = """
acpid amd-ucode archinstall argon2 base bash-completion bcachefs-tools bind  cloud-init dhclient dhcpcd dmidecode
dmraid dnsmasq edk2-shell ethtool exfatprogs fatresize fsarchiver glibc-locales gpart grml-zsh-config grub  hdparm
hyperv inetutils intel-ucode iotop iptables iwd jfsutils ldns lftp linux linux-firmware lsb-release lsscsi memtest86+
memtest86+-efi mkinitcpio-archiso mkinitcpio-nfs-utils modemmanager mtools mtr nbd ndisc6 networkmanager nfs-utils nmap
nss-mdns nvme-cli open-iscsi openconnect openpgp-card-tools openvpn pptpclient qemu-guest-agent refind reflector
rp-pppoe rsync sdparm sequoia-sq sg3_utils smartmontools smbnetfs sof-firmware squashfs-tools ssh-tools syslinux
systemd-resolvconf testdisk tmux tpm2-tools traceroute udftools udisks2 unrar unzip uriparser usb_modeswitch usbmuxd
usbutils vim virtualbox-guest-utils-nox wireguard-tools wireless-regdb wireless_tools wvdial xl2tpd zsh-autosuggestions
"""

CONSOLE_PACKAGES = """
7zip acpid adwaita-icon-theme alsa-firmware alsa-utils amd-ucode android-tools android-udev archinstall argon2 aribb24
aribb25 aspell-en aspell-ru aws-cli-v2 b3sum b43-fwcutter base base-devel bash-completion bash-language-server
bcachefs-tools bind blendr bluez-tools bluez-utils bolt cfr clamav clang clonezilla cloud-init container-diff corepack
ddrescue dhclient dhcpcd dive dmraid dnsmasq docker-buildx docker-compose drone-cli drone-runner-docker edk2-aarch64
edk2-ovmf edk2-shell ethtool evtest exfatprogs extra-cmake-modules fatresize fsarchiver git-lfs
git-repair glibc-locales gopls gpart grml-zsh-config grub guestfs-tools hdparm htop hyperv iftop imvirt inetutils
intel-ucode iotop iptables irssi iso-codes iwd jadx jdk-openjdk jedi-language-server jfsutils kompose
ldns lftp libaemu libcdr libdc1394 libdnet libdvdcss libdvdnav libgme libkate liblockfile liblouis libmicrodns
libmirage libnss_nis libsigc++ libsonic libspeechd libunrar libverto libvirt-dbus libzip linux linux-atm linux-firmware
linux-firmware-marvell live-media livecd-sounds lsb-release lsscsi lua-language-server lua-socket lynx man-db man-pages
mc memtest86+ memtest86+-efi mkinitcpio-archiso mkinitcpio-nfs-utils modemmanager mtools mtr nano nbd ndisc6
networkmanager nfs-utils nmap npm nss-mdns nvme-cli nvtop open-iscsi opencode openconnect openjdk-doc
openpgp-card-tools openvpn otf-fira-mono otf-fira-sans pandoc-cli pandoc-crossref pandoc-plot passff-host pipewire-alsa
pipewire-v4l2 plantuml-ascii-math power-profiles-daemon pptpclient pv python-build-backend python-docker
python-libguestfs python-pandocfilters python-poetry python-psycopg-pool python-pypandoc python-pytest-ruff
python-ruff-api python-sphinx_rtd_theme python-yaml qemu-audio-pipewire qemu-block-nfs qemu-docs qemu-tools
qemu-user-static-binfmt read-edid refind reflector repo rp-pppoe rsync rust-analyzer sdl_imagesdparm sequoia-sq
sg3_utils smartmontools smbnetfs squashfs-tools ssh-tools syslinux systemd-resolvconf tcpdump terminus-font terraform
terragrunt testdisk tflint tmux tpm2-tools traceroute ttf-dejavu ttf-droid ttf-fira-code ttf-fira-mono ttf-fira-sans
ttf-liberation udftools udisks2 unrar unzip uriparser usb_modeswitch usbmuxd usbutils uv vcdimager vim virt-firmware
virt-install virt-what virtualbox-guest-utils-nox vkd3d wireguard-tools wireless-regdb wireless_tools wit wvdial xl2tpd
yaml-language-server yarn yt-dlp zsh-autosuggestions
"""

# Installed before SONICDE_PACKAGES: xlibre-xserver Provides: xorg-server, and
# sonic-login-manager (a sonicde-meta dependency) Requires: xorg-server — with
# the server installed first that dependency resolves to the xlibre build
# instead of pulling in the conflicting stock xorg-server.
XLIBRE_PACKAGES = """
xlibre-input-evdev xlibre-input-wacom xlibre-meta xlibre-video-amdgpu xlibre-video-ati xlibre-video-qxl
"""

# Installed before GRAPHICAL_PACKAGES: the sonic packages conflict with (and
# provide) the stock KDE/Plasma ones, so having them installed first makes
# pacman resolve those dependencies to the sonic replacements.
SONICDE_PACKAGES = """
sonicde-meta
"""

GRAPHICAL_PACKAGES = """
audacious audacity blender brltty cdrdao chromium colord-gtk dleyna dolphin-plugins espeakup filelight
firefox-i18n-en-ca firefox-i18n-ru firefox-spell-ru firefox-ublock-origin gameconqueror gimp gst-libav gst-plugin-dav1d
gst-plugin-rav1e guvcview-qt gwenview intel-media-driver joyutils kate kgraphviewer lib32-libva lib32-mesa
libreoffice-fresh-ru libva-utils libvdpau-va-gl memtest_vulkan modem-manager-gui mono-msbuild-sdkresolver
network-manager-applet networkmanager-openconnect okular open-vm-tools pavucontrol peek pycharm-community-edition
pipewire-pulse qbittorrent radeontop renderdoc scrcpy spice-vdagent systray-x-common telegram-desktop texlive-latexextra
thunderbird-i18n-en-us thunderbird-i18n-ru virglrenderer virt-manager virt-viewer vkmark vlc vlc-plugins-all
vulkan-broadcom vulkan-dzn vulkan-extra-tools vulkan-gfxstream vulkan-headers vulkan-intel vulkan-mesa-layers
vulkan-radeon vulkan-virtio wine-gecko xarchiver xorg-xset xreader zed
"""

IGNORE_PKG = "kweather kweathercore akonadi kmix kalarm kget ktorrent kalk"
# sonic-workspace's startplasma never materializes the Silver session defaults
# (~/.config/kdedefaults: [Icons] Theme=silver, colors, cursors, decorations):
# with no look-and-feel recorded its defaults write is skipped, and when it
# runs it produces empty files. Without the defaults every theme/icon lookup
# falls back to hicolor and the desktop renders generic or missing icons.
# Running plasma-apply-lookandfeel instead is not an option: it works only in
# a fully interactive session (it fails/segfaults in chroot and autostart
# contexts), so the installer seeds the kdedefaults files directly, mirroring
# the state a successful apply leaves behind (verified against a working
# host). The kdedefaults/package marker plus kdeglobals [KDE]
# LookAndFeelPackage keep startplasma's broken defaults write from firing on
# later logins. Fork-specific values — revisit on sonic-workspace updates.
DEFAULT_LOOKANDFEEL = "org.kde.silverlightbottompanel.desktop"
XLIBRE_KEY_ID = "B97F7C613F359424"
SONICDE_KEY_ID = "3B87898C73F11DF5"
USER_GROUPS = "video,scanner,optical,kvm,sys,wheel,uucp,games,docker"

# Installed into the new system: probes the connection's DHCP DNS servers
# directly on every network event and keeps ignore-auto-dns off (router DNS,
# search domains and split-DNS all apply) while at least one server answers;
# flips it on only while they are all dead, so systemd-resolved's fallback
# resolvers take over. Self-reverts on the next event after the network heals.
# Runs detached from the dispatcher (NM kills slow scripts); flock serializes
# overlapping runs, and the no-op check prevents reapply event loops.
_DNS_FALLBACK_HOOK = (
    "#!/bin/sh",
    "# archinstaller: use DHCP-provided DNS whenever it answers; ignore it",
    "# (systemd-resolved fallback resolvers take over) while it does not.",
    'iface="$1"; event="$2"',
    'case "$event" in',
    "    up|reapply|dhcp4-change|dhcp6-change|manual) ;;",
    "    *) exit 0 ;;",
    "esac",
    'case "$3" in',
    "    --worker) ;;",
    "    *)  # dispatcher context: NM kills slow scripts, probe in the background",
    '        setsid "$0" "$iface" "$event" --worker >/dev/null 2>&1 </dev/null &',
    "        exit 0 ;;",
    "esac",
    "exec 9>/run/archinstaller-dns-fallback.lock || exit 0",
    "flock -n 9 || exit 0",
    'servers="${DHCP4_DOMAIN_NAME_SERVERS:-} ${DHCP6_DOMAIN_NAME_SERVERS:-}"',
    'if [ -z "$(printf \'%s\' "$servers" | tr -d \' \\t\')" ]; then',
    '    servers="$(nmcli -f DHCP4 dev show "$iface" 2>/dev/null \\',
    "        | sed -n 's/^[^:]*: *domain_name_servers = //p')\"",
    "fi",
    '[ -n "$servers" ] || exit 0',
    'alive=""',
    "for s in $servers; do",
    '    if timeout 4 drill archlinux.org @"$s" >/dev/null 2>&1; then',
    '        alive=1; break',
    "    fi",
    "done",
    "mode=no; [ -n \"$alive\" ] || mode=yes",
    'conn="${CONNECTION_ID:-$(nmcli -g GENERAL.CONNECTION dev show "$iface" 2>/dev/null)}"',
    '[ -n "$conn" ] || exit 0',
    '[ "$(nmcli -g ipv4.ignore-auto-dns con show "$conn" 2>/dev/null)" = "$mode" ] && \\',
    '    [ "$(nmcli -g ipv6.ignore-auto-dns con show "$conn" 2>/dev/null)" = "$mode" ] && exit 0',
    'nmcli con modify "$conn" ipv4.ignore-auto-dns "$mode" ipv6.ignore-auto-dns "$mode" || exit 0',
    'nmcli dev reapply "$iface" >/dev/null 2>&1',
)


@dataclasses.dataclass(frozen=True)
class InstallConfig:
    disk: str
    hostname: str
    locale: str
    swap_size: str
    username: str
    root_password: str
    user_password: str
    public_key: str
    graphical: bool
    virt: str = "oracle"
    # The target disk accepts discards (SSD/NVMe hardware, or a VM disk whose
    # hypervisor forwards guest TRIM): enables fstrim.timer and the swapfile
    # fstab discard option; VM targets additionally mount root with the
    # continuous discard option so freed extents unmap the drive image at once.
    discard: bool = False
    # Base URL of the local arch-cache-mirror (http://<host-ip>:8282) when
    # --local-mirror is set: the sole pacman source for the live environment
    # and the installed system, extra-repo Server lines included.
    local_mirror: str | None = None


def build_install_script(cfg: InstallConfig) -> str:
    return "\n".join(part for part in [
        _header(),
        _partitioning(cfg.disk),
        _formatting(cfg),
        _local_mirror(cfg),
        _pacstrap(cfg),
        _fstab(),
        _chroot(cfg),
    ] if part)


def _header() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        "log() { printf '\\n===== %s =====\\n' \"$*\"; }\n"
    )


def _partitioning(disk: str) -> str:
    return (
        # A previous FAILED run leaves /mnt/new-root (plus its /boot ESP)
        # mounted and the guest swapfile swapon'ed; sfdisk refuses to
        # repartition a busy disk, so release first (no-ops on a fresh ISO).
        "swapoff -a 2>/dev/null || true\n"
        "umount -R /mnt/new-root 2>/dev/null || true\n"
        f"log 'Partitioning {disk} (1G ESP + rest for root)'\n"
        f"wipefs -af {_sh(disk)}\n"
        f"sfdisk {_sh(disk)} <<'SFDISK'\n"
        "label: dos\n"
        ",1G,0xef\n"
        ",,\n"
        "SFDISK\n"
    )


def _formatting(cfg: InstallConfig) -> str:
    # Continuous discard on VM targets: freed extents unmap immediately, keeping
    # the hypervisor-side drive image (VDI/qcow2/...) compact. Real SSDs get the
    # weekly fstrim.timer batch instead (no per-delete latency cost). genfstab
    # copies the mount options verbatim, so the option persists in fstab.
    options = " -o discard" if cfg.discard and cfg.virt != "none" else ""
    return (
        "log 'Creating filesystems and mounting'\n"
        f"mkfs.fat -F 32 {_sh(cfg.disk + '1')}\n"
        f"mkfs.ext4 -F {_sh(cfg.disk + '2')}\n"
        f"mount --mkdir{options} {_sh(cfg.disk + '2')} /mnt/new-root\n"
        f"mount --mkdir {_sh(cfg.disk + '1')} /mnt/new-root/boot\n"
    )


def _local_mirror(cfg: InstallConfig) -> str:
    # Sole mirrorlist entry for the live environment: pacstrap downloads the
    # official repos through the local arch-cache-mirror, so reinstalls hit
    # its package cache instead of the public mirrors.
    if cfg.local_mirror is None:
        return ""
    return (
        "log 'Pointing the live pacman mirrorlist at the local cache mirror'\n"
        f"printf '%s\\n' {_sh(_mirrorlist_line(cfg))} > /etc/pacman.d/mirrorlist\n"
    )


def _mirrorlist_line(cfg: InstallConfig) -> str:
    return f"Server = {cfg.local_mirror}/$repo/os/$arch"


def _extra_repo_servers(cfg: InstallConfig) -> tuple[str, str]:
    """Server lines for the [xlibre-stable] and [sonicde] pacman sections.

    With a local cache mirror both point at the mirror's own repo segments,
    which carry the upstream repo names (xlibre, sonicde) — pacman requests
    the database named after the section (xlibre-stable), so the sections
    cannot reuse the mirrorlist's $repo template here.
    """
    if cfg.local_mirror is None:
        return ("Server = https://packages.xlibre.net/arch/stable/$arch",
                "Server = https://sonicde-arch.github.io/$arch")
    return (f"Server = {cfg.local_mirror}/xlibre/os/$arch",
            f"Server = {cfg.local_mirror}/sonicde/os/$arch")


def _pacstrap(cfg: InstallConfig) -> str:
    return (
        "log 'Bootstrapping base system with pacstrap (long step)'\n"
        "pacstrap -K /mnt/new-root \\\n"
        f"    {_wrapped(_select_guest_utils(BASE_PACKAGES, cfg))}\n"
    )


def _select_guest_utils(packages: str, cfg: InstallConfig) -> str:
    # Hypervisor guest agents: virtualbox-guest-utils and -nox conflict, so
    # exactly one variant must be requested on VirtualBox targets (the full
    # build with X11/Wayland integration for graphical installs, the headless
    # nox build otherwise); on any other target both are dead weight and are
    # dropped.
    if cfg.virt == "oracle":
        if cfg.graphical:
            return packages.replace("virtualbox-guest-utils-nox", "virtualbox-guest-utils")
        return packages
    return " ".join(t for t in packages.split()
                    if not t.startswith("virtualbox-guest-utils"))


def _select_graphical_packages(packages: str, cfg: InstallConfig) -> str:
    # open-vm-tools is VMware-specific; on any other target it is dead weight.
    if cfg.virt == "vmware":
        return packages
    return " ".join(t for t in packages.split() if t != "open-vm-tools")


def _swap_fstab_line(cfg: InstallConfig) -> str:
    # discard makes swapon trim unused swap blocks (a full trim at every
    # swapon plus frees as pages are released), passing them on to the
    # backing SSD or hypervisor drive image.
    options = "defaults,discard" if cfg.discard else "defaults"
    return f"/swapfile none swap {options} 0 0"


def _fstab() -> str:
    return (
        "log 'Generating /etc/fstab'\n"
        "genfstab -U /mnt/new-root >> /mnt/new-root/etc/fstab\n"
    )


def _chroot(cfg: InstallConfig) -> str:
    user = _sh(cfg.username)
    home = f"/home/{cfg.username}"
    xlibre_server, sonicde_server = _extra_repo_servers(cfg)
    lines = [
        "log 'Configuring the new system (arch-chroot)'",
        "arch-chroot /mnt/new-root /bin/bash <<'CHROOT'",
        "set -euo pipefail",
        "log() { printf '\\n===== %s =====\\n' \"$*\"; }",
        "",
        "retry() {",
        "    local attempt=1",
        "    while true; do",
        "        if \"$@\"; then",
        "            return 0",
        "        fi",
        "        if [ \"$attempt\" -ge 3 ]; then",
        "            return 1",
        "        fi",
        "        echo \"attempt $attempt/3 failed: $*; retrying in 5s...\"",
        "        attempt=$((attempt + 1))",
        "        sleep 5",
        "    done",
        "}",
        "",
        "log 'Setting root password, enabling sshd'",
        f"printf 'root:%s\\n' {_sh(cfg.root_password)} | chpasswd",
        "systemctl enable sshd",
        "",
        f"log 'Setting hostname {_sh(cfg.hostname)} and locale {_sh(cfg.locale)}'",
        f"printf '%s\\n' {_sh(cfg.hostname)} > /etc/hostname",
        f"sed -i 's/^#{_sed_regex(cfg.locale)} UTF-8$/{cfg.locale} UTF-8/' /etc/locale.gen",
        "locale-gen",
        f"printf 'LANG=%s\\n' {_sh(cfg.locale)} > /etc/locale.conf",
        "",
        "log 'Installing GRUB bootloader'",
        # The NVRAM entry alone is unreliable: every wipe randomizes the MBR
        # disk-id so entries from previous installs stop resolving, and
        # VirtualBox EFI drops guest-written boot entries on guest-initiated
        # reboots. --removable additionally installs the signature-less
        # /EFI/BOOT/BOOTX64.EFI fallback that boots without any NVRAM entry.
        "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB",
        "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB --removable",
        "grub-mkconfig -o /boot/grub/grub.cfg",
        "mkinitcpio -P",
        "",
        "log 'Tuning /etc/pacman.conf'",
        "sed -i 's/^#Color/Color/' /etc/pacman.conf",
        "sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 10/' /etc/pacman.conf",
        f"sed -i '/^\\[options\\]$/a IgnorePkg = {IGNORE_PKG}' /etc/pacman.conf",
        "sed -i 's/^#\\[multilib\\]/[multilib]/' /etc/pacman.conf",
        "sed -i '/^\\[multilib\\]$/,/^$/ s/^#Include/Include/' /etc/pacman.conf",
        *(["",
           f"log 'Pointing pacman at the local cache mirror ({cfg.local_mirror})'",
           f"printf '%s\\n' {_sh(_mirrorlist_line(cfg))} > /etc/pacman.d/mirrorlist",
           ] if cfg.local_mirror else []),
        "cat >> /etc/pacman.conf <<'REPOS'",
        "",
        "[xlibre-stable]",
        xlibre_server,
        "",
        "[sonicde]",
        sonicde_server,
        "REPOS",
        "",
        "log 'Fetching and signing third-party repository keys'",
        "retry curl -O https://xlibre-arch.github.io/xlibre-archlinux.asc",
        "pacman-key --add xlibre-archlinux.asc",
        f"pacman-key --finger {XLIBRE_KEY_ID}",
        f"pacman-key --lsign-key {XLIBRE_KEY_ID}",
        "retry curl -O https://sonicde-arch.github.io/sonicde-archlinux.asc",
        "pacman-key --add sonicde-archlinux.asc",
        f"pacman-key --finger {SONICDE_KEY_ID}",
        f"pacman-key --lsign-key {SONICDE_KEY_ID}",
        "",
        "log 'Granting wheel group sudo rights'",
        "printf '%s\\n' '%wheel ALL=(ALL:ALL) ALL' > /etc/sudoers.d/10-wheel",
        "chmod 440 /etc/sudoers.d/10-wheel",
        "",
        f"log 'Creating {cfg.swap_size} swap file'",
        f"mkswap -U clear --size {cfg.swap_size} --file /swapfile",
        "swapon /swapfile",
        f"printf '%s\\n' {_sh(_swap_fstab_line(cfg))} >> /etc/fstab",
        "",
        "log 'Installing console packages (long step)'",
        "retry pacman -Sy --needed --noconfirm \\",
        f"    {_wrapped(_select_guest_utils(CONSOLE_PACKAGES, cfg))}",
    ]
    if cfg.graphical:
        lines += [
            "",
            "log 'Installing Xlibre X server (long step)'",
            "retry pacman -S --needed --noconfirm \\",
            f"    {_wrapped(XLIBRE_PACKAGES)}",
            "",
            "log 'Installing Sonic DE base (long step)'",
            "retry pacman -S --needed --noconfirm \\",
            f"    {_wrapped(SONICDE_PACKAGES)}",
            "",
            "log 'Installing graphical packages (long step)'",
            "retry pacman -S --needed --noconfirm \\",
            f"    {_wrapped(_select_graphical_packages(GRAPHICAL_PACKAGES, cfg))}",
            "",
            "log 'Enabling sonic-login-manager display manager'",
            "systemctl enable soniclogin",
            "",
            f"log 'Enabling sonic-login-manager autologin for {cfg.username}'",
            "mkdir -p /etc/soniclogin.conf.d",
            # || true: find exits 1 when one of the two directories is missing
            # (the current sonicde set ships no Wayland session file), and
            # pipefail + set -e would abort before the empty check below.
            ("session=$(find /usr/share/xsessions /usr/share/wayland-sessions"
             " -maxdepth 1 -name '*.desktop' 2>/dev/null | sort | head -n 1"
             " || true)"),
            "if [ -z \"$session\" ]; then",
            "    echo 'no session desktop files found' >&2",
            "    exit 1",
            "fi",
            "session_name=$(basename \"$session\")",
            (f"printf '%s\\n' '[Autologin]' 'User={cfg.username}'"
             " \"Session=$session_name\""
             " > /etc/soniclogin.conf.d/10-archinstaller.conf"),
        ]
    lines += [
        "",
        f"log 'Creating user {cfg.username}'",
        f"useradd -m --groups {USER_GROUPS} {user}",
        f"printf '%s:%s\\n' {user} {_sh(cfg.user_password)} | chpasswd",
        "",
        f"log 'Granting passwordless sudo to {cfg.username}'",
        f"printf '%s\\n' '{cfg.username} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/20-archinstaller",
        "chmod 440 /etc/sudoers.d/20-archinstaller",
        f"install -d -m 700 -o {user} -g {user} {home}/.ssh",
        f"printf '%s\\n' {_sh(cfg.public_key)} > {home}/.ssh/authorized_keys",
        f"chmod 600 {home}/.ssh/authorized_keys",
        f"chown {user}:{user} {home}/.ssh/authorized_keys",
        *([
            "",
            "log 'Seeding the default Silver session defaults'",
            f"install -d -m 700 -o {user} -g {user} {home}/.config/kdedefaults",
            (f"printf '%s\\n' '[General]' 'ColorScheme=SilverLight' '' '[Icons]'"
             " 'Theme=silver' '' '[KDE]' 'widgetStyle=Silver'"
             f" > {home}/.config/kdedefaults/kdeglobals"),
            (f"printf '%s\\n' '[Mouse]' 'cursorTheme=silver_cursors_light'"
             f" > {home}/.config/kdedefaults/kcminputrc"),
            (f"printf '%s\\n' '[Theme]' 'name=silver-light'"
             f" > {home}/.config/kdedefaults/plasmarc"),
            (f"printf '%s\\n' '[DesktopSwitcher]' 'LayoutName=org.kde.silver.desktop'"
             " '' '[WindowSwitcher]' 'LayoutName=org.kde.silver.desktop' ''"
             " '[org.kde.kdecoration2]' 'library=org.kde.silver' 'theme=Silver'"
             f" > {home}/.config/kdedefaults/kwinrc"),
            (f"printf '%s\\n' '[KSplash]' 'Theme=org.kde.silver.desktop'"
             f" > {home}/.config/kdedefaults/ksplashrc"),
            # startplasma re-runs its (empty-writing) defaults step whenever
            # this marker differs from kdeglobals [KDE] LookAndFeelPackage;
            # the marker must carry no trailing newline for the comparison.
            (f"printf '%s' '{DEFAULT_LOOKANDFEEL}'"
             f" > {home}/.config/kdedefaults/package"),
            (f"printf '%s\\n' '[KDE]'"
             f" 'LookAndFeelPackage={DEFAULT_LOOKANDFEEL}'"
             f" > {home}/.config/kdeglobals"),
            "",
            "log 'Making the ACPI power button shut down'",
            # PowerDevil takes a block inhibitor on handle-power-key, so
            # logind's default (poweroff) never fires; the non-mobile default
            # action is the logout dialog, which stalls host-side
            # `VBoxManage controlvm acpipowerbutton` on an autologin desktop.
            # 8 = PowerDevil PowerButtonAction::Shutdown.
            (f"printf '%s\\n' '[AC][HandleButtonLid]' 'powerButtonAction=8'"
             " '[Battery][HandleButtonLid]' 'powerButtonAction=8'"
             " '[LowBattery][HandleButtonLid]' 'powerButtonAction=8'"
             f" > {home}/.config/powerdevilrc"),
            *([
                "",
                "log 'Handing ACPI power buttons to logind (VM target)'",
                # On X11 sessions PowerDevil's button delivery is dead (its
                # kglobalaccel grabs never fire a configured action) while its
                # logind inhibitor blocks the default poweroff: the button
                # becomes a no-op (verified 2026-10-03 on powerdevil 6.7.5).
                # VMs have no battery or backlight, so DE power management is
                # worth less than a working button — mask PowerDevil and let
                # logind's HandlePowerKey=poweroff shut the machine down.
                f"mkdir -p {home}/.config/systemd/user",
                f"ln -s /dev/null {home}/.config/systemd/user/plasma-powerdevil.service",
            ] if cfg.virt != "none" else []),
            f"chown -R {user}:{user} {home}/.config",
        ] if cfg.graphical else []),
        "",
        "log 'Disabling sshd password authentication'",
        "mkdir -p /etc/ssh/sshd_config.d",
        ("printf '%s\\n' 'PasswordAuthentication no' 'KbdInteractiveAuthentication no'"
         " > /etc/ssh/sshd_config.d/10-archinstaller.conf"),
        "",        "log 'Enabling network services'",
        "systemctl disable systemd-networkd",
        "systemctl enable systemd-resolved",
        "systemctl enable NetworkManager",
        *(["systemctl enable qemu-guest-agent"] if cfg.virt in ("kvm", "qemu") else []),
        *(["systemctl enable vboxservice"] if cfg.virt == "oracle" else []),
        *([
            "",
            "log 'Enabling weekly batch TRIM (fstrim.timer)'",
            # Weekly batch TRIM: low wear and no per-delete latency on real
            # SSDs; on VM disks it still unmaps free space (compacting the
            # drive image) on top of the continuous root discard.
            "systemctl enable fstrim.timer",
            ] if cfg.discard else []),
        *(["",
           "log 'Working around the frozen VirtualBox HDA DMA position reporting'",
           # VirtualBox's emulated HDA advertises a DMA position buffer that
           # never advances: the guest kernel reads hw_ptr stuck at 0, the
           # audio graph stalls on the first playback (pulse clients hang)
           # and the emulated controller keeps looping whatever sits in the
           # ALSA ring buffer to the host — a short sound fragment repeats
           # indefinitely. position_fix=1 reads the LPIB register instead,
           # which the emulation keeps accurate (verified on 7.2.20).
           ("printf '%s\\n' 'options snd-hda-intel position_fix=1'"
            " > /etc/modprobe.d/90-archinstaller-vbox-audio.conf"),
           ] if cfg.virt == "oracle" else []),
        "",
        "log 'Installing the DNS fallback NetworkManager dispatcher'",
        "cat > /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback <<'DNS_HOOK'",
        *_DNS_FALLBACK_HOOK,
        "DNS_HOOK",
        "chmod 755 /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback",
        "",
        "log 'Installing and enabling firewalld'",
        "retry pacman -S --needed --noconfirm firewalld",
        "systemctl enable firewalld",
        "CHROOT",
    ]
    return "\n".join(lines) + "\n"


def _wrapped(packages: str) -> str:
    return " \\\n    ".join(packages.split())


def _sh(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _sed_regex(locale: str) -> str:
    return locale.replace("\\", r"\\").replace(".", r"\.")
