# archinstaller

Automated, unattended Arch Linux installation driven over SSH into the
Arch ISO live environment. It replicates the manual install draft
(partitioning, pacstrap, GRUB, pacman.conf tuning, third-party repos,
user creation), reboots the machine, generates a fresh SSH keypair for
the created user and prints a summary.

## Prepare the live ISO

Boot the target (physical machine or VM) from the Arch ISO in **UEFI
mode** with **Secure Boot disabled** — the install registers GRUB for
`x86_64-efi` and needs an ESP; the tool verifies this on the target
before touching the disk. Then, on the Arch ISO console:

```bash
passwd              # set the live environment root password
systemctl start sshd
ip a                # note the address to pass as --target
```

### Supported targets

The tool is target-agnostic: anything that boots the Arch ISO in UEFI
mode and serves SSH works. It detects the hypervisor on the target with
`systemd-detect-virt` and adapts the guest agents:

| Target | Behavior |
|---|---|
| Physical computer | nothing special; real NVRAM persists boot entries, so the plain post-install reboot works; VirtualBox guest utils are skipped |
| libvirt / KVM / QEMU VM | `qemu-guest-agent` is installed and enabled; OVMF pflash NVRAM persists boot entries, so the plain reboot works; no `--vbox-vm` equivalent needed |
| VirtualBox VM | `virtualbox-guest-utils` (graphical) or `-nox` (console) is installed and `vboxservice` is enabled (without it the host never sends video-mode hints and `VBoxClient --vmsvga` blanks the screen after login — see the hypervisor bullet in the deviations below); use `--vbox-vm` for the host-side reboot — guest-written EFI boot entries do not survive a guest reboot there (see below) |
| Other (Hyper-V, VMware, ...) | detected and reported; `open-vm-tools` is installed only on VMware graphical installs; the base lists already carry `qemu-guest-agent` and Hyper-V daemons (inert where unused) |

Requirements for every target:

* UEFI boot, Secure Boot off (the GRUB build is unsigned);
* `--disk` is a plain `sdX`/`vdX`/`hdX` device — NVMe naming
  (`nvme0n1`) is not supported;
* for the /24 fallback scan, a literal IPv4 `--target` on a subnet you
  are allowed to probe (disable with `--no-subnet-scan`; a jump-host
  run never scans).

## Usage

```bash
poetry install
poetry run archinstaller \
    --target 192.168.122.X \
    [--jump-host 192.168.1.35 --jump-user root] \
    [--disk /dev/vda] \
    [--hostname arch-host-2026-09-06] \
    [--username nameless] \
    --ssh-pubkey 'ssh-ed25519 AAAA... comment'   # or a path: --ssh-pubkey ~/.ssh/id_ed25519.pub \
    [--locale en_US.UTF-8] [--swap-size 16G] \
    [--graphical] [--opencode]
```

Password handling:

* `--login-password` defaults to `local0instaLl` (only used briefly on
  the live ISO; override with the flag if your ISO password differs).
* `--root-password` / `--user-password` are optional: if omitted, a
  random 10-character alphanumeric password is generated and printed in
  the final summary block (deferred to the end so it cannot scroll out
  of the console buffer).
* `--jump-password` is still prompted for when a jump host is used.

After the user is created (with the provided public key in
`authorized_keys`), sshd password authentication is disabled on the
installed system, so post-reboot access is public-key only. The created
user can `sudo` without a password prompt
(`/etc/sudoers.d/20-archinstaller`: `NOPASSWD: ALL`).

Host key changes after a reinstall are handled automatically: stale
`known_hosts` entries for the target are removed (`ssh-keygen -R`)
before connecting.

### Arguments

| Argument | Default | Meaning |
|---|---|---|
| `--target HOST` | required | host running the live ISO |
| `--target-port` | `22` | SSH port of the target |
| `--login-user` / `--login-password` | `root` / `local0instaLl` | live ISO credentials |
| `--jump-host`, `--jump-port`, `--jump-user`, `--jump-password` | none | optional SSH jump (like `ssh -J`) |
| `--disk` | `/dev/vda` | disk to wipe; must be a plain `sdX`/`vdX`/`hdX` device (no NVMe naming) |
| `--hostname` | `arch-host-YYYY-MM-DD` (script run date) | hostname for the new system |
| `--username` | `nameless` | user account to create (groups: video, scanner, optical, kvm, sys, wheel, uucp, games, docker) |
| `--ssh-pubkey` | required | ssh public key as a literal string **or** a path to a file containing one; validated (known key type + decodable base64 blob) |
| `--locale` | `en_US.UTF-8` | system locale (must be `<lang>_<region>.UTF-8`) |
| `--swap-size` | `16G` | size of `/swapfile` |
| `--root-password`, `--user-password` | generated (printed in the final summary) | credentials for the installed system |
| `--timezone` | `Asia/Bangkok` | timezone set on the installed system via `timedatectl set-timezone` after first boot |
| `--graphical` | off | console-only package list by default; with the flag the Xlibre X server stack is installed first, then the Sonic DE base (`sonicde-meta`, `sonic-ecco`, `sonic-win`, `sonic-workspace`), then the graphical packages (this order makes the `xorg-server` and KDE/Plasma dependencies resolve to their xlibre/sonic replacements instead of conflicting), the SDDM desktop session is installed with autologin for the created user (`/etc/sddm.conf.d/10-archinstaller.conf`; the `Session=` entry is auto-detected from the installed session desktop files — SDDM refuses to autologin without it), and on VirtualBox targets the full `virtualbox-guest-utils` (X11/Wayland integration) replaces the headless `virtualbox-guest-utils-nox` (non-VirtualBox targets install neither) |
| `--opencode` | off | additionally deploy the opencode web server as a systemd **user** service on port `49374` (opens the port in firewalld; see below) |
| `--install-timeout` | `7200` | seconds allowed for the whole install script |
| `--reboot-timeout` | `900` | seconds to wait for SSH after reboot |
| `--no-subnet-scan` | off | if the rebooted target does not answer at `--target` in time, the tool scans the surrounding /24 (TCP 22 probe of the 254 host addresses, then a key-authenticated SSH login) for the machine reporting the configured hostname and continues at that address; this flag disables the fallback |
| `--vbox-vm NAME` | none | VirtualBox VM name for a **host-side** reboot: clean power-off, NVRAM store backed up to `.nvram.bak` (fresh firmware defaults on next boot), boot order disk-before-DVD, start — makes the first boot work out of the box (see below) |
| `--resume STATE_FILE` | none | skip the install; finish a previous run's post-reboot stage from its state file (all other arguments ignored) |

### Output

The final summary block (printed at the very end, after the first
boot) lists the generated root/user passwords (only those that were
generated), the target's private IP(s), public IP, created user name
and the **newly generated** user SSH public
key (an `ed25519` keypair is created on the target after the first boot;
the key passed via `--ssh-pubkey` is only used for initial access).

With `--opencode` the summary additionally lists the opencode web
address (`http://<target>:49374`), the connection username (`opencode`)
and its separately generated password.

### opencode web service (`--opencode`)

After the first boot the tool additionally:

* runs `loginctl enable-linger <username>` (via passwordless sudo) so
  the user manager — and the service — run without an active login
  session;
* installs `~/.config/systemd/user/opencode.service` running
  `opencode serve --hostname 0.0.0.0 --port 49374` and enables/starts
  it (`systemctl --user daemon-reload`, `systemctl --user enable --now`);
* sets the server password through `OPENCODE_SERVER_PASSWORD` in the
  unit: always a separate generated 10-character alphanumeric password,
  independent of `--user-password` (opencode v2 protects the server
  with HTTP basic auth; without the variable it would generate a random
  password into the journal on every start);
* starts the unit with `systemctl --user enable` +
  `start --no-block` and then polls `is-active` until it reports
  `active` — a blocking `systemctl --user start` can occasionally hold
  the SSH channel open until the read timeout (observed once on first
  start); the poll also verifies the service actually came up;
* opens the port: `firewall-cmd --permanent --add-port=49374/tcp` +
  `firewall-cmd --reload` (firewalld itself is installed and enabled
  in the basic setup of every install — see the deviations list).

Username note: opencode v2 (as of 2.0.18, the current Arch package)
hardcodes the HTTP basic-auth username to `opencode` —
`OPENCODE_SERVER_USERNAME` is ignored and `opencode service set
username ...` is rejected as an unknown key — so the summary reports
`opencode` as the connection username. Newer opencode builds honour
`OPENCODE_SERVER_USERNAME` if a custom username is ever wanted.

### Two-stage runs (`--resume`) and VirtualBox (`--vbox-vm`)

The install and the post-boot configuration are two stages. Before the
reboot the tool writes `archinstaller-state-<hostname>.json` (mode
0600 — it holds the generated passwords) into the working directory.
Normally the tool finishes stage two itself: wait for SSH at
`--target`, fall back to the /24 hostname scan, then apply the timezone,
`resolv.conf`, user key and opencode service, print the summary, and
delete the state file. If the machine does not come back, the tool
prints recovery steps and exits non-zero, keeping the state file; once
the machine is reachable again (at any address), run:

```bash
poetry run archinstaller --resume archinstaller-state-<hostname>.json
```

Verified VirtualBox EFI behavior behind `--vbox-vm`: boot entries the
guest writes (what `grub-install`'s efibootmgr does) do **not** survive
a guest-initiated reboot — the NVRAM store is only flushed on power-off
— so a reinstall leaves a stale `BootOrder` (old GRUB entry pointing at
a wiped disk-id, `UiApp` boot manager in front of the disk) that traps
the machine in the firmware UI even though the fallback
`\EFI\BOOT\BOOTX64.EFI` is bootable. With `--vbox-vm NAME` the tool
reboots from the host instead of inside the guest: clean power-off,
`<vm>.nvram` renamed to `<vm>.nvram.bak` (fresh firmware defaults), boot
order changed to disk-before-DVD, VM started. The machine then boots the
ESP fallback directly — out of the box, with the install ISO still
attached. The one cost: boot entries previously registered in that VM's
NVRAM are gone (only the firmware defaults remain).

## Deviations from the manual draft

* `fdisk` dialog → scripted `sfdisk` (MBR: 1G ESP type `0xef` + rest root),
  same layout as the draft.
* `grub-install` runs twice: once normally (registers the `GRUB` boot entry
  in UEFI NVRAM) and once with `--removable` (installs the fallback
  `\EFI\BOOT\BOOTX64.EFI`). NVRAM entries alone proved unreliable for a
  wiping installer: `sfdisk` randomizes the MBR disk-id on every run, so
  entries left over from a previous install stop resolving, and VirtualBox
  EFI loses guest-written boot entries across guest-initiated reboots (the
  NVRAM store is flushed only on power-off). The removable-path fallback
  carries no signature and boots via the firmware's plain hard-disk option.
  **VirtualBox note:** without `--vbox-vm` (see "Two-stage runs and
  VirtualBox" above) detach the ISO or order the HDD before the DVD
  yourself before the installer reboots, otherwise the still-attached
  ISO wins the boot and the machine comes back into the live
  environment; a stale EFI BootOrder can still trap the boot in the
  firmware UI, in which case follow the printed recovery steps and
  finish with `--resume`.
* After the reboot the tool waits at `--target`; on timeout it scans the
  surrounding /24 for the machine (automatic for literal IPv4 targets
  without a jump host, disable with `--no-subnet-scan`). Motivation: the
  archiso identifies DHCP clients with a systemd DUID derived from a
  transient machine-id, and the VirtualBox host-only DHCP server keys
  leases by client-id (not MAC), so every ISO boot looks like a new client
  and gets the next pool address. The installed NetworkManager system
  defaults to a MAC-based client-id, so its address is stable across
  reboots — but the first boot after the install can still land on a
  different address than `--target`. The scan probes port 22 on the 254
  usable addresses of the /24 and verifies the configured hostname over a
  key-authenticated SSH connection, so it never mistakes another machine
  for the target.
* `pacman` runs use `--noconfirm` / `--needed` (non-interactive).
* `passwd` / `EDITOR=vim visudo` → `chpasswd` and direct
  `/etc/sudoers.d/10-wheel` (mode `0440`) plus a passwordless-sudo rule
  for the created user (`/etc/sudoers.d/20-archinstaller`, mode `0440`).
* `/etc/pacman.conf` edits (Color, `ParallelDownloads = 10`, `IgnorePkg`,
  Multilib, `[xlibre-stable]` + `[sonicde]` repos, key signing) done with
  `sed` and heredocs; only the repo signing keys (`B97F7C613F359424`,
  `3B87898C73F11DF5`) are imported from the `.asc` files over HTTPS —
  no keyserver access is needed. The `#Include` uncommenting for Multilib is scoped to
  the `[multilib]` section so no stray `mirrorlist` include lands inside
  `[options]`.
* The graphical install runs in three pacman transactions, in this order:
  the Xlibre X server stack, then the Sonic DE base (`sonicde-meta`,
  `sonic-ecco`, `sonic-win`, `sonic-workspace`), then the graphical packages.
  The ordering is load-bearing: `xlibre-xserver` provides `xorg-server`, and
  `sonic-login-manager` (a `sonicde-meta` dependency) as well as `sddm`
  require `xorg-server` — with the xlibre server installed first those
  dependencies resolve to the xlibre build instead of pulling in the
  conflicting stock `xorg-server`. The sonic packages likewise conflict with
  (and provide) the stock KDE/Plasma libraries, so installing them before the
  graphical apps lets pacman resolve the `k*` dependencies to the sonic
  replacements without "removing ... because it conflicts" warnings.
  `dolphin` is requested as `sonic-ecco` (it provides `dolphin`, so
  `dolphin-plugins` still installs); `sonic-x11-session` is dropped (removed
  from the repo, replaced by `sonic-workspace`).
* The hypervisor is detected on the target with `systemd-detect-virt`
  (run in the live environment) before the install script is generated:
  VirtualBox targets get `virtualbox-guest-utils` (graphical) or `-nox`
  (console) — the two conflict, so exactly one variant must be
  requested — plus `vboxservice` enabled, KVM/QEMU targets additionally
  get `qemu-guest-agent` enabled, and VMware graphical installs get
  `open-vm-tools`. Any other
  target installs neither; the `qemu-guest-agent` and Hyper-V daemons
  already present in the lists stay installed but are inert where
  unused.
* `vboxservice` must be enabled on VirtualBox targets (Arch does not
  auto-enable it): it is what reports the guest graphics capability to
  the host. Without it the host never sends an initial video-mode hint,
  so at X session start `VBoxClient --vmsvga` reads a 0x0 display size
  and applies it — the mode-set fails (`BadValue`, `dp-svga-x11:
  Resizing frame buffer to 0 0 has failed`) and the failed attempt
  leaves the only KMS CRTC disabled, so the VM window shows the EFI
  logo forever while the guest itself runs fine. Verified on
  VirtualBox 7.2.20 / guest kernel 7.2.8 / XLibre; recovery without the
  fix is `xrandr --output Virtual-1 --mode <mode>` from a terminal or
  over SSH.
* `locale-gen` needs the locale uncommented in `/etc/locale.gen`
  (the draft missed this); it is done automatically.
* `systemctl enable --now sshd` in chroot → `systemctl enable sshd`
  (starting via chroot would target the live system's PID 1).
* Host key changes after reinstall are handled by removing stale
  `known_hosts` entries with `ssh-keygen -R` before each connection
  phase.
* After user creation sshd password authentication is disabled
  (`/etc/ssh/sshd_config.d/10-archinstaller.conf`:
  `PasswordAuthentication no`); the tool then reconnects with the
  private key matching `--ssh-pubkey` (derived from the `.pub` file
  path, or falls back to agent/default keys).
* The timezone is applied with `timedatectl set-timezone` right after
  the first boot (it cannot run inside `arch-chroot`).
* `/etc/resolv.conf` → `stub-resolv.conf` symlink is applied right after
  the first boot, as in the draft.
* `firewalld` is installed and enabled in the basic setup of every
  install (`retry pacman -S --needed --noconfirm firewalld`,
  `systemctl enable firewalld`); the default zone configuration keeps
  SSH reachable. `--opencode` additionally opens `49374/tcp`.

## Test

```bash
poetry run pytest
```
