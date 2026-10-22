# archinstaller

Unattended Arch Linux installer. `install` drives the stock Arch ISO live
environment over SSH — or a freshly provisioned local VirtualBox/libvirt VM,
from VM creation through a rebooted, SSH-reachable system. `workbook` renders
the same run as a copy-paste markdown runbook. Both render from one step model
(`archinstaller/steps.py`), so a workbook always matches what `install` runs.

## What the finished system gives you

- **Boot that survives anything**: GRUB registered in NVRAM *and* the
  signature-less `\EFI\BOOT\BOOTX64.EFI` fallback — stale boot entries, wiped
  disk-ids and VirtualBox NVRAM resets cannot trap the boot.
- **Key-only access**: created user with passwordless sudo, your
  `--ssh-pubkey` in `authorized_keys`, sshd password authentication disabled,
  a fresh ed25519 keypair generated on the target; passwords generated and
  printed in the final summary.
- **Curated package sets** distilled from the Arch ISO: base + console
  toolbox, `--devel` development tooling, `--graphical` Xlibre + Sonic DE with
  autologin (see *Graphical installs* below).
- **TRIM done right**: per-disk probe enables `fstrim.timer`, swap discard and
  (on VMs) continuous root discard; hypervisor-side forwarding is arranged for
  you (see *TRIM/discard* below).
- **Small disk footprint**: the pacman cache is pruned after every
  transaction; optionally served by a LAN cache mirror (`--local-mirror`) so
  reinstalls are cache hits.
- **Self-healing DNS**: lease DNS servers are used while any of them answers;
  when none does, systemd-resolved's public fallbacks take over, reverting
  automatically when the network heals.
- **Sane baseline**: NetworkManager + systemd-resolved, firewalld enabled on
  every install.
- **VM-aware tuning**: guest agents per hypervisor, VirtualBox HDA fix,
  balloon-friendly memory sysctls, ACPI power button wired to a clean
  shutdown, screen locking off on VM desktops (physical machines keep it).
- **Optional opencode web server** as a systemd user service with its own
  generated password and firewalled port.

## Scenarios

```bash
poetry install   # Python >= 3.13; runtime dependency: paramiko

# fresh local desktop VM on libvirt, packages from the LAN cache mirror
poetry run archinstaller install --provision libvirt --graphical --local-mirror

# existing machine booted from the ISO (on the ISO console: passwd; note the IP)
poetry run archinstaller install --target 192.168.1.50 --graphical

# reinstall a VirtualBox VM with the host-side reboot assist
poetry run archinstaller install --target 192.168.1.51 --vbox-vm MyVM

# manual runbook instead of automation (add --provision to include VM creation)
poetry run archinstaller workbook --provision libvirt --graphical --local-mirror

# finish a previous run's post-reboot stage after an interruption
poetry run archinstaller resume archinstaller-state-<hostname>.json
```

`--provision` creates a VM named `--hostname`, boots the stock ISO and drives
it over its serial line — no target preparation at all. `--local-mirror`
points pacman at the sibling `arch-cache-mirror` container on this host (port
8282) for both the install and the installed system: repeated installs are LAN
cache hits instead of public-mirror downloads.

## Requirements

- UEFI boot, Secure Boot off (the GRUB build is unsigned).
- `--disk` is a plain `sdX`/`vdX`/`hdX` device — NVMe naming is not supported.
- The /24 fallback scan (see *Two-stage runs and recovery* below) probes 254
  addresses; use `--no-subnet-scan` where that is unwelcome (it never runs
  with a jump host or a non-IPv4 target).
- `--provision vbox`: VirtualBox on this host (Extension Pack optional, for
  USB 3.0); `--provision libvirt`: `virsh` with access to `qemu:///system`.
- `--local-mirror`: the `arch-cache-mirror` container reachable from the
  target; verified via `/healthz` before anything destructive.

## How an install proceeds

1. Connect to the live ISO as `root` (`--login-*`; optional SSH jump host;
   stale `known_hosts` entries cleared automatically).
2. Preflights on the target: UEFI check, hypervisor detection
   (`systemd-detect-virt`, or pinned with `--virt`), disk discard probe (or
   `--discard`), DNS check with a public-resolver fallback, mirror health
   check.
3. Upload and run the generated script: release stale mounts/swap from any
   previous failed run → partition (1 GiB ESP + root) → mkfs/mount → pacstrap
   → fstab → chroot: passwords, hostname/locale, GRUB (NVRAM + `--removable`
   fallback) + initramfs, pacman.conf (Color, parallel downloads, IgnorePkg
   set, multilib, `xlibre-stable` + `sonicde` repos with locally-signed
   keys), cache-prune hook, sudo, swapfile, package sets, user + key + sshd
   hardening, network services, TRIM tuning, VM tuning, firewalld, and the
   graphical configuration when enabled.
4. Reboot: from inside the guest, or host-side — `--vbox-vm` (power off,
   NVRAM store backed up, disk before DVD, start) or a provisioned run (stop
   the VM, eject the ISO, boot the disk).
5. Stage two over SSH, authenticating with the private key that matches
   `--ssh-pubkey` (literal-key runs fall back to your agent/default keys):
   wait for the target (with a /24 hostname-scan fallback), `resolv.conf`
   stub + DNS repair, timezone, user keypair, opencode service, then the
   final summary; the state file is deleted.

Guest adaptation by detected hypervisor:

| Target | Adaptation |
|---|---|
| physical | none |
| kvm / qemu | `qemu-guest-agent` enabled; graphical installs also enable the SPICE agent daemon (`spice-vdagentd.socket` has no `[Install]` section, so `systemctl add-wants` is used) |
| oracle (VirtualBox) | `virtualbox-guest-utils` (graphical) or `-nox` (console), `vboxservice` enabled, HDA `position_fix=1` pin |
| vmware | `open-vm-tools` on graphical installs |
| everything else | `hyperv` / `qemu-guest-agent` sit in the base list, inert |

Every VM target also gets `/etc/sysctl.d/90-small-cache.conf`
(`vm.watermark_scale_factor = 500`, `vm.vfs_cache_pressure = 20`): kswapd
wakes earlier and reclaims page cache in preference to the dentry/inode
caches, keeping memory available for the virtio balloon to hand back to the
host. VirtualBox targets additionally get
`options snd-hda-intel position_fix=1` — the emulated HDA's DMA position
buffer never advances, so with the default the first playback stalls the audio
graph and loops the last fragment on the host forever.

## Arguments

System configuration — shared by `install` and `workbook`:

| Argument | Default | Meaning |
|---|---|---|
| `--disk` | `/dev/vda` | disk to wipe; plain `sdX`/`vdX`/`hdX` only |
| `--hostname` | `arch-host-YYYY-MM-DD` | also names a provisioned VM |
| `--username` | `nameless` | user to create (groups: video, scanner, optical, kvm, sys, wheel, uucp, games; +docker with `--devel`) |
| `--ssh-pubkey` | `~/.ssh/id_ed25519.pub` | literal key or path to a file; validated |
| `--locale` | `en_US.UTF-8` | |
| `--swap-size` | `16G` | `/swapfile` size |
| `--timezone` | `Asia/Bangkok` | applied after first boot |
| `--root-password`, `--user-password` | generated, printed in the summary | credentials for the installed system |
| `--graphical` | off | Xlibre + Sonic DE desktop; see *Graphical installs* below |
| `--devel` | off | append the development package lists (console always; graphical too with `--graphical`) |
| `--opencode` | off | deploy the opencode web service; see *opencode service* below |
| `--local-mirror` | off | pacman via the LAN cache mirror; see *local mirror* below |
| `--virt` | probe | pin `none\|kvm\|qemu\|oracle\|vmware\|microsoft` instead of probing |
| `--discard` | probe (off in workbook mode) | force TRIM/discard enablement |

Transport — `install` only:

| Argument | Default | Meaning |
|---|---|---|
| `--target HOST` | required without `--provision` | host running the live ISO (rejected with `--provision`) |
| `--target-port` | `22` | SSH port of the target |
| `--login-user` / `--login-password` | `root` / `local0instaLl` | live ISO credentials; with `--provision` the tool sets this password over serial itself |
| `--jump-host`, `--jump-port`, `--jump-user`, `--jump-password` | — | SSH jump, like `ssh -J` (password prompted when omitted) |
| `--install-timeout` | `7200` | seconds allowed for the install script |
| `--reboot-timeout` | `900` | seconds to wait for SSH after the reboot |
| `--no-subnet-scan` | off | disable the /24 hostname fallback scan |
| `--vbox-vm NAME` | — | host-side reboot assist for an existing VirtualBox VM (+ discard flags on its disk attachments); incompatible with `--provision` |

Provisioned-VM options (`install` and `workbook` with `--provision`):

| Argument | Default | Meaning |
|---|---|---|
| `--provision` | `none` | `vbox` or `libvirt`: create a fresh VM named `--hostname` and install into it; rejects `--target`, `--jump-*`, `--vbox-vm`, `--virt` |
| `--disk-size-gib` | `45` | provisioned disk size (GiB) |
| `--ram-gib` | `4` | guest memory (GiB) |
| `--cores` | `4` | guest vCPUs |
| `--iso-path` | `~/Downloads/archlinux.iso` | must be an existing, readable `.iso`; the stock ISO is used unmodified |

Workbook-only: `--out PATH` (default `archinstaller-workbook-<hostname>.md`)
and `--with-passwords`.

## Provisioned runs (`--provision vbox|libvirt`)

Hardware provisioned per backend:

- **vbox**: UEFI, VMSVGA video (256 MB under `--graphical`, 16 MB console),
  virtio-scsi VDI attached with `--nonrotational on --discard on`, virtio-net
  on NAT with an SSH port forward `127.0.0.1:<port>` → `10.0.2.15:22` (free
  ports auto-picked in 23950–24000; the guest address is asserted over
  serial), serial port as a host TCP listener, HDA audio on the default host
  driver, UTC RTC, shared clipboard, USB 3.0 (xHCI) when the Extension Pack
  is installed.
- **libvirt** (`qemu:///system`): q35 + UEFI, `host-passthrough` CPU with
  `migratable='off'` and topology mirroring the host SMT shape, vCPUs pinned
  1:1 to the high host CPUs so sibling vCPUs of a guest core share one
  physical core (emulator pinned to the whole core just below; shared-cpuset
  fallback when the host is too small), full memory from the start with a
  virtio balloon (`freePageReporting`, `autodeflate`), qcow2 on virtio with
  `discard='unmap' detect_zeroes='unmap'`, a guest-agent channel, virtio NIC
  on the first usable network (physical bridge → `lan-routed` → default NAT),
  ICH9 HD audio via the spice backend, spice with GL under `--graphical`
  (local GL-less spice otherwise), a `com.redhat.spice.0` spicevmc agent
  channel (the guest's spice-vdagent transport: clipboard sharing and
  console-resize resolution following), TCP serial.

Boot and install flow: at the ISO's systemd-boot menu the tool blindly types
`e`, appends `console=ttyS0,115200` and boots (hypervisor keystrokes ~10 s
after start; a missed menu window is retried after a VM restart, 3 attempts).
The serial session logs in as root, sets the live root password
(`--login-password`) and reads the guest's DHCP address. The install then
runs over SSH exactly as with `--target`, with discard tuning always on
(both backends are provisioned for TRIM forwarding). Finally the tool
finalizes from the host side: stop the VM, eject the ISO, boot the installed
disk — VirtualBox flushes guest-written EFI entries on power-off, libvirt
pflash NVRAM survives destroy/start, so the installed GRUB boots directly in
both cases.

Name collisions (existing VM/domain or volume) are an error — pass another
`--hostname`. If the rebooted system is not reachable, stage two falls back
per backend: libvirt looks up the domain's DHCP lease by MAC; VirtualBox
needs nothing (the NAT port forward is fixed).

## Graphical installs (`--graphical`)

Package order is load-bearing: the Xlibre X server installs first
(`xlibre-xserver` Provides: `xorg-server`, so sonic-login-manager's
dependency resolves to the xlibre build instead of the conflicting stock
one), then `sonicde-meta` (conflicts with and provides the stock KDE/Plasma
packages, so later dependencies resolve to the sonic replacements), then the
graphical list.

The flag additionally configures:

- **sonic-login-manager** enabled with autologin for the created user; the
  session is auto-detected from the installed `.desktop` files (soniclogin
  refuses to autologin without a `Session=` entry).
- **ACPI power button shuts the machine down**: PowerDevil is seeded with the
  Shutdown action (for stacks where its button delivery works, e.g. Wayland);
  on VM targets the daemon is masked outright — its X11 button delivery is
  dead while its logind inhibitor blocks logind's default, making the button
  a no-op — so logind's `HandlePowerKey=poweroff` fires and host-side
  `acpipowerbutton` works. Physical targets keep normal locking and the
  daemon.
- **VM targets: screen locking disabled** — autolock and lock-on-resume off,
  the Meta+L Lock Session shortcut cleared, so muscle memory aimed at the
  host OS cannot lock the VM.
- **VirtualBox targets**: the full `virtualbox-guest-utils` (X11/Wayland
  integration) replaces the headless `-nox` build.

## TRIM/discard

Probed per target disk in the live environment (`discard_max_bytes > 0`;
rotational is reported for context only). Discard-capable → `fstrim.timer`
(weekly batch), the swapfile fstab entry gains `discard`, and VM targets
additionally mount root with continuous `discard` (genfstab persists it) so
freed extents unmap the hypervisor-side image at once. Not capable → nothing
is enabled.

- `--discard` forces this on without probing; workbook mode defaults to off.
- `--vbox-vm` re-attaches every hard-disk attachment with
  `--discard on --nonrotational on` host-side while the VM is powered off —
  VirtualBox shrinks a VDI in response to guest TRIM only with these flags.
  The flags land after the probe, so the guest is configured for discard
  regardless of the probe result; a failed flip only warns (e.g. IDE-attached
  disks cannot forward TRIM). Without `--vbox-vm`, set the two flags on the
  attachment yourself (VM Storage settings).
- Provisioned libvirt domains carry `discard='unmap' detect_zeroes='unmap'`.
  For your own libvirt domains: virtio-blk advertises discard out of the box;
  current stacks (libvirt ≥ 12.7.0 with QEMU ≥ 11.1.1) forward it in all
  modes unless the disk XML opts out with `discard='ignore'`, older stacks
  need the explicit `<driver ... discard='unmap'/>`. `detect_zeroes='unmap'`
  additionally compacts zero-heavy writes (such as a reinstall's fresh mkfs)
  live. Nothing needs re-running when forwarding appears — the enabled guest
  config starts unmapping on its next pass.

## Local package cache mirror (`--local-mirror`)

The sibling `arch-cache-mirror` container on the host running this tool
(published port `8282`) becomes the **only** pacman source for the live
environment and the installed system: the mirrorlist is replaced with a
single `Server = http://<mirror-host>:8282/$repo/os/$arch` line, and the
extra repos are rewritten to the mirror's own repo segments
(`/xlibre/os/$arch`, `/sonicde/os/$arch` — pacman requests the database named
after the pacman.conf section, so these cannot reuse the mirrorlist's `$repo`
template). Signing keys still come from their upstream `.asc` homes.

The mirror host is the guest's default gateway for VM targets (the hypervisor
host, static per backend — the URL survives host network roams) and the
host's primary-interface IPv4 for physical targets. Reachability is verified
via `/healthz` before anything destructive; there is no public fallback, so a
mirror that dies mid-install fails the install.

## opencode service (`--opencode`)

After the first boot the tool enables `loginctl enable-linger` for the user,
installs `~/.config/systemd/user/opencode.service` running
`opencode serve --hostname 0.0.0.0 --port 49374` with a separately generated
`OPENCODE_SERVER_PASSWORD`, starts it (`--no-block` + `is-active` polling) and
opens the port in firewalld. opencode v2 protects the server with HTTP basic
auth and hardcodes the username to `opencode`; the summary prints the web
address, username and password.

## Workbook (`workbook`)

Renders the identical run — provisioning (optional), partitioning, chroot
configuration, post-boot steps — as numbered markdown sections with rationale
and copy-paste blocks; the install script's `retry` helper is unwrapped so
every block runs standalone.

It shares the system-configuration arguments with `install` and needs no
target: the two probe-derived facts are pinned by flags (defaults
`--virt none`, no discard) and verified by a rendered "Target facts" step 0 —
re-render with matching `--virt`/`--discard` when the machine disagrees.
With `--provision vbox|libvirt` the workbook instead renders the backend's
exact commands and domain XML (host facts like free ports, machine folder and
libvirt network are probed at render time) plus manual replacements for the
automated boot/serial session.

Passwords render as `{{ROOT_PASSWORD}}`-style placeholders so the file stays
shareable. `--with-passwords` embeds explicit values and generates the
missing ones: the file is written with mode `0600`, carries a caution header,
and the generated passwords are printed to stdout once — treat the file as a
secret and rotate the passwords when convenient.

## Two-stage runs and recovery

The install and the post-boot configuration are two stages. Before the reboot
the tool writes `archinstaller-state-<hostname>.json` (mode `0600` — it holds
the passwords) into the working directory and deletes it once stage two
completes.

If the rebooted target does not answer within `--reboot-timeout`, the tool
scans the surrounding /24 for an SSH host that authenticates with the install
key and reports the configured hostname (disabled by `--no-subnet-scan`;
never runs with a jump host or a non-IPv4 target). If that fails too,
recovery steps are printed and the tool exits non-zero, keeping the state
file. Once the machine is reachable again (at any address):

```bash
poetry run archinstaller resume archinstaller-state-<hostname>.json
```

VirtualBox note behind `--vbox-vm` (and provisioned runs): boot entries the
guest writes survive power-off only — a guest-initiated reboot loses them,
and a stale `BootOrder` can trap the machine in the firmware UI. Rebooting
from the host lets the ESP fallback bootloader bring the installed system up
directly: the power-off flushes NVRAM (with `--vbox-vm` the store is also
backed up for fresh firmware defaults and the disk is ordered before the
DVD).

## Test

```bash
poetry run pytest
```
