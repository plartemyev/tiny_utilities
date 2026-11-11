# zcode-build (on-target)

Builds [ZCode](https://github.com/zai-org/ZCode) (Z.ai's open-source coding
agent workspace) **on the target host itself**: checks out the latest
upstream `main`, **strips all telemetry** (assert-driven, see
`strip-telemetry.sh`), builds `pacman` packages and publishes them into a
**local pacman repository** at `~/zcode-build/out`. The `[zcode]` repository
registered in `/etc/pacman.conf` (`Server = file:///home/<user>/zcode-build/out`)
makes a plain `pacman -Syu` pick up every rebuild — no external repo server,
no signing (the packages never leave the machine), no Docker.

These files are package data of archinstaller (`--zcode`): the tool uploads
them to the target right after the first boot, runs the initial build and
installs `zcode` (+ `zcode-desktop` with `--graphical`) from the fresh local
repository. A `zcode-update.timer` **user unit** re-runs `build.sh` nightly
(03:17, `Persistent=true`, journal via `journalctl --user -u zcode-update`);
linger is already enabled by the installer, so the timer runs without a
login session.

Everything lives under `~/zcode-build/`:

| Path | What |
|---|---|
| `build.sh` | orchestrator: checkout → strip → build → package → publish |
| `strip-telemetry.sh` + `strip_telemetry.py` | the telemetry removal (shell parts + manifest/source edits) |
| `verify-stripped.sh` | post-build artifact gate; any hit fails the run |
| `packaging/` | PKGBUILDs, the `/usr/bin/zcode` wrapper, the desktop `.install` |
| `out/` | the published pacman repo: packages + `zcode.db` + `build-stamp.txt` |
| `cache/` | persistent state: upstream git mirror, pinned Node, pnpm/electron caches, gem home |
| `tmp/` | per-run scratch, wiped upfront |

## Packages

- **`zcode`** — the `pnpm build:zcode` distribution (CLI, TUI, web server +
  backend) under `/opt/zcode`, with the **pinned Node runtime vendored** at
  `/opt/zcode/node` (the exact version from upstream's `mise.toml`, verified
  against nodejs.org SHASUMS). `/usr/bin/zcode` execs
  `/opt/zcode/node/bin/node /opt/zcode/bin/zcode.mjs`.
- **`zcode-desktop`** — the Electron app from electron-builder's `pacman`
  target (fpm), re-packed to own the name/versioning, with the
  `chrome-sandbox` setuid bit applied by the `.install` hook. Needs
  `ruby` + `fpm` (installed into `cache/gems`, not the system gem home).

Versioning: `pkgver` = upstream's `package.json` version, `pkgrel` = `1`
for a new upstream version, or the UTC date (`YYYYMMDD`) when the same
version is rebuilt — so the nightly run always compares as newer even when
upstream stood still.

## Manual runs / updates

```bash
~/zcode-build/build.sh                 # same as the nightly timer
sudo pacman -Syu                       # picks the fresh packages up
ZCODE_REF=v3.18.0 ~/zcode-build/build.sh   # pin a tag
ZCODE_DESKTOP=1 ~/zcode-build/build.sh     # desktop too (default: baked
                                           # into the timer at install time)
```

Environment knobs: `ZCODE_REF`, `ZCODE_DESKTOP`, `ZCODE_ELECTRON_MIRROR`,
`ZCODE_CACHE`/`ZCODE_WORK`/`ZCODE_OUT` (paths, default alongside `build.sh`).

## Build dependencies (installed by archinstaller)

`base-devel git python` always; `ruby ruby-rubygems` additionally with
`--graphical` (fpm for electron-builder's pacman target). First run takes
1–2 h and several GB of caches; re-runs are incremental (git fetch + pnpm
store reuse) and typically minutes.

## Telemetry strip policy

The upstream codebase was audited directly; three activation paths exist,
and all are removed or compiled out:

1. **ARMS RUM** (desktop): the `@arms/rum-electron` SDK dependency is
   dropped from the manifests, its patch file deleted, and all import
   sites redirected to a local no-op stub. The business-side `report*ToArms`
   feeders stay but funnel into the stub — inert dead code.
2. **OTLP chain** (agent CLI + desktop main): the telemetry package loses
   `otlp-exporter.ts` and its activation functions, the OTel SDK deps are
   removed from the manifests, the desktop-side TTFT/renderer-action
   exporters are stubbed, and the electron-builder injection/verification
   lists lose their OTel entries.
3. **Event reporting / ARMS endpoints** (`packages/services`): these
   activate only through build-time endpoint injection
   (`ZCODE_ARMS_RUM_ENDPOINT` / `ZCODE_TELEMETRY_REPORT_ENDPOINT` via
   `config/private/`, absent in public checkouts); `build.sh` exports them
   explicitly empty and asserts no `.env` sneaks in.

Deliberately **kept** (verified non-telemetry): `deviceMid` (the
`X-Device-Mid` billing header), the local crash archive, local memory
diagnostics, the `envelope.ttft` protocol field, and `@opentelemetry/api`
(pure types; transitive dep of the Vercel AI SDK).

Every strip edit **asserts its anchor** and fails the build otherwise —
when upstream reorganizes this code, the nightly stops and `pacman -Syu`
keeps serving the last good packages instead of silently shipping telemetry
back. `verify-stripped.sh` then proves the *artifacts* are clean (lockfile
free of the ARMS/OTLP SDK chain; agent bundle, server entry and web dist
free of exporter machinery; the desktop `app.asar` manifest *and* extracted
content free of ARMS/OTLP references).

No third-party AUR packages or fork code are used anywhere — the
`zcode-ce-bin` AUR and the Zcode-CE fork were reviewed as references only.

## Caveats

- The desktop package builds against the target's own glibc — a
  rolling-build rolling-target pairing that is always in sync on Arch.
  The CLI/web package vendors Node and is immune to distro drift.
- `zcode` and official ZCode builds share the `~/.zcode/v2` data directory;
  don't run both against the same workspace simultaneously.
