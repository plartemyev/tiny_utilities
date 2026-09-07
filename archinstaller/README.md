# archinstaller

Automated, unattended Arch Linux installation driven over SSH into the
Arch ISO live environment. It replicates the manual install draft
(partitioning, pacstrap, GRUB, pacman.conf tuning, third-party repos,
user creation), reboots the machine, generates a fresh SSH keypair for
the created user and prints a summary.

## Prepare the live ISO

On the Arch ISO console, before running this tool:

```bash
passwd              # set the live environment root password
systemctl start sshd
ip a                # note the address to pass as --target
```

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
    [--graphical]
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
| `--graphical` | off | console-only package list by default; with the flag the graphical packages and SDDM desktop session are installed too, and the created user gets SDDM autologin (`/etc/sddm.conf.d/10-archinstaller.conf`) |
| `--install-timeout` | `7200` | seconds allowed for the whole install script |
| `--reboot-timeout` | `900` | seconds to wait for SSH after reboot |

### Output

The final summary block (printed at the very end, after the first
boot) lists the generated root/user passwords (only those that were
generated), the target's private IP(s), public IP, created user name
and the **newly generated** user SSH public
key (an `ed25519` keypair is created on the target after the first boot;
the key passed via `--ssh-pubkey` is only used for initial access).

## Deviations from the manual draft

* `fdisk` dialog → scripted `sfdisk` (MBR: 1G ESP type `0xef` + rest root),
  same layout as the draft.
* `pacman` runs use `--noconfirm` / `--needed` (non-interactive).
* `passwd` / `EDITOR=vim visudo` → `chpasswd` and direct
  `/etc/sudoers.d/10-wheel` (mode `0440`) plus a passwordless-sudo rule
  for the created user (`/etc/sudoers.d/20-archinstaller`, mode `0440`).
* `/etc/pacman.conf` edits (Color, `ParallelDownloads = 10`, `IgnorePkg`,
  Multilib, `[xlibre]` + `[sonicde]` repos, key signing) done with `sed`
  and heredocs; the `73580DE2EDDFA6D6` key is fetched from the default
  keyserver — outbound keyserver access is required, a failure aborts.
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

## Test

```bash
poetry run pytest
```
