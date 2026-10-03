from __future__ import annotations

import dataclasses

BASE_PACKAGES = """
acl acpid alsa-firmware alsa-lib alsa-topology-conf alsa-ucm-conf alsa-utils
amd-ucode arch-install-scripts archinstall archlinux-keyring argon2 attr audit
aws-cli-v2 b43-fwcutter base bash bash-completion bc bcachefs-tools bind
binutils bluez-libs bolt btrfs-progs bzip2 ca-certificates
ca-certificates-mozilla ca-certificates-utils ccid cifs-utils clamav clonezilla
cloud-init coreutils cryptsetup curl db5.3 dbus dbus-broker dbus-broker-units
dbus-units ddrescue device-mapper dhclient dhcpcd diffutils ding-libs dmidecode
dmraid dnsmasq dnssec-anchors dosfstools drbl duktape e2fsprogs ecryptfs-utils
edk2-shell efibootmgr efivar ell ethtool exfatprogs expat f2fs-tools fatresize
file filesystem findutils flac flex foot-terminfo fsarchiver fuse-common fuse2
fuse3 gawk gcc-libs gdbm gettext glib2 glibc glibc-locales gmp gnupg gnutls
gpart gpgme gpm gptfdisk grep grml-zsh-config groff grub gssproxy guestfs-tools
gzip hdparm hicolor-icon-theme hidapi htop hwdata hyperv iana-etc icu iftop
inetutils intel-ucode iotop iproute2 iptables iputils irssi iw iwd jansson
jemalloc jfsutils json-c kbd keyutils kitty-terminfo kmod krb5 lame lbzip2 ldns
less lftp libaio libarchive libassuan libasyncns libbpf libbsd libcap libcap-ng
libcbor libdnet libedit libelf libevent libffi libfido2 libgcrypt libgpg-error
libgudev libimobiledevice libimobiledevice-glue libinih libjpeg-turbo libksba
libldap liblouis libmaxminddb libmbim libmd libmspack libnetfilter_conntrack
libnewt libnfnetlink libnftnl libnghttp2 libnghttp3 libnl libnsl libnss_nis
libnvme libogg libotr libp11-kit libpcap libpipeline libplist libproxy libpsl
libqmi libqrtr-glib libsamplerate libsasl libseccomp libsecret libsigc++
libsndfile libsodium libsonic libspeechd libssh2 libsysprof-capture libtasn1
libtirpc libtool libunistring libunrar liburcu liburing libutempter libuv
libverto libvorbis libwbclient libxcrypt libxml2 libxslt libyaml libzip
licenses linux linux-api-headers linux-atm linux-firmware linux-firmware-intel
linux-firmware-marvell linux-firmware-whence livecd-sounds lmdb lrzip
lsb-release lsscsi lua lvm2 lynx lz4 lzo lzop m4 man-db man-pages mc mdadm
memtest86+ memtest86+-efi mkinitcpio mkinitcpio-archiso mkinitcpio-busybox
mkinitcpio-nfs-utils mobile-broadband-provider-info modemmanager mpdecimal mpfr
mpg123 mtools mtr nano nbd ncurses ndisc6 nettle networkmanager nfs-utils
nfsidmap nftables nilfs-utils nmap npth nspr nss nss-mdns ntfs-3g numactl
nvme-cli oath-toolkit open-iscsi open-isns openbsd-netcat openconnect
openpgp-card-tools openssh openssl openvpn opus p11-kit pacman pacman-contrib
pacman-mirrorlist pam pambase partclone parted partimage pbzip2 pciutils pcre
pcre2 pcsclite perl pigz pinentry pixz popt ppp pptpclient procps-ng psmisc pv
python python-attrs python-babel python-cffi python-charset-normalizer
python-configobj python-cryptography python-docutils python-idna
python-imagesize python-jinja python-jsonpatch python-jsonpointer
python-jsonschema python-jsonschema-specifications python-markupsafe
python-netifaces python-oauthlib python-packaging python-pycparser
python-pygments python-pyparted python-pyserial python-pytz python-referencing
python-requests python-rpds-py python-six python-snowballstemmer python-sphinx
python-sphinx-alabaster-theme python-sphinx_rtd_theme
python-sphinxcontrib-applehelp python-sphinxcontrib-devhelp
python-sphinxcontrib-htmlhelp python-sphinxcontrib-jquery
python-sphinxcontrib-jsmath python-sphinxcontrib-qthelp
python-sphinxcontrib-serializinghtml python-typing_extensions python-urllib3
python-yaml qemu-guest-agent readline refind reflector rp-pppoe rpcbind rsync
run-parts rxvt-unicode-terminfo screen sdparm sed sequoia-sq sg3_utils shadow
slang smartmontools smbclient smbnetfs sof-firmware sqlite squashfs-tools
ssh-tools sshfs stoken sudo sysfsutils syslinux systemd systemd-libs
systemd-resolvconf systemd-sysvcompat talloc tar tcl tcpdump terminus-font
terraform terragrunt testdisk tflint thin-provisioning-tools tmux tpm2-tools
tpm2-tss traceroute ttf-fira-code ttf-fira-mono ttf-fira-sans tzdata udftools
udisks2 unrar unzip uriparser usb_modeswitch usbmuxd usbutils util-linux
util-linux-libs vim vim-runtime virtualbox-guest-utils-nox vpnc which
wireguard-tools wireless-regdb wireless_tools wpa_supplicant wvdial wvstreams
xdg-utils xfsprogs xl2tpd xmlsec xxhash xz zlib zsh zsh-autosuggestions zstd
"""

CONSOLE_PACKAGES = """
7zip acl acpid adwaita-cursors adwaita-icon-theme alsa-firmware alsa-lib
alsa-topology-conf alsa-ucm-conf alsa-utils amd-ucode android-tools android-udev
arch-install-scripts archinstall archlinux-keyring argon2 aribb24 aribb25 aspell
aspell-en aspell-ru attr audit b43-fwcutter base base-devel bash bash-completion
bash-language-server bc bcachefs-tools bind binutils blendr bluez bluez-libs
bluez-tools bluez-utils bolt btrfs-progs bzip2 ca-certificates
ca-certificates-mozilla ca-certificates-utils ccid cfr cifs-utils clamav clang
clonezilla cloud-init container-diff corepack coreutils cryptsetup curl db5.3
dbus dbus-broker dbus-broker-units dbus-units ddrescue device-mapper dhclient
dhcpcd diffutils ding-libs dive dmidecode dmraid dnsmasq dnssec-anchors
dosfstools docker-compose docker-buildx drbl drone-cli drone-runner-docker
duktape e2fsprogs ecryptfs-utils
edk2-aarch64 edk2-ovmf edk2-shell efibootmgr efivar ell ethtool evtest
exfatprogs expat f2fs-tools fatresize file filesystem findutils flac flex
foot-terminfo fsarchiver fuse-common fuse2 fuse3 gawk gcc-libs gdbm gettext git
git-lfs git-repair glib2 glibc glibc-locales gmp gnupg gnutls gopls gpart gpgme
gpm gptfdisk grep grml-zsh-config groff grub gssproxy guestfs-tools gzip hdparm
hicolor-icon-theme hidapi htop hwdata hyperv iana-etc icu iftop imvirt
inetutils intel-ucode iotop iproute2 iptables iputils irssi iso-codes iw iwd
jadx jansson jdk-openjdk jedi-language-server jemalloc jfsutils json-c kbd
keyutils kitty-terminfo kmod kompose krb5 lame lbzip2 ldns less lftp libaemu
libaio libarchive libassuan libasyncns libbpf libbsd libcap libcap-ng libcbor
libcdio libcdr libdc1394 libdnet libdvdcss libdvdnav libdvdread libedit libelf
libevent libffi libfido2 libgcrypt libgme libgpg-error libgudev libguestfs
libimobiledevice libimobiledevice-glue libinih libjpeg-turbo libkate libksba
libldap liblockfile liblouis libmaxminddb libmbim libmd libmicrodns libmirage
libmspack libmtp libnetfilter_conntrack libnewt libnfnetlink libnfs libnftnl
libnghttp2 libnghttp3 libnl libnsl libnss_nis libnvme libp11-kit libpcap
libpipeline libplist libproxy libpsl libqmi libqrtr-glib libsamplerate libsasl
libseccomp libsecret libsigc++ libsndfile libsodium libsonic libspeechd libssh2
libsysprof-capture libtasn1 libtirpc libtool libunistring libunrar liburcu
liburing libutempter libuv libverto libvirt libvirt-dbus libvirt-python libvorbis
libwbclient libxcrypt libxml2 libxslt libyaml libzip licenses linux
linux-api-headers linux-atm linux-firmware linux-firmware-marvell
linux-firmware-whence live-media livecd-sounds lmdb lrzip lsb-release lsscsi lua
lua-language-server lua-socket lvm2 lynx lz4 lzo lzop m4 man-db man-pages mc
mdadm memtest86+ memtest86+-efi mkinitcpio mkinitcpio-archiso
mkinitcpio-busybox mkinitcpio-nfs-utils mobile-broadband-provider-info
modemmanager mpdecimal mpfr mpg123 mtools mtr nano nbd ncurses ndisc6 nettle
networkmanager nfs-utils nfsidmap nftables nilfs-utils nmap nodejs npm npth nspr
nss nss-mdns ntfs-3g numactl nvme-cli nvtop oath-toolkit open-iscsi open-isns
openbsd-netcat openconnect opencode openjdk-doc openpgp-card-tools openssh openssl
openvpn opus osinfo-db otf-fira-mono otf-fira-sans p11-kit pacman pacman-contrib
pacman-mirrorlist pam pambase pandoc-cli pandoc-crossref pandoc-plot partclone
parted partimage passff-host pbzip2 pciutils pcre pcre2 pcsclite perl pigz
pinentry pipewire-alsa pipewire-audio pipewire-v4l2 pixz plantuml
plantuml-ascii-math popt power-profiles-daemon ppp pptpclient procps-ng
protobuf psmisc pv python python-attrs python-babel python-build-backend
python-cffi python-charset-normalizer python-configobj python-cryptography
python-docker python-docutils python-idna python-imagesize python-jinja
python-jsonpatch python-jsonpointer python-jsonschema
python-jsonschema-specifications python-markupsafe python-netifaces
python-oauthlib python-packaging python-pandocfilters python-poetry
python-psycopg python-psycopg-pool python-pycparser python-pygments
python-pypandoc python-pyparted python-pyserial python-pytest-ruff python-pytz
python-referencing python-requests python-rpds-py python-ruff python-ruff-api
python-six python-snowballstemmer python-sphinx python-sphinx-alabaster-theme
python-sphinx_rtd_theme python-sphinxcontrib-applehelp
python-sphinxcontrib-devhelp python-sphinxcontrib-htmlhelp
python-sphinxcontrib-jquery python-sphinxcontrib-jsmath
python-sphinxcontrib-qthelp python-sphinxcontrib-serializinghtml
python-typing_extensions python-urllib3 python-yaml qemu-audio-pipewire
qemu-block-nfs qemu-docs qemu-guest-agent qemu-user-static
qemu-user-static-binfmt read-edid readline refind reflector repo rp-pppoe
rpcbind rsync run-parts rust-analyzer rxvt-unicode-terminfo screen sdl_image
sdparm sed sequoia-sq sg3_utils shadow slang smartmontools smbclient smbnetfs
squashfs-tools ssh-tools sshfs stoken sudo sysfsutils syslinux systemd
systemd-libs systemd-resolvconf systemd-sysvcompat talloc tar tcl tcpdump
terminus-font testdisk thin-provisioning-tools tmux tpm2-tools tpm2-tss
traceroute ttf-dejavu ttf-droid ttf-fira-mono ttf-fira-sans ttf-liberation
tzdata udftools udisks2 unrar unzip uriparser usb_modeswitch usbmuxd usbutils
util-linux util-linux-libs uv vcdimager vim vim-runtime virt-firmware
virt-install virt-what virtualbox-guest-utils-nox vkd3d vpnc which
wireguard-tools wireless-regdb wireless_tools wit
wpa_supplicant wvdial wvstreams xdg-utils xfsprogs xl2tpd xmlsec xxhash xz
yaml-language-server yarn yt-dlp zsh-autosuggestions zstd
"""

# Installed before SONICDE_PACKAGES: xlibre-xserver Provides: xorg-server, and
# sonic-login-manager (a sonicde-meta dependency) Requires: xorg-server — with
# the server installed first that dependency resolves to the xlibre build
# instead of pulling in the conflicting stock xorg-server.
XLIBRE_PACKAGES = """
xlibre-input-evdev xlibre-input-libinput xlibre-input-wacom xlibre-meta
xlibre-video-amdgpu xlibre-video-ati xlibre-video-qxl xlibre-xserver
"""

# Installed before GRAPHICAL_PACKAGES: the sonic packages conflict with (and
# provide) the stock KDE/Plasma ones, so having them installed first makes
# pacman resolve those dependencies to the sonic replacements.
SONICDE_PACKAGES = """
sonicde-meta sonic-ecco sonic-win sonic-workspace
"""

GRAPHICAL_PACKAGES = """
audacious audacious-plugins audacity blender brltty cdrdao chromium colord-gtk
dleyna sonic-ecco dolphin-plugins espeak-ng espeakup ffmpeg filelight firefox
firefox-i18n-en-ca firefox-i18n-ru firefox-spell-ru fluidsynth gameconqueror
gimp graphviz gst-libav gst-plugin-dav1d gst-plugin-rav1e guvcview-qt
intel-media-driver joyutils kate kgraphviewer lib32-libva lib32-mesa libcanberra
libpulse libreoffice-fresh-ru libsm libtiger libva libva-utils libvdpau-va-gl
libx11 libxau libxcb libxdmcp libxext libxmu libxss libxt mesa-utils
modem-manager-gui mono mono-msbuild mono-msbuild-sdkresolver
network-manager-applet networkmanager-openconnect nm-connection-editor okular
open-vm-tools pavucontrol pcaudiolib peek pipewire-pulse
pycharm-community-edition qbittorrent qt6-webengine radeontop renderdoc scrcpy
sddm sdl12-compat sdl2
spice-vdagent systray-x-common telegram-desktop texlive-latexextra
texlive-latexrecommended thunderbird thunderbird-i18n-en-us thunderbird-i18n-ru
virglrenderer virt-manager virt-viewer vkmark vlc vlc-plugins-all vulkan-broadcom
vulkan-dzn vulkan-extra-tools vulkan-gfxstream vulkan-intel vulkan-radeon
vulkan-tools vulkan-virtio wine wine-gecko xarchiver xcb-proto
xfce4-clipman-plugin xorg-xprop xorg-xrandr xorg-xset xorgproto
xreader zed zvbi vulkan-mesa-layers vulkan-headers memtest_vulkan
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


def build_install_script(cfg: InstallConfig) -> str:
    return "\n".join([
        _header(),
        _partitioning(cfg.disk),
        _formatting(cfg.disk),
        _pacstrap(cfg),
        _fstab(),
        _chroot(cfg),
    ])


def _header() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        "log() { printf '\\n===== %s =====\\n' \"$*\"; }\n"
    )


def _partitioning(disk: str) -> str:
    return (
        f"log 'Partitioning {disk} (1G ESP + rest for root)'\n"
        f"wipefs -af {_sh(disk)}\n"
        f"sfdisk {_sh(disk)} <<'SFDISK'\n"
        "label: dos\n"
        ",1G,0xef\n"
        ",,\n"
        "SFDISK\n"
    )


def _formatting(disk: str) -> str:
    return (
        "log 'Creating filesystems and mounting'\n"
        f"mkfs.fat -F 32 {_sh(disk + '1')}\n"
        f"mkfs.ext4 -F {_sh(disk + '2')}\n"
        f"mount --mkdir {_sh(disk + '2')} /mnt/new-root\n"
        f"mount --mkdir {_sh(disk + '1')} /mnt/new-root/boot\n"
    )


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


def _fstab() -> str:
    return (
        "log 'Generating /etc/fstab'\n"
        "genfstab -U /mnt/new-root >> /mnt/new-root/etc/fstab\n"
    )


def _chroot(cfg: InstallConfig) -> str:
    user = _sh(cfg.username)
    home = f"/home/{cfg.username}"
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
        "cat >> /etc/pacman.conf <<'REPOS'",
        "",
        "[xlibre-stable]",
        "Server = https://packages.xlibre.net/arch/stable/$arch",
        "",
        "[sonicde]",
        "Server = https://sonicde-arch.github.io/$arch",
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
        "printf '%s\\n' '/swapfile none swap defaults 0 0' >> /etc/fstab",
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
            "log 'Enabling SDDM display manager'",
            "systemctl enable sddm",
            "",
            f"log 'Enabling SDDM autologin for {cfg.username}'",
            "mkdir -p /etc/sddm.conf.d",
            ("session=$(find /usr/share/xsessions /usr/share/wayland-sessions"
             " -maxdepth 1 -name '*.desktop' 2>/dev/null | sort | head -n 1)"),
            "if [ -z \"$session\" ]; then",
            "    echo 'no session desktop files found' >&2",
            "    exit 1",
            "fi",
            "session_name=$(basename \"$session\")",
            (f"printf '%s\\n' '[Autologin]' 'User={cfg.username}'"
             " \"Session=$session_name\""
             " > /etc/sddm.conf.d/10-archinstaller.conf"),
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
