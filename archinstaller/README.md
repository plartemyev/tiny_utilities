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
before touching the disk. It also verifies working DNS resolution
(a broken DHCP-advertised resolver is switched to public resolvers on
the live environment; the install aborts with a clear error if that
still does not resolve). Then, on the Arch ISO console:

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
| VirtualBox VM | `virtualbox-guest-utils` (graphical) or `-nox` (console) is installed and `vboxservice` is enabled (without it the host never sends video-mode hints and `VBoxClient --vmsvga` blanks the screen after login — see the hypervisor bullet in the deviations below); the guest HDA driver is pinned to `position_fix=1` (`/etc/modprobe.d/90-archinstaller-vbox-audio.conf`) because the emulated DMA position buffer never advances — with the default auto mode the first playback stalls the audio graph and the last sound fragment loops on the host forever; use `--vbox-vm` for the host-side reboot — guest-written EFI boot entries do not survive a guest reboot there (see below) |
| Other (Hyper-V, VMware, ...) | detected and reported; `open-vm-tools` is installed only on VMware graphical installs; the base lists already carry `qemu-guest-agent` and Hyper-V daemons (inert where unused) |

Every install names the sound stack explicitly in the console package list —
`pipewire`, `wireplumber` and the `pipewire-pulse` PulseAudio compatibility —
instead of leaving them to transitive dependencies of other packages.

### TRIM/discard handling

Before the install the tool probes the target disk in the live environment
(`/sys/block/<disk>/queue/rotational` + `discard_max_bytes`) and enables
discard-dependent tuning only when the device actually accepts discards:

| Target disk | Behavior |
|---|---|
| SSD/NVMe or any other discard-capable device | `fstrim.timer` is enabled (weekly batch TRIM — SSD longevity and steady performance without the per-delete latency of continuous discard) and the swapfile fstab entry becomes `/swapfile none swap defaults,discard 0 0` so swapon trims unused swap blocks (a full trim at every swapon plus frees as pages are released) |
| discard-capable VM disk | additionally the root filesystem is mounted with the continuous `discard` option (genfstab persists the mount option into fstab) so freed extents unmap the hypervisor-side drive image at once, keeping VDI/qcow2 files compact |
| rotational HDD, or VM disk whose hypervisor drops discards | nothing is enabled — TRIM would be a no-op or never reach the backing store |

With `--vbox-vm` the tool additionally flips `--discard on` +
`--nonrotational on` onto the VM's hard-disk attachments host-side while it
is powered off (part of the existing reboot-assist step): VirtualBox shrinks
a VDI in response to guest TRIM only when the attachment carries these flags,
so without them the guest-side TRIMs never reach the image. Since the flags
land only after the install, the live-env probe cannot see them yet — for
`--vbox-vm` runs the guest is configured for discard regardless. A failed
flip only warns (e.g. IDE-attached disks cannot forward TRIM); on runs
without `--vbox-vm`, enable the two flags on the attachment yourself (VM
Storage settings) for compaction to work.

libvirt/KVM targets are the self-serve case by design (the tool manages no
libvirt state). virtio-blk advertises discard to the guest out of the box
(QEMU ≥ 4.0), so the analysis enables the guest-side config; on current
stacks (libvirt ≥ 12.7.0 with QEMU ≥ 11.1.1) the hypervisor forwards guest
TRIM into the image in all modes unless the disk XML explicitly opts out
with `discard='ignore'`. Older stacks forward only with the explicit
`<driver name='qemu' type='qcow2' discard='unmap'/>` (virt-manager: Discard
mode "unmap") — without it the guest TRIMs are silently dropped and the
image never compacts. No guest-side re-run is needed when forwarding
appears (stack upgrade or flag set): the already-enabled fstrim.timer, swap
discard and root discard start unmapping on their next pass. Recommended
companion on the same `<driver>`: `detect_zeroes='unmap'` converts guest
zero-writes into live unmaps — compacting zero-heavy writes such as a
reinstall's fresh mkfs or `dd`-style zeroing without waiting for the next
fstrim pass (must be set together with `discard='unmap'`, which it requires).
Compaction frees the image's allocated blocks (`du`); the apparent file size
only shrinks when the discarded range reaches the image tail.

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
| `--graphical` | off | console-only package list by default; with the flag the Xlibre X server stack is installed first, then the Sonic DE base (`sonicde-meta`, `sonic-ecco`, `sonic-win`, `sonic-workspace`), then the graphical packages (this order makes the `xorg-server` and KDE/Plasma dependencies resolve to their xlibre/sonic replacements instead of conflicting), the SDDM desktop session is installed with autologin for the created user (`/etc/sddm.conf.d/10-archinstaller.conf`; the `Session=` entry is auto-detected from the installed session desktop files — SDDM refuses to autologin without it), the ACPI power button is wired for clean host-side shutdown — on VM targets PowerDevil is masked (its logind inhibitor blocks the button while its X11 delivery never fires it, making `VBoxManage controlvm acpipowerbutton` a no-op; logind's power-key default then shuts the machine down in ~5 s) and the KDE power profiles are seeded with the Shutdown action for stacks where PowerDevil's button delivery works (e.g. Wayland) — and on VirtualBox targets the full `virtualbox-guest-utils` (X11/Wayland integration) replaces the headless `virtualbox-guest-utils-nox` (non-VirtualBox targets install neither) |
| `--opencode` | off | additionally deploy the opencode web server as a systemd **user** service on port `49374` (opens the port in firewalld; see below) |
| `--install-timeout` | `7200` | seconds allowed for the whole install script |
| `--reboot-timeout` | `900` | seconds to wait for SSH after reboot |
| `--no-subnet-scan` | off | if the rebooted target does not answer at `--target` in time, the tool scans the surrounding /24 (TCP 22 probe of the 254 host addresses, then a key-authenticated SSH login) for the machine reporting the configured hostname and continues at that address; this flag disables the fallback |
| `--vbox-vm NAME` | none | VirtualBox VM name for a **host-side** reboot: clean power-off, NVRAM store backed up to `.nvram.bak` (fresh firmware defaults on next boot), boot order disk-before-DVD, start — makes the first boot work out of the box (see below); the VM's hard-disk attachments are also re-attached with `--discard on` + `--nonrotational on` so guest TRIM compacts the drive images (see TRIM/discard handling) |
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
`--target`, fall back to the /24 hostname scan, then verify DNS (the
install system carries a NetworkManager dispatcher hook that probes the
connection's DHCP DNS servers on every network event: while they answer
they are used as-is — router DNS, search domains and split-DNS all
apply; when none answers, DHCP DNS is ignored so systemd-resolved's
built-in fallback resolvers take over, self-reverting when the network
heals. Stage two kicks the hook once if resolution is broken right
now), apply the timezone, `resolv.conf`, user key and opencode service,
print the summary, and delete the state file. If the machine does not come back, the tool
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

## Test

```bash
poetry run pytest
```
