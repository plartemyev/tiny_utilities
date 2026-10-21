"""Single source of truth for everything archinstaller executes.

`install_steps` / `post_boot_steps` describe the run as a list of `Step`
objects; `script.py` renders them to the bash install script and
`workbook.py` renders them to a markdown workbook. Command text lives
here and nowhere else.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

_SHELL_DIR = Path(__file__).parent / "shell"


def shell_lines(name: str) -> list[str]:
    """Lines of a static shell snippet shipped in archinstaller/shell/.

    The files are kept as real .sh files (readable, shellcheck-able) and
    their content is emitted verbatim into generated scripts — keep them
    free of comments and keep their trailing newline.
    """
    return (_SHELL_DIR / name).read_text(encoding="utf-8").splitlines()

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
pipewire-v4l2 pipewire-jack plantuml-ascii-math power-profiles-daemon pptpclient pv python-poetry-core python-docker
python-libguestfs python-pandocfilters python-poetry python-psycopg-pool python-pypandoc python-pytest-ruff
python-ruff-api python-sphinx_rtd_theme python-yaml qemu-audio-pipewire qemu-block-nfs qemu-docs qemu-tools
qemu-user-static-binfmt read-edid refind reflector repo rp-pppoe rsync rust-analyzer sequoia-sq
sg3_utils smartmontools smbnetfs squashfs-tools ssh-tools syslinux systemd-resolvconf tcpdump terminus-font terraform
terragrunt testdisk tflint tmux tpm2-tools traceroute ttf-dejavu ttf-droid ttf-fira-code ttf-fira-mono ttf-fira-sans
ttf-liberation udftools udisks2 unrar unzip uriparser usb_modeswitch usbmuxd usbutils uv vcdimager vim virt-firmware
virt-install virt-what virtualbox-guest-utils-nox vkd3d wireguard-tools wireless-regdb wireless_tools wit wvdial xl2tpd
yaml-language-server yarn yt-dlp zsh-autosuggestions sdl_image
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
network-manager-applet networkmanager-openconnect okular open-vm-tools pavucontrol
pipewire-pulse qbittorrent radeontop renderdoc scrcpy spice-vdagent systray-x-common telegram-desktop texlive-latexextra
thunderbird-i18n-en-us thunderbird-i18n-ru virglrenderer virt-manager virt-viewer vkmark vlc vlc-plugins-all
vulkan-broadcom vulkan-dzn vulkan-extra-tools vulkan-gfxstream vulkan-headers vulkan-intel vulkan-mesa-layers
vulkan-radeon vulkan-virtio wine-gecko xarchiver xorg-xset xreader zed qt6-multimedia-ffmpeg tesseract-data-eng
tesseract-data-rus
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
OPENCODE_PORT = 49374
OPENCODE_UNIT_PATH = ".config/systemd/user/opencode.service"

# Stage-two DNS repair, as executed by the dispatcher hook itself (cli kicks
# the hook with sudo): probes the connection's lease DNS servers on every
# network event and keeps ignore-auto-dns off (router DNS, search domains and
# split-DNS all apply) while at least one server answers; flips it on only
# while they are all dead, so systemd-resolved's fallback resolvers take over.
# Self-reverts on the next event after the network heals.
DNS_FALLBACK_WORKER = ("/etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback"
                       " \"$(ip route show default | awk '{print $5; exit}')\" manual --worker")

# Installed into the new system (see DNS_FALLBACK_WORKER for the policy);
# the body lives in shell/dns-fallback-hook.sh, emitted into the dispatcher
# file verbatim. Runs detached from the dispatcher (NM kills slow scripts);
# flock serializes overlapping runs, and the no-op check prevents reapply
# event loops.
_DNS_FALLBACK_HOOK = shell_lines("dns-fallback-hook.sh")

# Where a step's commands run: "live" is the booted ISO environment, "chroot"
# is inside the mounted new system, "post-boot" is the installed system over
# SSH after the first reboot.
LIVE = "live"
CHROOT = "chroot"
POST_BOOT = "post-boot"


@dataclasses.dataclass(frozen=True)
class Step:
    """One titled unit of work; the atom of both renderers.

    title: rendered as the bash `log` line and the workbook heading; None
        marks a continuation that belongs to the neighboring section (no log
        line, no heading).
    rationale: workbook prose (distilled from the installer's comments).
    commands: shell commands; a single command may span lines (heredocs).
    root: post-boot only — run through passwordless sudo.
    id: optional hook for cli-side orchestration (e.g. polling after the
        opencode unit is started); renderers ignore it.
    """

    title: str | None
    commands: tuple[str, ...] = ()
    rationale: str = ""
    context: str = LIVE
    root: bool = False
    id: str | None = None
    # Renderers emit a blank line before the step (section separator); False
    # glues it to the previous block (continuations, and the partitioning
    # step whose leftover-release commands precede its log marker).
    spaced: bool = True


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
    # Base URL of the local arch-cache-mirror (http://<mirror-host>:8282)
    # when --local-mirror is set: the sole pacman source for the live
    # environment and the installed system, extra-repo Server lines
    # included. For VM targets <mirror-host> is the guest's default gateway
    # (the hypervisor host, static per backend); physical targets get the
    # host's LAN IP.
    local_mirror: str | None = None
    # Stage-two parameters (post_boot_steps); unused by the install script.
    timezone: str = ""
    opencode: bool = False
    opencode_password: str | None = None


def opencode_unit(opencode_password: str) -> str:
    return "\n".join([
        "[Unit]",
        "Description=OpenCode web server",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f"Environment=OPENCODE_SERVER_PASSWORD={opencode_password}",
        f"ExecStart=/usr/bin/opencode serve --hostname 0.0.0.0 --port {OPENCODE_PORT}",
        "Restart=on-failure",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]) + "\n"


def install_steps(cfg: InstallConfig) -> list[Step]:
    steps = [
        Step(None, (
            "swapoff -a 2>/dev/null || true",
            "umount -R /mnt/new-root 2>/dev/null || true",
        )),
        Step(f"Partitioning {cfg.disk} (1G ESP + rest for root)", (
            f"wipefs -af {_sh(cfg.disk)}",
            _heredoc(f"sfdisk {_sh(cfg.disk)} <<'SFDISK'",
                     "label: dos", ",1G,0xef", ",,", "SFDISK"),
        ), rationale=(
            "A previous failed run can leave /mnt/new-root (plus its /boot ESP) mounted"
            " and its swapfile active; sfdisk refuses to repartition a busy disk. Both"
            " release commands are no-ops on a fresh system."
        ), spaced=False),
        _formatting_step(cfg),
        _local_mirror_step(cfg),
        Step("Bootstrapping base system with pacstrap (long step)", (
            ("pacstrap -K /mnt/new-root \\\n"
             f"    {_wrapped(_select_guest_utils(BASE_PACKAGES, cfg))}"),
        ), rationale=(
            "Base system plus a console toolbox. The VirtualBox guest-utils variant is"
            " chosen per target (the two variants conflict): the headless -nox build on"
            " console installs, the full build on graphical ones, and neither anywhere"
            " else."
        )),
        Step("Generating /etc/fstab", (
            "genfstab -U /mnt/new-root >> /mnt/new-root/etc/fstab",
        ), rationale="UUID-based fstab for the new system."),
    ]
    steps.extend(_chroot_steps(cfg))
    return steps


def _formatting_step(cfg: InstallConfig) -> Step:
    options = " -o discard" if cfg.discard and cfg.virt != "none" else ""
    return Step("Creating filesystems and mounting", (
        f"mkfs.fat -F 32 {_sh(cfg.disk + '1')}",
        f"mkfs.ext4 -F {_sh(cfg.disk + '2')}",
        f"mount --mkdir{options} {_sh(cfg.disk + '2')} /mnt/new-root",
        f"mount --mkdir {_sh(cfg.disk + '1')} /mnt/new-root/boot",
    ), rationale=(
        "On VM targets whose hypervisor forwards TRIM, root is mounted with the"
        " continuous 'discard' option so freed extents unmap the hypervisor-side drive"
        " image at once; genfstab copies the option into fstab. Physical SSDs get the"
        " weekly fstrim.timer batch instead (enabled below when the disk accepts"
        " discards)."
    ))


def _local_mirror_step(cfg: InstallConfig) -> Step:
    if cfg.local_mirror is None:
        return Step(None, ())
    return Step("Pointing the live pacman mirrorlist at the local cache mirror", (
        f"printf '%s\\n' {_sh(_mirrorlist_line(cfg))} > /etc/pacman.d/mirrorlist",
    ), rationale=(
        "Sole mirrorlist entry for the live environment: pacstrap downloads the"
        " official repos through the local arch-cache-mirror, so reinstalls hit its"
        " package cache instead of the public mirrors."
    ))


def _chroot_steps(cfg: InstallConfig) -> list[Step]:
    user = _sh(cfg.username)
    home = f"/home/{cfg.username}"
    steps: list[Step] = [
        Step("Setting root password, enabling sshd", (
            f"printf 'root:%s\\n' {_sh(cfg.root_password)} | chpasswd",
            "systemctl enable sshd",
        )),
        Step(f"Setting hostname {_sh(cfg.hostname)} and locale {_sh(cfg.locale)}", (
            f"printf '%s\\n' {_sh(cfg.hostname)} > /etc/hostname",
            f"sed -i 's/^#{_sed_regex(cfg.locale)} UTF-8$/{cfg.locale} UTF-8/' /etc/locale.gen",
            "locale-gen",
            f"printf 'LANG=%s\\n' {_sh(cfg.locale)} > /etc/locale.conf",
        ), rationale=(
            "The locale line is uncommented in /etc/locale.gen before locale-gen; the"
            " sed pattern escapes the dots in the locale name."
        )),
        Step("Installing GRUB bootloader", (
            "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB",
            "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB --removable",
            "grub-mkconfig -o /boot/grub/grub.cfg",
            "mkinitcpio -P",
        ), rationale=(
            "The NVRAM entry alone is unreliable: every wipe randomizes the MBR disk-id"
            " so older entries stop resolving, and VirtualBox EFI drops guest-written"
            " boot entries on guest-initiated reboots. The second, --removable install"
            " additionally provides the signature-less /EFI/BOOT/BOOTX64.EFI fallback"
            " that boots without any NVRAM entry."
        )),
        Step("Tuning /etc/pacman.conf", (
            "sed -i 's/^#Color/Color/' /etc/pacman.conf",
            "sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 10/' /etc/pacman.conf",
            f"sed -i '/^\\[options\\]$/a IgnorePkg = {IGNORE_PKG}' /etc/pacman.conf",
            "sed -i 's/^#\\[multilib\\]/[multilib]/' /etc/pacman.conf",
            "sed -i '/^\\[multilib\\]$/,/^$/ s/^#Include/Include/' /etc/pacman.conf",
        ), rationale=(
            "Color, parallel downloads, an IgnorePkg set and the multilib repo, then"
            " the two third-party repositories are appended."
        )),
        *([
            Step(f"Pointing pacman at the local cache mirror ({cfg.local_mirror})", (
                f"printf '%s\\n' {_sh(_mirrorlist_line(cfg))} > /etc/pacman.d/mirrorlist",
            ), rationale=(
                "Same sole source for the installed system as for the live environment."
            )),
        ] if cfg.local_mirror else []),
        Step(None, (
            ("cat >> /etc/pacman.conf <<'REPOS'\n"
             "\n"
             "[xlibre-stable]\n"
             f"{_extra_repo_servers(cfg)[0]}\n"
             "\n"
             "[sonicde]\n"
             f"{_extra_repo_servers(cfg)[1]}\n"
             "REPOS"),
        ), spaced=False),
        Step("Fetching and signing third-party repository keys", (
            "retry curl -O https://xlibre-arch.github.io/xlibre-archlinux.asc",
            "pacman-key --add xlibre-archlinux.asc",
            f"pacman-key --finger {XLIBRE_KEY_ID}",
            f"pacman-key --lsign-key {XLIBRE_KEY_ID}",
            "retry curl -O https://sonicde-arch.github.io/sonicde-archlinux.asc",
            "pacman-key --add sonicde-archlinux.asc",
            f"pacman-key --finger {SONICDE_KEY_ID}",
            f"pacman-key --lsign-key {SONICDE_KEY_ID}",
        ), rationale=(
            "The signing keys are fetched from their upstream homes (the cache mirror"
            " proxies repository files only, not key .asc files) and locally signed."
        )),
        Step("Granting wheel group sudo rights", (
            "printf '%s\\n' '%wheel ALL=(ALL:ALL) ALL' > /etc/sudoers.d/10-wheel",
            "chmod 440 /etc/sudoers.d/10-wheel",
        )),
        Step(f"Creating {cfg.swap_size} swap file", (
            f"mkswap -U clear --size {cfg.swap_size} --file /swapfile",
            "swapon /swapfile",
            f"printf '%s\\n' {_sh(_swap_fstab_line(cfg))} >> /etc/fstab",
        ), rationale=(
            "Fixed-size swapfile with a random clear UUID. On discard-capable disks the"
            " fstab line carries 'discard' so swapon trims unused swap blocks (a full"
            " trim at every swapon, plus frees as pages are released)."
        )),
        Step("Installing console packages (long step)", (
            ("retry pacman -Sy --needed --noconfirm \\\n"
             f"    {_wrapped(_select_guest_utils(CONSOLE_PACKAGES, cfg))}"),
        ), rationale=(
            "The console toolbox. Sound is explicit (pipewire, wireplumber,"
            " pipewire-pulse) instead of left to transitive dependencies."
        )),
    ]
    if cfg.graphical:
        steps.extend([
            Step("Installing Xlibre X server (long step)", (
                "retry pacman -S --needed --noconfirm \\\n" + f"    {_wrapped(XLIBRE_PACKAGES)}",
            ), rationale=(
                "Installed before the sonic packages: xlibre-xserver Provides:"
                " xorg-server, and sonic-login-manager Requires: xorg-server — with the"
                " server installed first that dependency resolves to the xlibre build"
                " instead of pulling in the conflicting stock xorg-server."
            )),
            Step("Installing Sonic DE base (long step)", (
                "retry pacman -S --needed --noconfirm \\\n" + f"    {_wrapped(SONICDE_PACKAGES)}",
            ), rationale=(
                "Installed before the graphical list: the sonic packages conflict with"
                " (and provide) the stock KDE/Plasma ones, so later dependencies resolve"
                " to the sonic replacements."
            )),
            Step("Installing graphical packages (long step)", (
                ("retry pacman -S --needed --noconfirm \\\n"
                 f"    {_wrapped(_select_graphical_packages(GRAPHICAL_PACKAGES, cfg))}"),
            ), rationale=(
                "open-vm-tools is kept only on VMware targets; elsewhere it is dead"
                " weight."
            )),
            Step("Enabling sonic-login-manager display manager", (
                "systemctl enable soniclogin",
            )),
            Step(f"Enabling sonic-login-manager autologin for {cfg.username}", (
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
            ), rationale=(
                "soniclogin refuses to autologin without a Session= entry; the session"
                " is auto-detected from the installed .desktop files. The find carries"
                " || true because the current session set is X11-only: find exits 1 on"
                " the missing wayland directory and set -e would abort before the empty"
                " check."
            )),
        ])
    steps.extend([
        Step(f"Creating user {cfg.username}", (
            f"useradd -m --groups {USER_GROUPS} {user}",
            f"printf '%s:%s\\n' {user} {_sh(cfg.user_password)} | chpasswd",
        )),
        Step(f"Granting passwordless sudo to {cfg.username}", (
            f"printf '%s\\n' '{cfg.username} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/20-archinstaller",
            "chmod 440 /etc/sudoers.d/20-archinstaller",
            f"install -d -m 700 -o {user} -g {user} {home}/.ssh",
            f"printf '%s\\n' {_sh(cfg.public_key)} > {home}/.ssh/authorized_keys",
            f"chmod 600 {home}/.ssh/authorized_keys",
            f"chown {user}:{user} {home}/.ssh/authorized_keys",
        ), rationale=(
            "The created user gets passwordless sudo and the provided public key for"
            " initial access. Root-owned files in a user's home make sshd (StrictModes)"
            " refuse them, hence the explicit chown."
        )),
    ])
    if cfg.graphical:
        steps.extend(_graphical_config_steps(cfg))
    steps.extend([
        Step("Disabling sshd password authentication", (
            "mkdir -p /etc/ssh/sshd_config.d",
            ("printf '%s\\n' 'PasswordAuthentication no' 'KbdInteractiveAuthentication no'"
             " > /etc/ssh/sshd_config.d/10-archinstaller.conf"),
        ), rationale=(
            "Landed after the user and its authorized_keys exist, so post-reboot access"
            " is public-key only."
        )),
        Step("Enabling network services", (
            "systemctl disable systemd-networkd",
            "systemctl enable systemd-resolved",
            "systemctl enable NetworkManager",
            *(["systemctl enable qemu-guest-agent"] if cfg.virt in ("kvm", "qemu") else []),
            *(["systemctl enable vboxservice"] if cfg.virt == "oracle" else []),
        ), rationale=(
            "NetworkManager and systemd-resolved replace the ISO's network stack;"
            " without vboxservice the host never sends video-mode hints and"
            " VBoxClient blanks the screen on VirtualBox."
        )),
        *([
            Step("Enabling weekly batch TRIM (fstrim.timer)", (
                "systemctl enable fstrim.timer",
            ), rationale=(
                "Low wear and no per-delete latency on real SSDs; on VM disks it still"
                " unmaps free space (compacting the drive image) on top of the"
                " continuous root discard."
            )),
        ] if cfg.discard else []),
        *([
            Step("Tuning guest memory pressure (small page cache)", (
                "printf '%s\\n' 'vm.watermark_scale_factor = 500'"
                " 'vm.vfs_cache_pressure = 200'"
                " > /etc/sysctl.d/90-small-cache.conf",
            ), rationale=(
                "The VM boots with its full RAM (current = max) and the virtio balloon"
                " returns pages to the host only when the guest notices pressure:"
                " freePageReporting hands back free-page hints and autodeflate inflates"
                " the balloon under host pressure. watermark_scale_factor = 500 wakes"
                " kswapd at 5% free memory (0.1% default) and the raised"
                " vfs_cache_pressure reclaims dentries/inodes sooner, keeping the page"
                " cache from claiming memory the hypervisor could reuse. (The"
                " pagecache-limit sysctls are SUSE out-of-tree, not mainline.)"
            )),
        ] if cfg.virt != "none" else []),
        *([
            Step("Working around the frozen VirtualBox HDA DMA position reporting", (
                ("printf '%s\\n' 'options snd-hda-intel position_fix=1'"
                 " > /etc/modprobe.d/90-archinstaller-vbox-audio.conf"),
            ), rationale=(
                "VirtualBox's emulated HDA advertises a DMA position buffer that never"
                " advances: the guest reads hw_ptr stuck at 0, the audio graph stalls on"
                " the first playback and the emulated controller keeps looping whatever"
                " sits in the ALSA ring buffer — a short fragment repeats indefinitely."
                " position_fix=1 reads the LPIB register instead, which the emulation"
                " keeps accurate."
            )),
        ] if cfg.virt == "oracle" else []),
        Step("Installing the DNS fallback NetworkManager dispatcher", (
            _heredoc("cat > /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback <<'DNS_HOOK'",
                     *_DNS_FALLBACK_HOOK, "DNS_HOOK"),
            "chmod 755 /etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback",
        ), rationale=(
            "Probes the connection's DHCP DNS servers on every network event and uses"
            " them only while at least one answers, so router DNS, search domains and"
            " split-DNS all apply; when none answers, DHCP DNS is ignored so"
            " systemd-resolved's fallback resolvers take over. Self-reverting on the"
            " next event after the network heals."
        )),
        Step("Installing and enabling firewalld", (
            "retry pacman -S --needed --noconfirm firewalld",
            "systemctl enable firewalld",
        )),
    ])
    return [dataclasses.replace(step, context=CHROOT) for step in steps]


def _graphical_config_steps(cfg: InstallConfig) -> list[Step]:
    user = _sh(cfg.username)
    home = f"/home/{cfg.username}"
    return [
        Step("Seeding the default Silver session defaults", (
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
        ), rationale=(
            "startplasma never materializes the Silver session defaults when none are"
            " recorded (every theme/icon lookup falls back to hicolor; the desktop"
            " renders generic or missing icons), and plasma-apply-lookandfeel works"
            " only in a fully interactive session (it fails or segfaults in chroot), so"
            " the files are seeded directly, mirroring the state a successful apply"
            " leaves behind. The no-trailing-newline package marker plus kdeglobals"
            " [KDE] LookAndFeelPackage keep startplasma's empty-writing defaults step"
            " from firing again on later logins."
        )),
        Step("Making the ACPI power button shut down", (
            # PowerDevil takes a block inhibitor on handle-power-key, so
            # logind's default (poweroff) never fires; the non-mobile default
            # action is the logout dialog, which stalls host-side
            # `VBoxManage controlvm acpipowerbutton` on an autologin desktop.
            # 8 = PowerDevil PowerButtonAction::Shutdown.
            (f"printf '%s\\n' '[AC][HandleButtonLid]' 'powerButtonAction=8'"
             " '[Battery][HandleButtonLid]' 'powerButtonAction=8'"
             " '[LowBattery][HandleButtonLid]' 'powerButtonAction=8'"
             f" > {home}/.config/powerdevilrc"),
        ), rationale=(
            "Seeds PowerDevil's Shutdown action (8) for stacks where its button"
            " delivery works (e.g. Wayland); logind's inhibitor would otherwise leave"
            " the button on the logout-dialog default."
        )),
        *([
            Step("Handing ACPI power buttons to logind (VM target)", (
                f"mkdir -p {home}/.config/systemd/user",
                f"ln -s /dev/null {home}/.config/systemd/user/plasma-powerdevil.service",
            ), rationale=(
                "On X11 sessions PowerDevil's button delivery is dead (its"
                " kglobalaccel grabs never fire a configured action) while its logind"
                " inhibitor blocks the default poweroff: the button becomes a no-op."
                " VMs have no battery or backlight, so the daemon is masked and logind's"
                " HandlePowerKey=poweroff shuts the machine down."
            )),
        ] if cfg.virt != "none" else []),
        Step(None, (
            f"chown -R {user}:{user} {home}/.config",
        ), spaced=False),
    ]


def post_boot_steps(username: str, hostname: str, timezone: str,
                    opencode: bool, opencode_password: str | None,
                    include_dns: bool = True) -> list[Step]:
    """Stage two: applied to the installed system over SSH after first boot.

    Steps run as the created user; `root` steps go through passwordless sudo.
    include_dns=False drops the manual DNS-repair step (the cli probes and
    kicks the dispatcher hook itself at the right position).
    """
    steps = [
        Step("Pointing /etc/resolv.conf at systemd-resolved's stub", (
            "ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf",
        ), context=POST_BOOT, root=True),
        *([
            Step("Restoring DNS resolution if it is broken", (
                (f"timeout 15 getent hosts archlinux.org >/dev/null ||"
                 f" sudo {DNS_FALLBACK_WORKER}"),
            ), rationale=(
                "The installed dispatcher hook does this automatically on every network"
                " event; this is the same kick, for when resolution is broken right now."
            ), context=POST_BOOT, root=False),
        ] if include_dns else []),
        Step(f"Setting the timezone to {timezone}", (
            f"timedatectl set-timezone {_sh(timezone)}",
        ), context=POST_BOOT, root=True),
        Step(f"Generating an SSH keypair for {username}", (
            ("test -f $HOME/.ssh/id_ed25519.pub || ssh-keygen -q -t ed25519 -N ''"
             f" -f $HOME/.ssh/id_ed25519 -C {_sh(f'{username}@{hostname}')}"),
        ), rationale=(
            "First keypair for the created user (ed25519, empty passphrase); the key"
            " passed to the installer was only for initial access."
        ), context=POST_BOOT),
    ]
    if opencode:
        assert opencode_password is not None
        steps.extend([
            Step(f"Letting {username}'s services run without a login session", (
                f"loginctl enable-linger {_sh(username)}",
            ), rationale=(
                "The user manager — and with it the opencode unit — runs from boot,"
                " without an active login session."
            ), context=POST_BOOT, root=True),
            Step("Installing the opencode user service", (
                "mkdir -p ~/.config/systemd/user",
                _heredoc(f"cat > {OPENCODE_UNIT_PATH} <<'UNIT'",
                         *opencode_unit(opencode_password).splitlines(), "UNIT"),
                f"chmod 644 $HOME/{OPENCODE_UNIT_PATH}",
                "systemctl --user daemon-reload",
                "systemctl --user enable opencode.service",
                "systemctl --user start --no-block opencode.service",
            ), rationale=(
                "opencode v2 protects the server with HTTP basic auth; without"
                " OPENCODE_SERVER_PASSWORD it would generate a random password into the"
                " journal on every start. The basic-auth username is hardcoded to"
                " 'opencode' (as of 2.0.18). The start is queued with --no-block"
                " because a blocking start can hold the SSH channel open; verify with"
                " `systemctl --user is-active opencode.service`."
            ), context=POST_BOOT, id="opencode-service"),
            Step(f"Opening port {OPENCODE_PORT} in firewalld", (
                f"firewall-cmd --permanent --add-port={OPENCODE_PORT}/tcp",
                "firewall-cmd --reload",
            ), context=POST_BOOT, root=True),
        ])
    return steps


def _heredoc(start: str, *lines: str) -> str:
    return "\n".join((start, *lines))


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


def _wrapped(packages: str) -> str:
    return " \\\n    ".join(packages.split())


def _sh(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _sed_regex(locale: str) -> str:
    return locale.replace("\\", r"\\").replace(".", r"\.")
