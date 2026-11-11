# zcode-build

Private build infrastructure for [ZCode](https://github.com/zai-org/ZCode)
(Z.ai's open-source coding agent workspace): a nightly job checks out the
latest upstream `main`, **strips all telemetry**, builds signed pacman
packages and serves them from a local repository. Targets installed with
`archinstaller --zcode` get their ZCode from this repository, and plain
`pacman -Syu` picks up the nightly rebuilds.

No third-party AUR packages or fork code is used anywhere in the pipeline —
the `zcode-ce-bin` AUR (a repackaging of the Zcode-CE community fork) was
**reviewed as a reference only**: its PKGBUILD-shaped packaging decisions
(pacman-target artifact, chrome-sandbox setuid in `.install`, `!strip`)
and the fork's telemetry audit informed our own implementation, which was
then re-derived from the upstream sources.

## Layout

| Path | What |
|---|---|
| `Dockerfile` | builder image (`archlinux:latest` + git/makepkg/fpm toolchain) |
| `Dockerfile.repo` | repo server image (`archlinux:latest` + busybox httpd) |
| `docker-compose.yml` | long-running repo server, published on port **8283** |
| `build.sh` | in-container orchestrator (checkout → strip → build → package → repo-add) |
| `strip-telemetry.sh` | the telemetry removal, assert-driven (see below) |
| `verify-stripped.sh` | post-build artifact gate; any hit fails the nightly run |
| `packaging/` | PKGBUILDs, the `/usr/bin/zcode` wrapper, the desktop `.install` |
| `nightly.sh` | host-side cron entrypoint (flock, image rebuild, docker run) |
| `repo/` | served repository: `zcode.db{,.sig}`, packages, `zcode-repo.asc`, `healthz` |
| `cache/` | persistent volume: upstream git mirror, pinned Node, pnpm/electron caches, GPG home |
| `gnupg/` | the repository signing key (generated on first run, kept forever) |

## Packages

- **`zcode`** — the `pnpm build:zcode` distribution (CLI, TUI, web server +
  backend) under `/opt/zcode`, with the **pinned Node runtime vendored** at
  `/opt/zcode/node` (the exact version from upstream's `mise.toml`, verified
  against nodejs.org SHASUMS). Upstream builds and prebuilds its native
  modules against that pin, and the Arch `nodejs` package drifts
  independently (26.x while upstream pins 24.x), so the package carries its
  own runtime and depends on nothing. `/usr/bin/zcode` execs
  `/opt/zcode/node/bin/node /opt/zcode/bin/zcode.mjs`.
- **`zcode-desktop`** — the Electron app from electron-builder's `pacman`
  target (fpm), re-packed to own the name/versioning, dropping the
  artifact's `usr/bin` entry (it would collide with the CLI package's
  `/usr/bin/zcode`; ours is `/usr/bin/zcode-desktop`), with the
  `chrome-sandbox` setuid bit applied by the `.install` hook — packaging
  normalization strips setuid bits, so it must land at install time (same
  reason the upstream `.deb` ships a postinst). `depends=(gtk3 nss libxss
  libxtst libnotify alsa-lib mesa xdg-utils)`, mirroring electron-builder's
  computed closure. No autostart: it only appears in menus.

Versioning: `pkgver` = upstream's `package.json` version, `pkgrel` = `1` for
a new upstream version, or the UTC date (`YYYYMMDD`) when the same version
is rebuilt — so a same-day manual re-run or a strip-script update still
compares as newer to pacman. Old package files are pruned after `repo-add`.

## Telemetry strip policy

The upstream codebase was audited directly (not via the fork's claims);
three activation paths exist, and all are removed or compiled out:

1. **ARMS RUM** (desktop, `@arms/rum-electron`): the SDK dependency is
   dropped from the manifests, its patch file deleted, and all import
   sites redirected to a local no-op stub (`armsRumStub.ts`). The
   business-side `report*ToArms` feeder modules stay but funnel into the
   stub — inert dead code.
2. **OTLP chain** (agent CLI + desktop main): the telemetry package loses
   `otlp-exporter.ts` and its activation functions (stubbed to dead), the
   OTel SDK deps are removed from the manifests, the desktop-side
   TTFT/renderer-action exporters are stubbed, and the electron-builder
   injection/verification lists lose their OTel entries.
3. **Event reporting / ARMS endpoints** (`packages/services`
   `telemetryCore`, `appARMSBootstrap`): these activate only through
   build-time endpoint injection (`ZCODE_ARMS_RUM_ENDPOINT` /
   `ZCODE_TELEMETRY_REPORT_ENDPOINT` via `config/private/`, which does not
   exist in public checkouts). `build.sh` exports them explicitly empty and
   asserts no `.env`/`.env.local`/`config/private` sneaks in.

Deliberately **kept** (verified non-telemetry, matching the CE audit):
`deviceMid` (`X-Device-Mid` billing header), the local crash archive
(upstream already builds with `uploadToServer: false`), local memory
diagnostics, the `envelope.ttft` protocol field, and `@opentelemetry/api`
(pure types here; transitive dep of the Vercel AI SDK).

Every strip edit **asserts its anchor** and fails the build otherwise —
when upstream reorganizes this code, the nightly stops and the repository
keeps serving the last good packages instead of silently shipping
telemetry back. `verify-stripped.sh` then proves the *artifacts* are clean
(lockfile free of `@arms/` and the OTLP SDK chain; agent bundle, server
entry and web dist free of exporter machinery; the desktop `app.asar`
manifest *and* extracted content free of ARMS/OTLP references).

## Repository serving and trust

- The repo server is a `busybox httpd` container publishing `./repo`
  read-only on port **8283** (adjacent to the arch-cache-mirror's 8282;
  IANA-unassigned, unprivileged, below the ephemeral range). Byte-range
  support means pacman resume works.
- Packages and the database are GPG-signed (`repo-add --sign`) with a key
  generated on first nightly run and persisted in `gnupg/`. The public key
  is exported to `repo/zcode-repo.asc`. archinstaller fetches it, imports
  it with `pacman-key --add` and locally signs it, reading the fingerprint
  from the `.asc` at install time (the key is host-specific, so the id
  cannot be pinned in the installer).
- Losing `gnupg/` means re-signing under a new key: targets must re-run
  the `pacman-key` import/lsign for the `[zcode]` repo to validate again.

## First run / nightly schedule

```bash
# one-time: build images, generate the key, run the first build (~1-2 h and
# several GB of caches on first ever run)
./nightly.sh

# watch it
tail -f tmp/nightly-$(date +%Y%m%d).log
```

Cron entry (any user with docker access is enough):

```
17 3 * * * /path/to/zcode-build/nightly.sh
```

`nightly.sh` is flock-guarded (no overlapping runs), rebuilds the builder
image only when the scripts changed, keeps the repo server up
(`docker compose up -d repo`) and runs the build container as the invoking
user so `repo/` and `cache/` stay host-user owned.

Manual runs / debugging:

```bash
ZCODE_REF=origin/main ./nightly.sh          # default ref
ZCODE_REF=v3.18.0 ./nightly.sh              # pin a tag
ZCODE_ELECTRON_MIRROR=... ./nightly.sh      # override the electron mirror
```

## Host firewall

LAN targets reach the repository through the host firewall; open the port
once (the archinstaller `--zcode` preflight prints the same remedy):

```bash
firewall-cmd --permanent --add-port=8283/tcp && firewall-cmd --reload
```

## Caveats

- The desktop package is built on `archlinux:latest` (current glibc); as
  with any rolling-build rolling-target pairing, a target that lags far
  behind may need a mirror-sync first. The CLI/web package vendors Node and
  is immune to distro drift.
- The whole upstream toolchain (pnpm workspace, electron-builder, npmmirror
  downloads) is network-hungry on first run; the `cache/` volume makes
  subsequent nightly runs incremental.
- `zcode` and official ZCode builds share the `~/.zcode/v2` data directory;
  don't run both against the same workspace simultaneously.
