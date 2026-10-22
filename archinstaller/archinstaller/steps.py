"""Single source of truth for everything archinstaller executes.

`install_steps` / `post_boot_steps` describe the run as a list of `Step`
objects; `script.py` renders them to the bash install script and
`workbook.py` renders them to a markdown workbook. Command text lives
here and nowhere else.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

_SHELL_DIR = Path(__file__).parent / "shell"


def shell_lines(name: str) -> list[str]:
    """Lines of a static shell snippet shipped in archinstaller/shell/.

    The files are kept as real .sh files (readable, shellcheck-able) and
    their content is emitted verbatim into generated scripts — keep them
    free of comments and keep their trailing newline.
    """
    return (_SHELL_DIR / name).read_text(encoding="utf-8").splitlines()


_PACKAGES_DIR = Path(__file__).parent / "packages"


def package_list(name: str) -> str:
    """Whitespace-joined package names from archinstaller/packages/<name>.txt.

    The lists live as one-package-per-line .txt files (readable, clean
    git diffs); blank lines and '#' comment lines are skipped and the
    rest is returned as a single space-joined string.
    """
    lines = (_PACKAGES_DIR / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    return " ".join(line.strip() for line in lines
                    if line.strip() and not line.lstrip().startswith("#"))

BASE_PACKAGES = package_list("base")

CONSOLE_PACKAGES = package_list("console")

# Development tooling split out of the console list; appended only with --devel
# (console-devel always; graphical-devel additionally with --graphical).
CONSOLE_DEVEL_PACKAGES = package_list("console-devel")

# Installed before SONICDE_PACKAGES: xlibre-xserver Provides: xorg-server, and
# sonic-login-manager (a sonicde-meta dependency) Requires: xorg-server — with
# the server installed first that dependency resolves to the xlibre build
# instead of pulling in the conflicting stock xorg-server.
XLIBRE_PACKAGES = package_list("xlibre")

# Installed before GRAPHICAL_PACKAGES: the sonic packages conflict with (and
# provide) the stock KDE/Plasma ones, so having them installed first makes
# pacman resolve those dependencies to the sonic replacements.
SONICDE_PACKAGES = package_list("sonicde")

GRAPHICAL_PACKAGES = package_list("graphical")

# Development tooling split out of the graphical list; appended only with
# --devel (in addition to console-devel, and only when --graphical is set).
GRAPHICAL_DEVEL_PACKAGES = package_list("graphical-devel")

IGNORE_PKG = package_list("ignore")
XLIBRE_KEY_ID = "B97F7C613F359424"
SONICDE_KEY_ID = "3B87898C73F11DF5"
# Base membership for the created user. Every group below is created by the
# sysusers.d defaults of the base meta-package's own packages (systemd:
# basic.conf — wheel, kvm, optical, uucp, video; filesystem: arch.conf —
# sys, games, scanner), so none of them can be missing. docker is appended
# only with --devel: its group is created by the docker package, which
# enters the install only through the devel lists (docker-compose/buildx
# dependencies), and useradd exits 6 on a missing group.
USER_GROUPS = "video,scanner,optical,kvm,sys,wheel,uucp,games"
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

# Installed into the new system (see the prune step below for the policy);
# prunes every cached package file and pacman's leftover download-* staging
# directories after each pacman transaction. rm, not `pacman -Scc`:
# PostTransaction hooks run while the parent transaction still holds
# /var/lib/pacman/db.lck, so the nested pacman would fail with "unable to
# lock database" on every transaction (verified on a current archlinux
# container), while plain rm needs nothing beyond coreutils. Staging dirs
# hold no resumable state: pacman >= 6.1 keeps .part files inside them and
# they do not survive the transaction anyway (only a killed pacman leaves
# one behind; the next transaction's hook run prunes it). Unmatched globs
# exit 0 through rm -f/-rf.
PACKAGE_CACHE_PRUNE_HOOK = "\n".join([
    "[Trigger]",
    "Operation = Install",
    "Operation = Upgrade",
    "Operation = Remove",
    "Type = Package",
    "Target = *",
    "",
    "[Action]",
    "Description = Pruning the pacman package cache",
    "When = PostTransaction",
    ("Exec = /usr/bin/sh -c 'rm -rf -- /var/cache/pacman/pkg/download-*"
     " /var/cache/pacman/pkg/*.pkg.tar.*'"),
]) + "\n"

# Where a step's commands run: "live" is the booted ISO environment, "chroot"
# is inside the mounted new system, "post-boot" is the installed system over
# SSH after the first reboot.
LIVE = "live"
CHROOT = "chroot"
POST_CHROOT = "post-chroot"  # live env again, after the chroot heredoc exits
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
    # --devel: append the development package lists on top of the regular
    # ones (console-devel always; graphical-devel additionally with
    # --graphical).
    devel: bool = False
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
    steps.append(
        Step("Releasing the target mounts and swap", (
            "swapoff -a 2>/dev/null || true",
            "umount -R /mnt/new-root 2>/dev/null || true",
        ), rationale=(
            "The script exits with the installed filesystem unmounted, so the"
            " host-side poweroff (clean or forced) never races a pending write;"
            " the same commands double as the pre-install cleanup at the top."
        ), context=POST_CHROOT, spaced=False),
    )
    return steps


def _partition(disk: str, number: int) -> str:
    """Partition n of disk: NVMe controllers need the 'p' name separator."""
    if re.fullmatch(r"nvme\d+n\d+", disk.rsplit("/", 1)[-1]):
        return f"{disk}p{number}"
    return f"{disk}{number}"


def _formatting_step(cfg: InstallConfig) -> Step:
    options = " -o discard" if cfg.discard and cfg.virt != "none" else ""
    return Step("Creating filesystems and mounting", (
        f"mkfs.fat -F 32 {_sh(_partition(cfg.disk, 1))}",
        f"mkfs.ext4 -F {_sh(_partition(cfg.disk, 2))}",
        f"mount --mkdir{options} {_sh(_partition(cfg.disk, 2))} /mnt/new-root",
        f"mount --mkdir {_sh(_partition(cfg.disk, 1))} /mnt/new-root/boot",
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
        *([
            Step("Reserving DRM card0 for the guest GPU (spice agent mapping)", (
                ("sed -i 's/^GRUB_CMDLINE_LINUX=.*/"
                 "GRUB_CMDLINE_LINUX=\"initcall_blacklist=sysfb_init\"/'"
                 " /etc/default/grub"),
            ), rationale=(
                "Built-in simpledrm registers DRM minor 0 at boot and is kicked off"
                " by the real GPU driver's aperture takeover afterwards, leaving the"
                " GPU as card1 with no card0. spice-vdagent enumerates cards"
                " card0..card9 but stops at the first missing index, so its"
                " server-display to X-output PCI mapping fails and the agent drops"
                " to output-index matching (single display only). Blacklisting the"
                " sysfb_init initcall stops the firmware framebuffer device from"
                " ever registering, so the GPU driver takes minor 0 = card0."
                " Must land before the grub-mkconfig in the next step."
            )),
        ] if cfg.graphical and cfg.virt in ("kvm", "qemu") else []),
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
        Step("Installing the package-cache prune hook", (
            "mkdir -p /etc/pacman.d/hooks",
            _heredoc("cat > /etc/pacman.d/hooks/90-archinstaller-prune-cache.hook <<'PRUNE'",
                     *PACKAGE_CACHE_PRUNE_HOOK.splitlines(), "PRUNE"),
        ), rationale=(
            "Empties the package cache after every pacman transaction. Arch's"
            " default keeps at least one compressed copy of every installed"
            " package in /var/cache/pacman/pkg forever (plus every downloaded"
            " version until manually cleaned); here the cache never duplicates"
            " the installed set. Deleted bytes are genuinely reclaimed through"
            " the discard handling above (continuous root discard on VMs,"
            " weekly fstrim on SSDs); on --local-mirror targets re-downloads"
            " come from the host LAN mirror. The cost is offline rollback:"
            " downgrades need the package re-fetched (the Arch archives carry"
            " the official repos; the third-party repos may not keep old"
            " versions). Plain rm instead of pacman -Scc: PostTransaction hooks"
            " run while the parent transaction still holds"
            " /var/lib/pacman/db.lck, so the nested pacman would fail with"
            " 'unable to lock database' on every run, while rm needs nothing"
            " beyond coreutils (pacman-contrib is not installed). Interrupted"
            " downloads leave nothing to resume: pacman >= 6.1 stages partial"
            " downloads under temporary download-* directories inside the"
            " cache and they do not survive the transaction; the hook clears"
            " those leftovers too (only a killed pacman leaves one behind, and"
            " the next transaction's hook run prunes it)."
        )),
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
    if cfg.devel:
        steps.append(
            Step("Installing console development packages (long step)", (
                f"retry pacman -Sy --needed --noconfirm \\\n    {_wrapped(CONSOLE_DEVEL_PACKAGES)}",
            ), rationale=(
                "Requested with --devel: compilers and SDKs, language servers,"
                " containers, CI/CD, cloud/IaC, VM host tooling, reverse"
                " engineering and security tooling on top of the console toolbox."
            )),
        )
    if cfg.opencode and not cfg.devel:
        # opencode sits in CONSOLE_DEVEL_PACKAGES; without this step
        # --opencode would still create the user unit in stage two, whose
        # ExecStart then dies with status 203/EXEC (no binary).
        steps.append(
            Step("Installing opencode (long step)", (
                "retry pacman -Sy --needed --noconfirm opencode",
            ), rationale=(
                "Requested with --opencode: the stage-two user service needs"
                " the /usr/bin/opencode binary, which otherwise only ships"
                " with --devel."
            )),
        )
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
        ])
        if cfg.devel:
            steps.append(
                Step("Installing graphical development packages (long step)", (
                    f"retry pacman -S --needed --noconfirm \\\n    {_wrapped(GRAPHICAL_DEVEL_PACKAGES)}",
                ), rationale=(
                    "Requested with --devel: VM management, graphics debugging and"
                    " benchmarks, 3D content creation, Vulkan development on top of"
                    " the graphical set."
                )),
            )
        steps.extend([
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
            f"useradd -m --groups {_user_groups(cfg)} {user}",
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
                " 'vm.vfs_cache_pressure = 20'"
                " > /etc/sysctl.d/90-small-cache.conf",
            ), rationale=(
                "The VM boots with its full RAM (current = max) and the virtio balloon"
                " returns pages to the host only when the guest notices pressure:"
                " freePageReporting hands back free-page hints and autodeflate inflates"
                " the balloon under host pressure. watermark_scale_factor = 500 wakes"
                " kswapd at 5% free memory (0.1% default) and the lowered"
                " vfs_cache_pressure makes reclaim target the page cache rather than"
                " the dentry/inode caches, keeping memory the hypervisor could reuse."
                " (The pagecache-limit sysctls are SUSE out-of-tree, not mainline.)"
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
        Step("Making the ACPI power button shut down", (
            # PowerDevil takes a block inhibitor on handle-power-key, so
            # logind's default (poweroff) never fires; the non-mobile default
            # action is the logout dialog, which stalls host-side
            # `VBoxManage controlvm acpipowerbutton` on an autologin desktop.
            # 8 = PowerDevil PowerButtonAction::Shutdown.
            # mkdir: this is the first ~/.config writer and the directory does
            # not exist after useradd -m (no skel entry; XDG dirs appear at
            # first session start only).
            f"mkdir -p {home}/.config",
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
            Step("Disabling screen locking (VM target)", (
                (f"printf '%s\\n' '[Daemon]' 'Autolock=false' 'LockOnResume=false'"
                 f" > {home}/.config/kscreenlockerrc"),
                # none,none is how kglobalaccel stores a user-cleared shortcut;
                # a missing entry would re-apply the built-in Meta+L default.
                ("printf '%s\\n' '[ksmserver]' 'Lock Session=none,none,Lock Session'"
                 f" > {home}/.config/kglobalshortcutsrc"),
            ), rationale=(
                "Meta+L muscle memory aimed at the host OS locks the VM desktop"
                " instead, and autolock or lock-on-resume can freeze unattended test"
                " runs behind a password prompt. Autolock and lock-on-resume are off"
                " and the Lock Session shortcut is cleared; physical targets keep"
                " normal locking."
            )),
        ] if cfg.virt != "none" else []),
        *([
            Step("Enabling the SPICE agent daemon (kvm/qemu target)", (
                "systemctl add-wants sockets.target spice-vdagentd.socket",
            ), rationale=(
                "spice-vdagentd.socket has no [Install] section, so nothing enables"
                " or starts it: the session agent then skips itself (its"
                " ConditionPathExists waits for the daemon's socket) and the guest"
                " loses clipboard sharing and console-resize resolution following."
                " add-wants creates the symlink `systemctl enable` refuses to; the"
                " daemon itself activates on the first session-agent connection."
                " Needs the domain's com.redhat.spice.0 spicevmc channel, which the"
                " provisioning adds."
            )),
        ] if cfg.virt in ("kvm", "qemu") else []),
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


def _user_groups(cfg: InstallConfig) -> str:
    return USER_GROUPS + (",docker" if cfg.devel else "")


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
