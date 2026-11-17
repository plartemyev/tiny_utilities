# zcode-build (on-target)

Builds [ZCode](https://github.com/zai-org/ZCode) (Z.ai's open-source coding
agent workspace) **on the target host itself**: checks out the latest
upstream **tagged release**, **strips all telemetry** (assert-driven, see
`strip-telemetry.sh`), **patches the standalone-web project flow**
(assert-driven, see `patch_standalone_web.py`), builds `pacman` packages and
publishes them into a
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
| `build.sh` | orchestrator: checkout → strip → patch → build → package → publish |
| `strip-telemetry.sh` + `strip_telemetry.py` | the telemetry removal (shell parts + manifest/source edits) |
| `patch_standalone_web.py` | the standalone-web local-project patch (source-level, assert-driven) |
| `verify-stripped.sh` | post-build artifact gate; any hit fails the run |
| `packaging/` | PKGBUILDs, the `/usr/bin/zcode` wrapper, the desktop `.install` |
| `out/` | the published pacman repo: packages + `zcode.db` + `build-stamp.txt` |
| `cache/` | persistent state: upstream shallow checkout (`src/`), pinned Node, pnpm/electron caches, gem home |
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
ZCODE_REF=v3.17.1 ~/zcode-build/build.sh   # pin an explicit ref (default:
                                           # the latest version tag)
ZCODE_DESKTOP=1 ~/zcode-build/build.sh     # desktop too (default: baked
                                           # into the timer at install time)
```

Environment knobs: `ZCODE_REF`, `ZCODE_DESKTOP`, `ZCODE_ELECTRON_MIRROR`,
`ZCODE_WEB_LOCAL_PROJECTS` (standalone-web project/storage-parity patch,
default on; a flip also needs `ZCODE_FORCE=1` — the stamp does not record
it), `ZCODE_AUTH_FALLBACK` (coding-plan business-token reuse, default on),
`ZCODE_SKIP_FETCH=1` (degraded-network escape hatch: resolve REF from
already-fetched local tags, skip `git fetch` entirely),
`ZCODE_CACHE`/`ZCODE_WORK`/`ZCODE_OUT` (paths, default alongside `build.sh`),
`ZCODE_FORCE=1` (rebuild even when the up-to-date check passes),
`ZCODE_SHALLOW=0` (full history fetch, for exotic refs like old commit
SHAs), `ZCODE_UPSTREAM_URL` (alternate upstream/mirror).

## Speed profile (measured on a 4 vCPU / 8 GiB libvirt target)

The first run pays everything: shallow upstream clone (~18.6k files), the
multi-GB pnpm dependency download, the Electron binary and the full
TS/bundler build. Measured end-to-end on the reference target: **~14 min**
with a warm pnpm store, ~20 min fully cold — nowhere near the 1–2 h first
guesses. Everything below `cache/` persists across builds and reboots
(pnpm store 2.8 GiB, checkout 1.3 GiB, pinned Node 229 MiB), so re-runs
download nothing and pay only the CPU cost (~13 min).

On top of that, `build.sh` early-exits after the fetch when the latest
tagged release is the one already built (recorded in
`out/build-stamp.txt` together with the strip-script hash and the desktop
flag) — upstream standing still makes the nightly a no-op that costs one
`git fetch` and a few seconds. Verified live: a manual re-run right after
an install exits with `up to date`. `ZCODE_FORCE=1` overrides.
`pnpm install` runs with `--prefer-offline`, so a warm store also skips
the registry round-trips.

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

## Standalone-web local-project patch

Upstream defect [zai-org/feedback#1161](https://github.com/zai-org/feedback/issues/1161)
(open, P2): `zcode --web` (standalone self-hosted server) cannot create
projects or start conversations — the composer's every send fails with
`project.remote-project-required` and the "Create project" folder picker
with `project.host-offline`. Root cause: the standalone server assembles its
services with a remote-style `ownerHostId`
(`createServerHostServices`, `packages/services/src/node.ts`) while the web
client addresses the machine it talks to as `local`; the standalone server
has no `resolveHost`, so every `local` request dies.

`patch_standalone_web.py` (runs after the strip, before the build; disable
with `ZCODE_WEB_LOCAL_PROJECTS=0`) fixes the gates in
`packages/services/src/project/index.ts`, at source level — the community
workaround in the issue hand-edits the built `server/entry-http.js` instead,
which we cannot do since we compile from source:

1. `route()` resolves the browser's `local` to the server's own service
   (folder picker and every host-scoped read work);
2. `saveProject` drops the client `local` alias before the repository call,
   so the `project.host-immutable` check passes and the row is stored under
   the server's own host partition (`project-repository.ts` is NOT touched);
3. every `VirtualProject` row leaving the service (saveProject response,
   readProjects, readTree, restoreProject) is presented with
   `hostId: "local"` via a `presentProject` helper — otherwise
   `ProjectCreation.saved()` throws the false
   `remote-project.host-removed` right after a successful save, and
   composer pickers / automation lists filter the rows out as
   foreign-host entries;
4. **storage partition parity** (`createServerHostServices` in
   `packages/services/src/node.ts`): the server joins the desktop's
   `"local"` project/task partition instead of its remote-style identity.
   This is what actually makes the web and desktop UIs show the SAME
   projects and tasks out of the shared `~/.zcode/v2` store — before it,
   desktop-created projects were invisible in the web UI and vice versa
   (two disjoint partitions of one SQLite store). With parity in place the
   runtime behaves desktop-local: project-less composer sends work
   out of the box, and the presentation shims in (1)/(3) go inert.
   Caveat: desktop→server REMOTE connections (this server addressed as a
   remote host from another machine's desktop) are not exercised with
   parity mode; the server's advertised serverId itself is unchanged.

Scope and lifecycle, by construction:

- desktop remote hosts have `resolveHost` → `isStandaloneServer` is false
  there and the alias never fires; the alias also goes inert the moment
  upstream supplies a `resolveHost` of its own (their future proper fix);
- the upstream policy is kept, not deleted: sessions on the standalone
  server still require a project (`remote-project-required`), so the
  composer needs a selected project — create/select one for the
  `--workspace` directory (or any server directory) and send;
- every edit asserts its anchor; when upstream fixes or reorganizes this
  code the nightly stops and keeps serving the last good packages — at that
  point delete the patch call (and this section) after confirming their fix;
- `verify-stripped.sh` re-checks the patch state in the compiled-from
  source (the artifacts are minified, the comment markers only exist in the
  source tree): present when enabled, absent when disabled.

## Coding-plan auth fallback patch

Separate upstream gap, same "standalone CLI/web vs desktop" family
(`patch_coding_plan_auth.py`; disable with `ZCODE_AUTH_FALLBACK=0`): turns
failed on the standalone CLI and the web server's spawned runtime with
`project_token_login_failed` while the desktop on the same box with the
same stored credentials worked. Cause: the login flow persists the
`/api/auth/z/login` **business** platform JWT as `oauth:zai:access_token`
(zaiProviderAdapter normalizes at login; the store contract is business
token), but the standalone runtime's coding-plan resolver re-exchanges that
stored token at `/api/auth/z/login` — which only accepts raw Z.AI OAuth
tokens (`200 {code:500, "Z.ai user information is invalid"}`) — and treats
the rejection as fatal. The desktop is unaffected because its host hands
tokens to its agent instead of re-exchanging.

Live-verified 2026-11-18: the stored token is rejected by
`/api/auth/z/login` yet accepted by the business APIs it exists for
(`GET /api/biz/customer/getCustomerInfo` → `code:200` with the org/project
list). The patch turns the exchange failure into a fall-through
(`loginToken = business?.token ?? oauth`, a line upstream already has), so
the stored business token is used directly; raw-OAuth-token stores still
refresh through the exchange as before, and expired tokens surface through
client.resolve's own 401 handling. The desktop path is untouched.

Verified live on 2026-11-17 (v3.18.2, target code-factory-m): with the
patched build, browser project creation via the folder picker, project
selection (composer chip and picker after reload) and conversation send all
pass; the server journal shows `project.readDirectory OK`,
`project.saveProject OK` and `project.prepareSession OK` with ZERO
`project.remote-project-required` / `project.host-offline` /
`remote-project.host-removed` / `project.host-immutable` occurrences, where
the unpatched 3.18.2 build reproduced the defect pair first (baseline). The
remaining send failures on that target are the model layer: its stored z.ai
OAuth token is stale (api.z.ai answers "Z.ai user information is invalid")
— a fresh `/login zai` (CLI) or desktop re-login is needed for real model
turns; that is target auth state, not patch-related.

## Caveats

- The desktop package builds against the target's own glibc — a
  rolling-build rolling-target pairing that is always in sync on Arch.
  The CLI/web package vendors Node and is immune to distro drift.
- `zcode` and official ZCode builds share the `~/.zcode/v2` data directory;
  don't run both against the same workspace simultaneously.
- **`zcode --web` (standalone web mode) cannot start conversations in
  3.17.x — upstream defect, not a build problem** (verified 2026-11-12 on
  3.17.2, target code-factory-m): the composer shows "Select project", every
  send fails with `Failed to send. Try again later.` / `草稿会话创建失败，请重试`,
  and the server journal shows `sendConversationCommandV4 FAIL
  Error: project.remote-project-required` (session creation; the standalone
  server's project storage owner is a remote-style host id, so sessions
  require a registered project) plus `project.readDirectory FAIL
  Error: project.host-offline` (the "Create project" folder picker routes to
  a nonexistent local host). "Work outside a project" is desktop-only and
  does nothing here; `--workspace <path>` only advertises the default
  workspace and does not bypass the check. Known upstream:
  [zai-org/feedback#1161](https://github.com/zai-org/feedback/issues/1161)
  (open, P2), independently documented by exe.dev's ZCode deploy guide with
  the identical error pair on 3.17.1; upstream's packaging notes say the web
  build is smoke-tested without a browser session. The desktop from the same
  build works (its host is `local`, exempt from the remote-project rules).
  Still no fix as of v3.18.2 (tagged 2026-11-13; re-checked 2026-11-17):
  the v3.18.0→v3.18.2 sync commits touch 148 files but none of
  `packages/server/` (entry-http), `packages/zcode-server-cli/`,
  `packages/services/src/remote-projects/` or
  `packages/services/src/project-storage/remote-policy.ts` — the policy
  gate still throws `project.remote-project-required` for non-`local`
  owners. A 2026-11-12 issue comment documents three more same-root-cause
  gates (`readRemoteProjectDirectory` SQL hides the self-host →
  `remote-project.host-removed` false error after save; the
  `project.host-immutable` second gate; container `hostname()` serverId
  drift — set `ZCODE_SERVER_ID` in containers) plus a verified temp patch
  on the distributed `server/entry-http.js` (allow `local` in `route()`,
  in the `host-immutable` check, and rewrite `saveProject` responses to
  `hostId: "local"`) — project creation and directory browsing work after
  it. No maintainer response on the issue yet. Since 2026-11-17 the build
  carries our own source-level patch for exactly these gates — see the
  standalone-web section above; the desktop from the same build was never
  affected. When upstream ships their own fix, the patch script's anchors
  are expected to fail the build (or go inert), at which point the patch
  gets retired.
