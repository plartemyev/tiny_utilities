# Project Guidelines

- Always read `README.md`;
- If there are major project changes, please update `README.md`;
- If you discover some tool calling peculiarities (specific arguments, non-standard paths, etc.), please document them
  in `AGENTS.md` for future reference;
- Strive for resource reusability, maintainability and consistency;

## Tooling notes

- Avoid formatting and empty lines changes on existing files unless explicitly asked for.
- On Arch Linux (`archlinux:latest`), `corepack` is a separate package from
  `nodejs`. To use Yarn 4 via Corepack, you must install both and then run
  `corepack enable`.
- When using Yarn 4 with `nodeLinker: node-modules` across multiple linked
  repositories (e.g. via `portal:`), it is recommended to explicitly set
  `export YARN_NODE_LINKER = node-modules` in the environment to avoid
  "Couldn't find the node_modules state file" errors during build steps.
- Never use `/tmp/` directory in your work (absolute path to system temp directory).
- If you want to create/write temporary files, then use/create a `tmp`
  directory in the current project.
- For long-running commands (e.g. `docker compose up --build`), detach with `setsid ... </dev/null >path/tmp/run.log 2>&1 & disown` and poll the log in separate tool calls; do not pipe through `tail` (it buffers until EOF, so a hanging build shows no output and times out the tool).
- When investigating network/services unavailability use `nc -zvw 1 TARGET TARGET_PORT`, `curl -vkL TARGET >/dev/null`, `mtr --json --aslookup --mpls --timeout 30 TARGET`. Check from multiple sources (check public IP availability both from Ansible managed host and from the DEV computer);
- KDE Connect DBus (session bus) peculiarities (discovered on Arch, Xlibre/Sonic DE, kdeconnectd):
    - Each phone media player gets its own MPRIS bus name `org.mpris.MediaPlayer2.kdeconnect.mpris_<hash>` (NOT the device id); the phone-side app name is in `Identity` on `/org/mpris/MediaPlayer2` (e.g. `Fennec - Raptor LTD`), not in `Metadata`;
    - `mpris:trackid` is always the constant `/org/mpris/MediaPlayer2` for phone players — use `xesam:title` for track identity; `Position` is always `-1000` (unknown); `mpris:length` (µs) and `xesam:url` are present only for some apps; metadata keys differ per app;
    - `org.kde.kdeconnect.device.notifications.notificationPosted` signal payload is just the numeric notification id (not JSON); content must be fetched afterwards via the `activeNotifications` method;
    - Some remote MPRIS `Play` calls are refused by the phone app itself (e.g. a background browser tab stays `Paused` after a remote `Play`);
    - PyGObject `DBusProxy` `g-properties-changed`: the `changed` dict is a `GLib.Variant` — plain `in`/`[]` access raises `KeyError: 0`; call `.unpack()` first;
    - PyGObject `GLibUnix.signal_add` invokes the handler with zero args, while `GLib.unix_signal_add` passes `(user_data)`; the former is the non-deprecated variant;
    - Existing tooling for this: `kdeconnect-media-logger/` (service) and `tmp/kdeconnect_media_probe.py` (exploratory probe).
- opencode v2 server peculiarities (Arch package 2.0.18; verified in a systemd docker container):
    - standalone `opencode serve` honours `OPENCODE_SERVER_PASSWORD`: with it set, HTTP basic auth is
      enforced (401 without/wrong creds, 200 with `opencode:<password>`); without it a random password is
      generated and printed to stdout (lost in the journal when run under systemd);
    - the basic-auth username is hardcoded to `opencode`: `OPENCODE_SERVER_USERNAME` is ignored by 2.0.18
      (honoured by newer v2 builds) and `opencode service set username ...` fails with "Unknown service config key";
    - `~/.config/opencode/service.json` (managed by `opencode service set/get`) is used only by the
      background-service mode (`opencode service start`), NOT by standalone `opencode serve`;
    - auth protects API routes (e.g. `/openapi.json`); static assets and health endpoints stay public.
- `loginctl enable-linger` without a user argument (verified in a systemd docker container over SSH):
    - resolves to the **owner of the logind session the calling process belongs to** — `sudo`, `sudo sh -c`,
      `sudo su`/`sudo -i` root shells all still target the SSH session's user (sudo/su create no logind
      session on Arch); only a genuine root session (console login, `machinectl shell`, sshd-as-root) targets root;
    - fails with `Access denied` without root privileges over SSH (polkit `set-self-linger` allows active
      sessions only), and fails outright with rc=1 in session-less contexts (systemd services, cron,
      docker exec) — there is no euid fallback and no "all users" mode;
    - linger itself is per-user marker files in `/var/lib/systemd/linger/<username>`; users created later
      never linger until enabled explicitly;
    - the named form `loginctl enable-linger <username>` is the only one independent of session/PAM context.
- VirtualBox EFI NVRAM peculiarities (verified on a VirtualBox 7.x EFI VM with `firmware="EFI"` + `.nvram` store):
    - `efibootmgr` entries written by the guest do **not** survive a guest-initiated reboot (`systemctl reboot`
      = VM reset); the NVRAM store is only flushed on power-off. An installer that wipes the disk (new random
      MBR disk-id via `sfdisk`) and then reboots silently loses its fresh boot entry, leaving stale ones that
      reference the old disk-id — the firmware skips them and falls through to the still-attached ISO;
    - reliable fix: also install the signature-less fallback bootloader `\EFI\BOOT\BOOTX64.EFI`
      (`grub-install ... --removable`); it boots via the firmware's plain HDD option with no NVRAM dependency
      (done in `archinstaller/archinstaller/script.py`, see the README deviations);
    - repairing an affected VM: boot the ISO, mount root + ESP, `arch-chroot` and re-run both `grub-install`
      variants, detach the ISO with `vboxmanage storageattach <vm> --storagectl IDE --port 0 --device 0
      --type dvddrive --medium emptydrive`, then power off (not reboot) so NVRAM flushes, and start again;
    - VirtualBox host-only DHCP keys leases by client-id, not MAC (lease store:
      `~/.config/VirtualBox/HostInterfaceNetworking-*-Dhcpd.leases`): the archiso's systemd-networkd sends a
      DUID-EN derived from a transient machine-id (archiso `/etc/machine-id` is empty), so every ISO boot is a
      new client and gets the next pool address (observed .104→.115 for one MAC); NetworkManager on the
      installed system defaults to a MAC-based client-id, so only the first installed boot may land on a
      different address — archinstaller falls back to scanning the target's /24 for the configured hostname
      after a reboot timeout;
    - VirtualBox EFI forensics (second full install run confirmed): after a guest reboot the fresh
      `GRUB` entry was absent again while `Boot0005` still carried the old disk-id — guest-written NVRAM
      is lost across guest reboots, only power-off flushes persist; the system DID auto-boot once the
      firmware reached the whole-disk entry (`BootCurrent: 0002`, `\EFI\BOOT\BOOTX64.EFI` fallback), and
      the firmware's own housekeeping reordered that entry ahead of UiApp/CD after a power-cycle;
    - firewalld `public` (ssh + dhcpv6-client only) does NOT block DHCPv4 client leases — NetworkManager
      leased both NICs fine on the installed system (earlier "no lease" was the VM sitting in the EFI UI);
    - VBoxClient 0x0 blank-screen chain (verified on a VirtualBox guest, VirtualBox 7.2.20 host / guest kernel 7.2.8 /
      XLibre, `graphicscontroller="vmsvga"`, 3D on): if `vboxservice.service` is not enabled, the guest
      never reports the graphics capability to the host (`VMMDev: Guest Additions capability report:
      graphics: no` in VBox.log), so the host never sends an initial video-mode hint; at X session start
      `VBoxClient --vmsvga` (logs under `dp-svga-x11` via VMMDev guest log) queries the display size,
      gets 0x0, and applies it — X rejects the mode (`BadValue`, `Resizing frame buffer to 0 0 has
      failed, current mode 1280 800`) but the attempt leaves the single KMS CRTC disabled
      (`/sys/class/drm/card0-Virtual-1/enabled` = `disabled`, `xrandr --listactivemonitors` = 0), and
      the VM window shows the EFI logo forever while the guest runs fine over SSH; guest dmesg noise
      `vmwgfx seems to be running on an unsupported hypervisor` + `Failed to open channel` is cosmetic
      (GCM/MesaVmsvgaDrv fixer, present on every VMSVGA boot); recovery: `xrandr --output Virtual-1
      --mode <mode>` inside the session (root needs `XAUTHORITY=/tmp/xauth_*` — SDDM writes a fresh
      random-named file per boot, `/run/sddm/xauth_*` from the previous boot goes stale); permanent fix:
      `systemctl enable vboxservice` (now done by archinstaller for `virt == "oracle"`);
    - archinstaller enabled `qemu-guest-agent` for kvm/qemu but never `vboxservice` for VirtualBox
      targets (hit on a 2026-10-02 install → the blank screen above); installs made before commit
      525d0e9 also carry a stray inert `open-vm-tools` package on VirtualBox targets (removable with
      `pacman -R open-vm-tools`);
    - `archinstaller --vbox-vm <name>` reboots from the host (poweroff → `<vm>.nvram` → `.nvram.bak` →
      `--boot2 disk --boot3 dvd` → start) so the first boot works out of the box;
      `--resume <state-file>` finishes a previous run's post-boot stage; the state file
      (`archinstaller-state-<hostname>.json`, mode 0600, holds generated passwords) is written before the
      reboot and deleted on success;
    - VirtualBox discard/TRIM forwarding (guest TRIM shrinking the VDI; wired into archinstaller as
      `vbox.enable_discard` + guest-side fstrim/swap/root-discard config): `--discard on` and
      `--nonrotational on` are **per-attachment** flags on `VBoxManage storageattach` (not `modifyvm`),
      and the re-attach must re-pass `--storagectl/--port/--device/--type/--medium`; without
      `--discard on` the guest may TRIM all day and the VDI never shrinks. Attachments appear in
      `showvminfo --machinereadable` as `"<controller>-<port>-<device>"` keys (controller names come from
      the `storagecontrollername<N>` keys; subkeys like `"<id>-UUID"` are NOT attachments); the emulation
      forwards TRIM only on controllers that support it (SATA/AHCI, NVMe) — IDE-attached disks cannot;
      the flags are only settable while the VM is powered off, so on `--vbox-vm` runs the guest discard
      config is decided before the live-env probe could ever see them (probed via
      `/sys/block/<disk>/queue/{rotational,discard_max_bytes}`);
    - libvirt/qemu discard forwarding (see the archinstaller README TRIM section): virtio-blk advertises
      discard to the guest since QEMU 4.0 regardless of backend forwarding; on libvirt ≥ 12.7.0 with
      QEMU ≥ 11.1.1 guest discards reach the image in all modes unless the disk XML explicitly sets
      `<driver ... discard='ignore'/>`, older stacks forward only with the explicit `discard='unmap'`;
      the live-env probe cannot distinguish "advertised" from "forwarded" (hypervisor-side state,
      invisible to the guest). QEMU's `detect_zeroes='unmap'` (converts guest zero-writes to unmaps
      live) has NO VirtualBox analog: VirtualBox forwards only explicit guest TRIM (`--discard on`),
      and its only zero-based compaction is the offline batch `VBoxManage modifymedium --compact`
      ("removes blocks that only contain zeroes", VDI, medium must not be attached to a running VM);
    - opencode unit Environment changes need `systemctl --user restart` (never just `start`) to reach the
      running process — `start` is a no-op on an active service, so a rewritten unit's new password gives
      HTTP 401 until a restart (hit during the manual stage-two replay); the tool's unit upload is
      follow-by-restart-safe because it runs before the first start;
    - target matrix (verified `systemd-detect-virt` = `oracle` on a VirtualBox target): the hypervisor is detected in
      the live env before script generation (`oracle` → virtualbox-guest-utils/-nox per `--graphical`;
      `kvm`/`qemu` → `qemu-guest-agent` enabled; `vmware` → `open-vm-tools` on graphical installs;
      anything else → neither) and the tool preflights UEFI (`test -d /sys/firmware/efi`) before touching
      the disk, so BIOS-booted targets fail fast instead of dying inside `grub-install` after pacstrap;
      physical machines and libvirt VMs need no host-side boot fix (their NVRAM persists guest-written
      entries), `--vbox-vm` stays VirtualBox-only;
    - the "missing" `initramfs-linux-fallback.img` on new installs is upstream default, not a tool bug:
      Arch's `/etc/mkinitcpio.d/linux.preset` ships `PRESETS=('default')` with the fallback preset
      commented out, so `mkinitcpio -P` builds the default image only;
    - SDDM autologin requires `Session=` in `[Autologin]`: with only `User=` set the journal shows
      "Unable to find autologin session entry" and the greeter appears instead (hit on a fresh install — the tool now
      detects the session via `find` over `/usr/share/{x,wayland}-sessions` at install time);
    - SDDM autologin also cannot auto-unlock password-encrypted secret stores — pam_kwallet5 logs
      "Couldn't get password (it is empty)" and the wallet stays locked until the first app prompts
      (ksecretd, which ships inside the `kwallet` package since 6.x, has the same encrypted backing store);
      the only autologin-compatible auto-unlock is a blank wallet password (insecure) or TPM-sealed
      secrets (not wired into this stack);
    - diagnostic helper: `tmp/vm_probe.py` (runs efibootmgr/lsblk/mounts over SSH into the ISO environment);
      `tmp/finish_install.py` + `tmp/restart_opencode.py` replayed an interrupted install's stage two on
      the target VM.
    - missing icons on fresh Sonic DE installs (observed 2026-10-02): startplasma never materializes the
      Silver session defaults — `~/.config/kdedefaults` stays empty (no `[Icons] Theme=silver`, colors,
      cursors), every theme/icon lookup falls back to hicolor and kickoff/tray/KRunner render generic
      icons; `sonic-silver-icons` is complete (breeze renamed, nothing missing) and `sonic-breeze` is an
      unrelated explicitly-installed leftover on working hosts. `plasma-apply-lookandfeel` fixes it but
      only in a fully interactive session — it fails ("Failed to open package file") or segfaults in
      chroot/offscreen/autostart contexts; fix: archinstaller seeds `~/.config/kdedefaults/*` + a
      `package` marker (no trailing newline!) + `kdeglobals [KDE] LookAndFeelPackage` — the marker pair
      keeps startplasma's empty-writing defaults step from firing on later logins (see the deviations
      bullet in `archinstaller/README.md`);
    - driving a running guest from the host without SSH (used for the icon debugging): `VBoxManage
      controlvm <vm> screenshotpng file.png` (watch the screen) and `keyboardputscancode` (set-1 hex
      bytes, extended keys as two bytes e.g. `e0 1f e0 f0 1f` for Meta — flaky, may type bare keys),
      `keyboardputstring "cmd"` + scancode `1c 9c` (Enter) into Konsole/KRunner restores access when
      `~/.ssh/authorized_keys` is gone; `VBoxManage controlvm <vm> poweroff` + `startvm` for the cold
      cycle;
    - `systemctl reboot` inside the VirtualBox guest hung at the final `Remounting '/' read-only` shutdown step (twice);
      `systemctl poweroff` works — power off and `VBoxManage startvm` instead of guest reboots;
      a 2026-10-03 deep-dive (anvil) confirmed the mechanism: the guest kernel stays alive and idles
      (both vCPUs in `pv_native_safe_halt` = `default_idle`, NOT `stop_this_cpu`), so the hang is
      systemd-shutdown (PID 1) blocked in its late phase (sync/remount-ro of the VirtioSCSI root),
      and no reset ever reaches VBox (log shows no `RESETTING`). Intermittent: 1 hang vs 8+ clean
      reboots on the same VM; poweroffs never hang. Debugging peculiarities:
      - `VBox.log` stamps are **relative to VM start** (not wall clock; `Log opened <ISO>` gives the
        anchor). Guest reboot = `RUNNING→RESETTING→RUNNING`; the reset line is preceded by
        `ACPI: Reset initiated by ACPI`; silent window + no reset = guest-side stall. At power-off
        VBox dumps both vCPUs' full register state ("Guest state at power off") — a snapshot of any
        pre-poweroff hang; symbolize via guest `/proc/kallsyms` (fix KASLR slide with the
        `entry_SYSCALL_64` value from the dump's `LSTAR` vs current boot).
      - `VBoxManage debugvm <vm> dumpvmcore --filename=f.elf` grabs guest RAM (~RAM-size) while
        running; the printk ring buffer is inside, greppable as `[YYYY-MM-DD HH:MM:SS] message...`
        — captures everything after journald died. `debugvm osdmesg` fails with VERR_NOT_FOUND on
        kernel 7.2 (VBox 7.2.20 too old for its log layout); `debugvm osdetect` works.
      - re-arm before hunting the hang (removed again 2026-10-03 after the deep-dive):
        `printf "kernel.printk = 7 4 1 7\nkernel.sysrq = 1\n" | sudo tee /etc/sysctl.d/90-shutdown-debug.conf`
        makes a hung-task report ("task systemd-shutdown/1 blocked for 120+s" + blocker) print to
        the console — capture with `VBoxManage controlvm <vm> screenshotpng` or from the dumpvmcore
        ring buffer (stock: printk `3 4 1 3`, sysrq `16`);
    - sshd (StrictModes) rejects a **root-owned** `~/.ssh/authorized_keys` (Permission denied even with
      correct perms); files written by root into a user's home must be chowned (archinstaller's install
      script already does this for `authorized_keys`);
    - VirtualBox NAT network DNS is snapshotted, not tracked (hit 2026-10-03 on the anvil install —
      guest DNS silently died after the host switched networks):
      `VBoxSVC` reads the host resolver config at startup and caches it; the NAT network service
      (`VBoxNetNAT`) advertises that cached list via DHCP forever. When the host roams
      (wired `192.168.1.x` → wifi `192.168.0.x`), guests keep the old, now-unreachable DNS server
      while routing keeps working — lookups just time out. `VBoxManage natnetwork stop/start` does
      NOT refresh the list (its config comes from the same VBoxSVC cache); the only fix is restarting
      VBoxSVC — power off every VM first (a VBoxSVC kill takes running VMs down with it), then
      `pkill -9 VBoxSVC` (SIGTERM was insufficient once), renew the guest lease
      (`nmcli device reapply`) after the next start. Plain per-VM NAT mode (`--nic1 nat`) is better:
      its engine lives in the VM process and passes through the host's CURRENT resolvers at every VM
      boot (verified: a fresh VM-process start advertised 192.168.0.1 while a same-state NAT network
      still advertised the stale value); `--natdnshostresolver1 on` goes further and resolves per
      query via the host resolver. Guest-side resilience is now built into
      archinstaller: stage one verifies DNS on the live ISO and falls back to public resolvers via
      `resolvectl dns <default-route-iface> 1.1.1.1 8.8.8.8` (fails the install fast if still broken);
      the install system carries a NetworkManager dispatcher hook
      (`/etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback`) that probes each
      connection's lease DNS servers directly (`timeout 4 drill archlinux.org @<server>`; drill is
      from the already-installed ldns) on every network event and toggles `ipv4/ipv6.ignore-auto-dns`:
      servers answering → off (router DNS, search domains and split-DNS all apply), all dead → on
      (resolved's fallback 9.9.9.9/1.1.1.1/8.8.8.8 take over). The decision is derived per-server, so
      it is loop-free and self-reverting (a reapply-triggered event re-probes and re-adopts a healed
      lease — verified on anvil; nmcli gotcha: `con modify` takes `prop value`, the `prop=value` form
      only exists in get output and is rejected). Stage two just kicks the hook once
      (`manual --worker`) when its own probe finds resolution broken;
    - Plasma PowerDevil makes ACPI power buttons a no-op on X11 VMs (hit on anvil, powerdevil
      6.7.5/Xlibre, 2026-10-03): the daemon takes a **block** inhibitor on `handle-power-key` at
      startup ("KDE handles power events"), so logind's default `HandlePowerKey=poweroff` never
      fires — and PowerDevil's own button path is dead on this stack: real `acpipowerbutton` presses
      (logind logs "Power key pressed short", the inhibitor swallows them) and synthetic XTEST
      `xdotool key XF86PowerOff` presses alike never reach PowerDevil (kglobalaccel grabs never fire;
      `QT_LOGGING_RULES="powerdevil*=true"` shows no button activity). Seeding the action changes
      nothing on X11 — note the profile settings live in `~/.config/powerdevilrc` on powerdevil 6.7
      (`powermanagementprofilesrc` is legacy; the `[Migration] MigratedProfilesToPlasma6=powerdevilrc`
      marker points away from it, and external file edits are NOT live-reloaded — restart
      plasma-powerdevil.service to apply). `PowerButtonAction` enum: 0 NoAction, 1 Sleep, 2 Hibernate,
      8 Shutdown, 16 PromptLogoutDialog (the non-mobile default), 32 LockScreen, 64 TurnOffScreen,
      128 ToggleScreenOnOff. Working setups, verified on anvil: console installs (no powerdevil) and
      graphical VM installs with plasma-powerdevil **masked** (`systemctl --user mask
      plasma-powerdevil.service`; archinstaller does this for `--graphical` on VM targets and keeps
      the daemon on physical machines) → `VBoxManage controlvm <vm> acpipowerbutton` cleanly powers
      off in ~5 s via logind; otherwise automate clean shutdowns with SSH `sudo systemctl poweroff`
      (~10 s; guest poweroffs never hang, unlike guest-initiated reboots) or hard
      `VBoxManage controlvm <vm> poweroff` (what `--vbox-vm` uses);
    - VirtualBox HDA guest audio freeze + ring-buffer loop (hit on anvil, VirtualBox 7.2.20 host /
      7.2.8 guest kernel, pipewire 1.6.9 + wireplumber 0.5.18, 2026-10-03): the emulated HDA
      advertises a DMA position buffer that never advances — guest
      `/proc/asound/card0/pcm0p/sub0/status` shows `hw_ptr: 0` with appl_ptr/delay frozen while the
      sink is RUNNING, so the audio graph stalls and the **first pulse client hangs forever**
      (`paplay` blocks silently, sink ends SUSPENDED), while the emulated controller keeps clocking
      the whole ALSA ring buffer to the host: the last-written fragment repeats every ring period
      (buffer_size/rate — 0.74 s at the wireplumber-picked 44100/period 1024) indefinitely;
      pipewire/wireplumber logs stay clean (no XRUNs). Observing it: on the host
      `pactl load-module module-null-sink sink_name=vbxtap`, `pactl move-sink-input <idx-of
      "VirtualBox front [...]"> vbxtap`, then `parec -d vbxtap.monitor --file-format=wav` and look
      for periodic bursts while the guest is idle. Fix: `options snd-hda-intel position_fix=1`
      (read the LPIB register instead of the position buffer — the emulation keeps that one
      accurate); a guest stack restart only clears the loop until the next stuck playback. Baked
      into the installs as `/etc/modprobe.d/90-archinstaller-vbox-audio.conf` on `oracle` targets
      (verified: sounds play once and the device idle-closes to silence after a reboot with the
      option persisted);
- `arch-cache-mirror/` (caching pacman mirror container) peculiarities (discovered 2026-10-05 while
  building it):
    - `archlinux:latest` docker builds: plain `pacman -Syu` fails signature checks when the image's
      `archlinux-keyring` lags behind the current repos; fix is `pacman -Sy --noconfirm
      archlinux-keyring && pacman -Syu --noconfirm <pkgs>` (baked into `arch-cache-mirror/Dockerfile`);
    - Arch mirrors largely IGNORE `If-Modified-Since` — `geo.mirror.pkgbuild.com` and
      `mirror.rackspace.com` both answered HTTP 200 to a conditional GET with a 2099 date (HEAD too),
      so conditional db revalidation is pointless against them; arch-cache-mirror instead triggers a
      bounded fresh retrieval (FRESH_WAIT, 5 s default) on every stale db request and falls back to
      serving the cached copy while the refresh continues in the background;
    - GitHub Pages edges can serve a short body with a stale Content-Length depending on the client's
      vantage point: `sonicde-arch.github.io/x86_64/sonicde.db` reported `Content-Length: 21502` with
      a 21500-byte body from a docker container while the host consistently got `21500/21500` — strict
      clients (pacman's curl, aiohttp, urllib) abort with "transfer truncated" although the whole file
      arrived. arch-cache-mirror buffers db downloads (they are small) and keeps what arrived, so
      clients always get self-consistent responses;
    - pacman aborts any download that transfers < 1 B/s for 10 s (curl low-speed default) — a proxy
      that buffers a large db (e.g. `extra.db` 8.4 MB on a slow moment) before sending the first
      client byte gets its clients killed; this is the second reason dbs are never proxied live but
      served from cache with background refresh (packages still stream through);
    - pacman `vercmp` reference source: sources.archlinux.org only hosts tarballs up to 6.0.2 (7.x not
      published there) and gitlab.archlinux.org is Anubis-walled; the algorithm is unchanged in 7.x —
      port from the 6.0.2 tarball (`lib/libalpm/version.c`) and differential-test against the 7.x
      binary in the container (`tmp/difftest_vercmp.py`, 2500 pairs, 0 mismatches);
    - `docker compose config --format json` does NOT unescape `$$` in environment values (it emits a
      valid compose representation), so deriving an env-file from it for `docker run --env-file`
      needs an explicit `value.replace("$$", "$")` (done in `arch-cache-mirror/e2e.sh`, which sources
      the repo/mirror env from docker-compose.yml to keep a single source of truth); watch out for
      stale leftovers when debugging: a failed `docker run --network <new-net>` leaves the previously
      created container serving on the same name, and its old logs look like fresh failures;
    - unit tests that construct the Config object directly never exercise `Config.from_env()` env
      defaults — a lost default constant there produced empty mirror lists (instant 502s with no
      upstream attempt logged) and only surfaced in e2e; `test_from_env` in
      `arch-cache-mirror/test_mirror.py` now locks the defaults contract;
    - aiohttp: mutating `app[...]` after the application started emits "Changing state of started or
      joined application is deprecated" (3.14) — share a plain dict set before startup and mutate it
      in place instead;
    - non-root in-container runtime (since 2026-10-06): the image ships a `mirror` user (uid/gid 1000)
      and `docker-compose.yml` maps it to the compose caller via `user: "${UID:-1000}:${GID:-1000}"` so
      the bind-mounted `./cache` stays host-user owned. Peculiarities: bash's `UID` is a readonly,
      NOT-exported shell variable — `UID=$(id -u) docker compose ...` dies with "readonly variable" and
      plain invocation leaves compose blind to it, so overrides must go through a `.env` file or
      `env UID=... GID=...` (zsh: both readonly as well); with a `:-` default compose interpolates
      silently (no warning), so a uid≠1000 host without the override only surfaces as a container
      crash-loop (PermissionError on the cache dir). `e2e.sh` derives both env AND the compose `user:`
      value from `docker compose config --format json` and passes it as `docker run --user`, plus a
      `stat -c %u` ownership assertion on cached files; because cache files are host-uid owned, the
      old root-wipe-through-a-container cleanup step is gone (plain `rm -rf` works).


## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## Coding guidelines
The Power of Ten – Rules for Developing Safety Critical Code
1. Rule: Restrict all code to very simple control flow constructs – do not use goto
statements, setjmp or longjmp constructs, and direct or indirect recursion.
Rationale: Simpler control flow translates into stronger capabilities for verification
and often results in improved code clarity. The banishment of recursion is perhaps the
biggest surprise here. Without recursion, though, we are guaranteed to have an
acyclic function call graph, which can be exploited by code analyzers, and can
directly help to prove that all executions that should be bounded are in fact bounded.
(Note that this rule does not require that all functions have a single point of return –
although this often also simplifies control flow. There are enough cases, though,
where an early error return is the simpler solution.)
2. Rule: All loops must have a fixed upper-bound. It must be trivially possible for a
checking tool to prove statically that a preset upper-bound on the number of iterations
of a loop cannot be exceeded. If the loop-bound cannot be proven statically, the rule
is considered violated.
Rationale: The absence of recursion and the presence of loop bounds prevents
runaway code. This rule does not, of course, apply to iterations that are meant to be
non-terminating (e.g., in a process scheduler). In those special cases, the reverse rule
is applied: it should be statically provable that the iteration cannot terminate.
One way to support the rule is to add an explicit upper-bound to all loops that have a
variable number of iterations (e.g., code that traverses a linked list). When the upper-
bound is exceeded an assertion failure is triggered, and the function containing the
failing iteration returns an error. (See Rule 5 about the use of assertions.)
3. Rule: Do not use dynamic memory allocation after initialization.
Rationale: This rule is common for safety critical software and appears in most
coding guidelines. The reason is simple: memory allocators, such as malloc, and
garbage collectors often have unpredictable behavior that can significantly impact
performance. A notable class of coding errors also stems from mishandling of
memory allocation and free routines: forgetting to free memory or continuing to use
memory after it was freed, attempting to allocate more memory than physically
available, overstepping boundaries on allocated memory, etc. Forcing all applications
to live within a fixed, pre-allocated, area of memory can eliminate many of these
problems and make it easier to verify memory use. Note that the only way to
dynamically claim memory in the absence of memory allocation from the heap is to
use stack memory. In the absence of recursion (Rule 1), an upper-bound on the use of
stack memory can derived statically, thus making it possible to prove that an
application will always live within its pre-allocated memory means.
4. Rule: No function should be longer than what can be printed on a single sheet of
paper in a standard reference format with one line per statement and one line per
declaration. Typically, this means no more than about 60 lines of code per function.
Rationale: Each function should be a logical unit in the code that is understandable
and verifiable as a unit. It is much harder to understand a logical unit that spans
multiple screens on a computer display or multiple pages when printed. Excessively
long functions are often a sign of poorly structured code.
5. Rule: The assertion density of the code should average to a minimum of two
      assertions per function. Assertions are used to check for anomalous conditions that
      should never happen in real-life executions. Assertions must always be side-effect
      free and should be defined as Boolean tests. When an assertion fails, an explicit
      recovery action must be taken, e.g., by returning an error condition to the caller of the
      function that executes the failing assertion. Any assertion for which a static checking
      tool can prove that it can never fail or never hold violates this rule. (I.e., it is not
      possible to satisfy the rule by adding unhelpful “assert(true)” statements.)
      Rationale: Statistics for industrial coding efforts indicate that unit tests often find at
      least one defect per 10 to 100 lines of code written. The odds of intercepting defects
      increase with assertion density. Use of assertions is often also recommended as part
      of a strong defensive coding strategy. Assertions can be used to verify pre- and post-
      conditions of functions, parameter values, return values of functions, and loop-
      invariants. Because assertions are side-effect free, they can be selectively disabled
      after testing in performance-critical code.
      A typical use of an assertion would be as follows:  
      ```
      if (!c_assert(p >= 0) == true) {
        return ERROR;
      }
      ```
      with the assertion defined as follows:  
      ```
      #define c_assert(e) ((e) ? (true) : \
        (tst_debugging(”%s,%d: assertion ’%s’ failed\n”, \
        __FILE__, __LINE__, #e), false))
      ```
     In this definition, __FILE__ and __LINE__ are predefined by the macro preprocessor
     to produce the filename and line-number of the failing assertion. The syntax #e turns
     the assertion condition e into a string that is printed as part of the error message. In
     code destined for an embedded processor there is of course no place to print the error
     message itself – in that case, the call to tst_debugging is turned into a no-op, and
     the assertion turns into a pure Boolean test that enables error recovery from
     anomolous behavior.
6. Rule: Data objects must be declared at the smallest possible level of scope.
Rationale: This rule supports a basic principle of data-hiding. Clearly if an object is
not in scope, its value cannot be referenced or corrupted. Similarly, if an erroneous
value of an object has to be diagnosed, the fewer the number of statements where the
value could have been assigned; the easier it is to diagnose the problem. The rule
discourages the re-use of variables for multiple, incompatible purposes, which can
complicate fault diagnosis.
7. Rule: The return value of non-void functions must be checked by each calling
function, and the validity of parameters must be checked inside each function.
Rationale: This is possibly the most frequently violated rule, and therefore somewhat
more suspect as a general rule. In its strictest form, this rule means that even the
return value of printf statements and file close statements must be checked. One can
make a case, though, that if the response to an error would rightfully be no different
than the response to success, there is little point in explicitly checking a return value.
This is often the case with calls to printf and close. In cases like these, it can be
acceptable to explicitly cast the function return value to (void) – thereby indicating
that the programmer explicitly and not accidentally decides to ignore a return value.
In more dubious cases, a comment should be present to explain why a return value is
irrelevant. In most cases, though, the return value of a function should not be ignored,
especially if error return values must be propagated up the function call chain.
Standard libraries famously violate this rule with potentially grave consequences. See,
for instance, what happens if you accidentally execute strlen(0), or strcat(s1, s2, -1)
with the standard C string library – it is not pretty. By keeping the general rule, we
make sure that exceptions must be justified, with mechanical checkers flagging
violations. Often, it will be easier to comply with the rule than to explain why non-
compliance might be acceptable.
8. Rule: The use of the preprocessor must be limited to the inclusion of header files and
simple macro definitions. Token pasting, variable argument lists (ellipses), and
recursive macro calls are not allowed. All macros must expand into complete
syntactic units. The use of conditional compilation directives is often also dubious,
but cannot always be avoided. This means that there should rarely be justification for
more than one or two conditional compilation directives even in large software
development efforts, beyond the standard boilerplate that avoids multiple inclusion of
the same header file. Each such use should be flagged by a tool-based checker and
justified in the code.
Rationale: The C preprocessor is a powerful obfuscation tool that can destroy code
clarity and befuddle many text based checkers. The effect of constructs in unrestricted
preprocessor code can be extremely hard to decipher, even with a formal language
definition in hand. In a new implementation of the C preprocessor, developers often
have to resort to using earlier implementations as the referee for interpreting complex
defining language in the C standard. The rationale for the caution against conditional
compilation is equally important. Note that with just ten conditional compilation
directives, there could be up to 210 possible versions of the code, each of which would
have to be tested– causing a huge increase in the required test effort.
9. Rule: The use of pointers should be restricted. Specifically, no more than one level of
dereferencing is allowed. Pointer dereference operations may not be hidden in macro
definitions or inside typedef declarations. Function pointers are not permitted.
Rationale: Pointers are easily misused, even by experienced programmers. They can
make it hard to follow or analyze the flow of data in a program, especially by tool-
based static analyzers. Function pointers, similarly, can seriously restrict the types of
checks that can be performed by static analyzers and should only be used if there is a
strong justification for their use, and ideally alternate means are provided to assist
tool-based checkers determine flow of control and function call hierarchies. For
instance, if function pointers are used, it can become impossible for a tool to prove
absence of recursion, so alternate guarantees would have to be provided to make up
for this loss in analytical capabilities.
10. Rule: All code must be compiled, from the first day of development, with all
compiler warnings enabled at the compiler’s most pedantic setting. All code must
compile with these setting without any warnings. All code must be checked daily with
at least one, but preferably more than one, state-of-the-art static source code analyzer
and should pass the analyses with zero warnings.
Rationale: There are several very effective static source code analyzers on the
market today, and quite a few freeware tools as well. 2 There simply is no excuse for
any software development effort not to make use of this readily available technology.
It should be considered routine practice, even for non-critical code development.
The rule of zero warnings applies even in cases where the compiler or the static
analyzer gives an erroneous warning: if the compiler or the static analyzer gets
confused, the code causing the confusion should be rewritten so that it becomes more
trivially valid. Many developers have been caught in the assumption that a warning
was surely invalid, only to realize much later that the message was in fact valid for
less obvious reasons. Static analyzers have somewhat of a bad reputation due to early
predecessors, such as lint, that produced mostly invalid messages, but this is no
longer the case. The best static analyzers today are fast, and they produce selective
and accurate messages. Their use should not be negotiable at any serious software
project.  

The first two rules guarantee the creation of a clear and transparent control flow structure
that is easier to build, test, and analyze. The absence of dynamic memory allocation,
stipulated by the third rule, eliminates a class of problems related to the allocation and
freeing of memory, the use of stray pointers, etc. The next few rules (4 to 7) are fairly
broadly accepted as standards for good coding style. Some benefits of other coding styles
that have been advanced for safety critical systems, e.g., the discipline of “design by
contract” can partly be found in rules 5 to 7.  
These ten rules are being used experimentally at JPL in the writing of mission critical
software, with encouraging results. After overcoming a healthy initial reluctance to live
within such strict confines, developers often find that compliance with the rules does tend
to benefit code clarity, analyzability, and code safety. The rules lessen the burden on the
developer and tester to establish key properties of the code (e.g., termination or
boundedness, safe use of memory and stack, etc.) by other means. If the rules seem
Draconian at first, bear in mind that they are meant to make it possible to check code
where very literally your life may depend on its correctness: code that is used to control
the airplane that you fly on, the nuclear power plant a few miles from where you live, or
the spacecraft that carries astronauts into orbit. The rules act like the seat-belt in your car:
initially they are perhaps a little uncomfortable, but after a while their use becomes
second-nature and not using them becomes unimaginable.
