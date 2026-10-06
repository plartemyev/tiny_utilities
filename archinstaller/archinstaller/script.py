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
pinentry pipewire pipewire-alsa pipewire-audio pipewire-pulse pipewire-v4l2
pixz plantuml
plantuml-ascii-math popt power-profiles-daemon ppp pptpclient procps-ng
protobuf psmisc pv python python-attrs python-babel python-build-backend
python-cffi python-charset-normalizer python-configobj python-cryptography
python-docker python-docutils python-idna python-imagesize python-jinja
python-jsonpatch python-jsonpointer python-jsonschema
python-jsonschema-specifications python-markupsafe python-netifaces
python-oauthlib python-packaging python-pandocfilters python-poetry
python-psycopg python-psycopg-pool python-pycparser python-pygments python-libguestfs
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
wireguard-tools wireless-regdb wireless_tools wireplumber wit
wpa_supplicant wvdial wvstreams xdg-utils xfsprogs xl2tpd xmlsec xxhash xz
yaml-language-server yarn yt-dlp zsh-autosuggestions zstd b3sum
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
open-vm-tools pavucontrol pcaudiolib peek
pycharm-community-edition qbittorrent qt6-webengine radeontop renderdoc scrcpy
sddm sdl12-compat sdl2
spice-vdagent systray-x-common telegram-desktop texlive-latexextra
texlive-latexrecommended thunderbird thunderbird-i18n-en-us thunderbird-i18n-ru
virglrenderer virt-manager virt-viewer vkmark vlc vlc-plugins-all vulkan-broadcom
vulkan-dzn vulkan-extra-tools vulkan-gfxstream vulkan-intel vulkan-radeon
vulkan-tools vulkan-virtio wine wine-gecko xarchiver xcb-proto
xorg-xprop xorg-xrandr xorg-xset xorgproto
xreader zed zvbi vulkan-mesa-layers vulkan-headers memtest_vulkan
firefox-ublock-origin gwenview
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
