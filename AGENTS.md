## Tooling notes
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
    - the autologin session-detection `find` must carry `|| true` under the install script's `set -euo pipefail`
      (hit 2026-10-07 on a libvirt target): the current sonicde set is X11-only (`sonic-workspace` ships
      `/usr/share/xsessions/sonicde.desktop`; nothing creates `/usr/share/wayland-sessions/`), and `find` exits 1
      when any of its path arguments is missing — pipefail turns that into a failing `session=$(...)` assignment
      and `set -e` aborts the script with code 1 BEFORE the `[ -z "$session" ]` guard, printing no diagnostic;
      find's partial output (the xsessions hit) still flows through the pipeline, so the fix keeps semantics;
    - rerunning archinstaller against a live ISO that already ran a FAILED install dies at the first step
      (`sfdisk`: "Checking that no-one is using this disk right now ... FAILED"): the failed run leaves
      `/mnt/new-root` (plus `/mnt/new-root/boot`) mounted and the guest swapfile swapon'ed, and sfdisk refuses
      to repartition a busy disk (hit 2026-10-07 on a libvirt target); the install script now releases the
      leftovers itself (`swapoff -a` + `umount -R /mnt/new-root`, both `|| true`, before `wipefs` — no-ops on
      a fresh ISO); the manual fallback is `ssh root@<target> 'swapoff -a; umount -R /mnt/new-root'`;
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
    - GitHub Pages (Fastly) serves **gzip Vary variants** keyed on Accept-Encoding (misdiagnosed for
      a week as "upstreams lying about Content-Length"): with aiohttp's default
      `Accept-Encoding: gzip, deflate`, `sonicde-arch.github.io` answers `content-encoding: gzip` with
      the COMPRESSED Content-Length (sonic-silver-sddm pkg: 7406532 vs raw 7405537; sonicde.db:
      21502 vs 21500) while aiohttp hands the proxy the auto-decompressed body — the relayed CL
      mismatch made pacman 7.x abort with curl error 63 "Maximum file size exceeded" (libalpm sets
      CURLOPT_MAXFILESIZE_LARGE to the db's %CSIZE%; hit 2026-10-06 on a real sonicde sync). Direct
      curl sends no Accept-Encoding and always got the raw object, which is why the artifact looked
      vantage-dependent. Fix: the mirror's upstream ClientSession sends `Accept-Encoding: identity`
      (server.py `on_startup`); a CL/body mismatch can now only be a genuine truncation, which aborts
      the stream and caches nothing (the keep-what-arrived tolerance died with the misdiagnosis);
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
      old root-wipe-through-a-container cleanup step is gone (plain `rm -rf` works); dockerd
      auto-creates a MISSING bind-mount host path (e.g. `./cache` after an `rm -rf`) as
      root:root 0755 at container create, so the next `up` crash-loops the non-root mirror
      (`PermissionError: /var/cache/arch-mirror/tmp` in the startup `os.makedirs`) even with
      the UID/GID override in place — the repo ships an empty `cache/` via
      `cache/.gitignore` (`*` + `!.gitignore`), so fresh clones are safe; after an
      `rm -rf cache` recreate it as the invoking user before `up` (an empty root-owned
      leftover needs no sudo: `rmdir cache && mkdir cache`; documented in README Caveats);
    - host-exposed port is **8282** (since 2026-10-06; was 8080), published as `8282:8080` — 8080 is
      heavily contended by local tools (dev servers, Jenkins, qBittorrent, ...) and 8282 is rarely
      taken (IANA: `libelle`, a rare enterprise tool) while staying below the Linux ephemeral range
      (32768-60999). Deliberate: do not "normalize" back to 8080; the container-internal listen port
      stays 8080 (LISTEN_PORT default, Dockerfile healthcheck, e2e in-network URLs);
    - archinstaller's `--local-mirror` points installs at this mirror: pacman requests the repo
      database named after the pacman.conf **section** (`[xlibre-stable]` → `xlibre-stable.db`),
      while the mirror resolves repos by its own configured names and 404s unknown ones — so the
      extra-repo `Server` lines must use literal mirror repo segments
      (`http://<host-ip>:8282/xlibre/os/$arch`, `.../sonicde/os/$arch`) instead of the `$repo`
      template that works for the mirrorlist-included official repos (wired in
      `archinstaller/script.py`, `_extra_repo_servers`). Host-side helper: `ip -4 route get 1.1.1.1`
      (its `src` field) is the cheap way to get the primary LAN interface's IPv4 for advertising a
      host service to LAN targets.
    - package/db fetch unification (2026-10-06): package misses, first-time db fetches and background
      db refreshes share one `_fetch_upstream` code path in `server.py` (caller holds the per-file
      lock); db first-fetches thereby got package-miss semantics (single-flight, latecomers served
      from cache). Non-obvious constraint: the request handler must NOT hold the per-file lock across
      the FRESH_WAIT wait — the background refresh takes the same non-reentrant asyncio.Lock, so that
      would deadlock the refresh and turn every stale request into a full FRESH_WAIT stall (hence
      double-checked locking only around the first fetch);
    - byte-range (pacman resume) support (2026-10-09, hit live: a first big download
      died mid-stream leaving nothing cached, pacman's retry resumed its `.part`
      with `Range: bytes=N-`, the mirror answered a plain 200, and curl aborts
      exactly that with error 33 - pacman prints "HTTP server does not seem to
      support byte ranges. Cannot resume." and fails the transaction). Serving
      rules now: cached files are sliced locally (206 + Content-Range, 416 +
      `Content-Range: bytes */size` past EOF); on a miss the client's Range is
      relayed upstream and the 206 streams through with NO cache write
      (partials never land in the cache); an upstream that ignores the range
      (200) is still fetched whole into the cache while only the requested
      window is forwarded - the resumer can hit its 10 s low-speed abort on a
      far window (no bytes flow until the chew reaches `start`), but its retry
      then resumes from the now-cached file (self-healing). Peculiarities:
      aiohttp 3.14's `web.FileResponse` handles single ranges natively (cached
      files were never broken), BUT it answers multi-range headers with its own
      416, so `_serve_local` serves unsupported Range forms itself (plain 200
      full body) instead of delegating - otherwise the multi-range answer would
      depend on which code path serves the file; aiohttp 3.14 does NOT suppress
      `StreamResponse` body writes for HEAD (probed: the HEAD reply carried the
      whole "body" on the wire), so both 206 paths guard
      `request.method != "HEAD"`; pacman never sends multi-range/other units,
      so 200-for-unsupported is enough; a stale db + Range skips the
      FRESH_WAIT refresh deliberately (the resume must come from the same
      content the `.part` started with - refresh-then-slice could stitch two
      db generations into one corrupt file);
    - e2e stage 3b covers the resume path (cached 206 slice + uncached 206
      relay, asserting the cache stays untouched); shell gotcha hit there:
      `tail -c +N bigfile | head -c M` inside e2e.sh kills the whole script
      with SIGPIPE (exit 141, silently - no FAIL line) under
      `set -o pipefail` once `head` exits; use `dd bs=1 skip= count=` instead;
    - arm64 / Arch Linux ARM support (added 2026-10-13; verified live via
      manifest inspection + HTTP probes, not docs):
      - the official `archlinux` OCI images are amd64 ONLY (docker.io
        library index lists just amd64 + attestation; ghcr/quay serve
        single-platform manifests) - `FROM archlinux:latest` cannot build
        or run natively on aarch64;
      - community ALARM base images are dead: `agners/archlinuxarm` last
        built 2021-05, `lopsided98/archlinux-docker` discontinued (its
        README's "Arch Linux ARM is nearly dead" is contradicted by live
        package activity - ALARM tracks Arch closely, e.g. python-aiohttp
        3.14.3 built 10 days after the Arch build of the same version);
      - the only sustainable ALARM container base is the official rolling
        rootfs tarball `os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz`
        (HTTP 302 from os.archlinuxarm.org to a country mirror);
        Docker remote `ADD` does NOT auto-extract tarballs -> busybox
        unpack stage in `Dockerfile.alarm`; `FROM --platform=$BUILDPLATFORM
        busybox` keeps the extraction native even in qemu cross-builds
        (the host has qemu-aarch64 binfmt registered, so
        `docker build --platform linux/arm64` works from the dev box);
      - ALARM mirrors serve ONLY the `/$arch/$repo` layout: the Arch-style
        `$repo/os/$arch` form 302s through the `mirror.archlinuxarm.org`
        geo redirector to country mirrors that 404 it (verified
        `core/os/aarch64/core.db` -> 404 vs `aarch64/core/core.db` -> 200);
        the redirector preserves the path, aiohttp follows redirects;
      - ALARM ships no database signatures (`core.db.sig` -> 404) - its
        pacman.conf default `SigLevel = Required DatabaseOptional` covers
        that, same string as Arch's; repos are `core extra alarm aur`
        (not community - merged into extra like upstream Arch);
      - ALARM's `docker` package does NOT pull in `docker-buildx` (optional
        dep): bare installs run the legacy builder, where BuildKit's
        predeclared `$BUILDPLATFORM` is empty and a
        `FROM --platform=$BUILDPLATFORM ...` line dies at parse time with
        `failed to parse platform : "" is an invalid OS component ...`;
        Dockerfile.alarm therefore avoids the BUILDPLATFORM trick (the
        busybox unpack just runs per-stage-platform - emulated on x86
        cross-builds, native on the Pi), and Pi deployments install
        `docker-buildx` anyway (compose builds then use buildkit);
      - ALARM's base tarball ships an ACTIVE pacman download sandbox
        (`DownloadUser = alpm` in /etc/pacman.conf - upstream Arch ships it
        commented): build-time `pacman -Sy` dies with "restricting
        filesystem access failed because Landlock is not supported by the
        kernel!" + "switching to sandbox user 'alpm' failed" (qemu-user
        cannot answer the Landlock probe; the alpm user may be missing in
        the tarball too) - Dockerfile.alarm seds the line out before the
        sync; the mirror never runs pacman at runtime;
      - the ALARM base tarball (unlike Arch's) already occupies GID 1000 -
        `groupadd -g 1000 mirror` fails with "GID '1000' already exists"
        (shadow exit 4); Dockerfile.alarm creates the mirror user with
        `-o` (non-unique ids) - only the numbers matter for the compose
        `user:` mapping anyway, never the names;
      - the ALARM tarball is a bootable-system image: it ships the kernel
        (linux-aarch64), modules, ~1 GB firmware AND their local pacman db
        entries - every build-time -Syu re-downloads the kernel and runs
        depmod + double mkinitcpio (default+fallback initramfs); strip the
        files AND the /var/lib/pacman/local entries at unpack time
        (busybox stage) or the db entries alone make -Syu reinstall them;
        image 6.8 GB -> 1.96 GB, no mkinitcpio hooks ever run (this is the
        same reason the official archlinux rootfs ships kernel-less);
      - in-image test runs (`docker run IMAGE python /app/test_mirror.py`)
        work despite root-owned `/app` because the image has no WORKDIR:
        cwd=/ puts the suite's TMP_BASE at the container's /tmp (1777) -
        disposable-container-safe, but README's "tests write only to
        ./tmp" is a host-perspective claim;
      - ALARM tier in server.py: `ALARM_ARCHES`/`ALARM_REPOS`/
        `ALARM_MIRRORS` (all three emptyable -> tier off); routing is a
        per-arch override map on Repo (`repo_mirrors(repo, arch)` is the
        single mirror-selection point; keep it that way - _fetch_upstream
        and handle_repo's unknown-repo 404 both go through it); ALARM
        clients must use the proxy's `/$repo/os/$arch` mirrorlist form -
        ALARM's native `/$arch/$repo` two-segment form would hit the
        3-segment local fallback and swap repo/arch.
    - Docker embedded-DNS snapshot vs roaming hosts (2026-10-13, diagnosed
      from a real "pacman said nothing to do while 4 days of updates were
      pending" incident): dockerd's resolver (127.0.0.11) snapshots the
      HOST nameservers at container CREATE and never refreshes them (see
      the container resolv.conf `ExtServers: [host(...)]` comment); a host
      roam leaves the container querying a dead resolver with a FIXED ~4 s
      failover (measured: blackhole-first + alive-second = 4.03 s per
      lookup; not configurable anywhere) while the host itself resolves
      fine - upstream db refreshes then all fail and the design's
      stale-serve past FRESH_WAIT does the rest silently. Fix (baked in):
      bypass the embedded resolver with a bind-mounted /etc/resolv.conf
      (`dns-resolv.conf` + the docker-compose.yml volume) and manage it
      from the host like archinstaller manages its guests' DNS:
      - docker honors the mount verbatim (never rewrites it);
      - glibc hot-reloads the file: a long-running python process picked
        up an in-place rewrite within one lookup (verified with a probe
        loop, `tmp/resolv_probe.py`) - NO container restarts (a restart
        would abort in-flight downloads for nothing);
      - per-server failover becomes glibc-controlled: `options timeout:1
        attempts:2` (dead-first penalty ~2 s for A+AAAA vs 4 s embedded) -
        this is why the embedded resolver had to go: its timeout is not
        tunable and the user wanted 1 s local-first failover;
      - glibc reads at most MAXNS=3 nameservers - cap the list;
      - single-FILE bind mounts track the inode: mv / `sed -i` (rename)
        swap the file out from under the mount - only in-place writes
        (`printf > file`; `cmp -s` for idempotence) are safe;
      - `dns-roam-hook.sh` (NM dispatcher hook, install as
        /etc/NetworkManager/dispatcher.d/90-arch-cache-mirror-dns) rewrites
        the file on up|reapply|dhcp[46]-change|manual events: flock-
        serialized (ACM_DNS_LOCK override for non-root test runs), target
        path resolved via `docker inspect` .Mounts (no hardcoded paths),
        loop-free (it never touches NM state); lease servers come from
        $DHCP[46]_DOMAIN_NAME_SERVERS env or a `nmcli -f DHCP[46] dev show`
        parse - the `-g DHCP4.DOMAIN-NAME-SERVERS` field DOES NOT EXIST
        (allowed group field is only DHCP4.OPTION) and the parse must
        exclude the requested_domain_name_servers echo lines
        (`s/.*[^_a-z]domain_name_servers *= *//p`); each lease server is
        probed with `timeout 1 drill archlinux.org @srv` before inclusion,
        publics (1.1.1.1, 8.8.8.8) always fill the remaining slots;
      - the image healthcheck additionally runs `getent hosts
        archlinux.org`, so DNS breakage shows as unhealthy in `docker ps`
        instead of being discovered through pacman behavior;
      - server.py fixes from the same audit: a 304 revalidation now
        renews the cached db's mtime (os.utime) - previously an unchanged
        upstream db was re-validated on EVERY sync past DB_TTL forever
        (sonicde.db sat with an Oct 9 mtime despite repeated successful
        304s; the If-Modified-Since forward-move stays correct: newer
        than an unchanged upstream file -> 304 again, changed upstream ->
        200); _handle_metadata's serving line is outcome-aware:
        mtime-renewed -> "db refreshed from upstream",
        finished-but-failed -> "db stale, upstream refresh failed" (the
        old unconditional line lied on quick-fail upstreams - DNS-dead
        upstreams were slow enough to mask it, which is why it never
        showed in the logs);
      - diagnosis helpers kept: `tmp/resolv_probe.py` (long-running glibc
        hot-reload probe) + `tmp/resolv-test.conf` (throwaway resolver
        file for the probe container).
    - sonicde upstream REPUBLISHES package files in place (verified
      2026-10-18: one rebuild batch replaced 6 existing filenames at
      once - e.g. sonic-frameworks-io-fuse-6.0.0-2 went 88614 -> 88327 B
      with a new sha256, Last-Modified 2026-10-13 19:07 GMT on all six,
      no pkgrel bump): the mirror's package-immutability cache kept
      serving the old bytes while clients' refreshed dbs carried the new
      %CSIZE%, so libalpm's curl max-file-size (= db CSIZE) aborted every
      attempt with "Maximum file size exceeded" (curl error 63; the log
      shows repeated cache `hit`s, one per pacman retry) - and the stale
      `.sig` would have failed signature verification anyway. Not the
      2026-10-06 gzip-variant bug (cached file was valid zstd;
      `Accept-Encoding: identity` was already in effect). server.py now
      validates the package cache against every landed db generation
      (`_validate_repo_cache`, both first-fetch and background-refresh
      hooks): a db-listed filename with a different on-disk size is
      pruned with its `.sig` (size-only check - catches every observed
      case without hashing GBs; same-size republish remains theoretical),
      not-in-db entries stay GC/KEEP_VERSIONS territory;
      `test_republish_prune` locks it. Forensics recipe: tarfile over
      `cache/<repo>/os/<arch>/<repo>.db`, compare %CSIZE%/%SHA256SUM%
      against the cached files, `curl -sI` the upstream URL for
      Last-Modified.
