# arch-cache-mirror

A caching Arch Linux repository mirror for the home LAN, shipped as a
single Arch-based Docker image. Point every machine's
`/etc/pacman.d/mirrorlist` at it once and all of them download packages
and databases from your LAN; the upstream mirrors are only hit on the
first request of any file.

```
LAN clients (pacman)                 arch-cache-mirror (Docker)         upstream mirrors
+-----------------+   GET /extra/os/x86_64/   +----------------------+   +-------------------+
| Server =        |  htop-3.5.3-1-...pkg.zst | cache hit?  -> serve |-->| geo.mirror.pkgbuild.com
| http://nas:8282 | -----------------------> | miss?       -> stream|-->| mirror.rackspace.com
| /$repo/os/$arch |    bytes as they arrive  |  to client + to cache|-->| packages.xlibre.net/arch/stable
+-----------------+                          +----------------------+   | sonicde-arch.github.io
                                                                          +-------------------+
```

Behaviour per request:

- **package files** (`*.pkg.tar.*`, immutable by design) are served
  straight from the cache when present; on a miss they are *streamed to
  pacman while being downloaded* from the first reachable upstream
  mirror and land in the cache at the same time. The cache only ever
  gains complete files: downloads are written to a temp file and
  atomically renamed into place.
- **databases** (`.db`, `.files`, `.db.sig`, `.files.sig`) are the
  metadata pacman only requests on a sync, so a request for a copy older
  than `DB_TTL` triggers a **fresh upstream retrieval that the requesting
  client waits for**.  The wait is bounded by `FRESH_WAIT` (default 5 s):
  if the upstream is slower than that (or dead), the cached copy is
  served immediately - a slow mirror can never trip pacman's 10 s
  low-speed abort - while the retrieval continues in the background for
  the next client.  Copies younger than `DB_TTL` are served without
  upstream contact (that is what keeps N simultaneous `-Syu`s to a
  single upstream fetch); a first-time fetch (nothing cached yet) blocks
  unconditionally with the package-miss semantics: one shared download
  under the per-file lock, streamed to the requesting client while it
  fills the cache - concurrent clients wait for it and are then served
  from the cache.
- the repository -> upstream mapping is built at startup from
  environment variables; `core`/`extra`/`multilib` come with sensible
  defaults, `xlibre` and `sonicde` are preconfigured.
- concurrent requests for the same file are served by one shared
  download (per-file locks), so five machines running `pacman -Syu` at
  once still produce a single upstream fetch per file.

## Quickstart

On the box that will host the cache (any machine with Docker; host port
8282 is published to the container's 8080 - deliberately uncommon and
below the 32768-60999 ephemeral range - and must be reachable from the
LAN):

```bash
cd arch-cache-mirror
env UID=$(id -u) GID=$(id -g) docker compose up -d --build     # cache persists in ./cache/
```

On every Arch machine of the house, put this as the **first** line of
`/etc/pacman.d/mirrorlist`:

```
Server = http://<host-ip>:8282/$repo/os/$arch
```

and attach the extra repositories in `/etc/pacman.conf` (they reuse the
same mirrorlist entry - `$repo` is substituted per section):

```ini
[xlibre]
Include = /etc/pacman.d/mirrorlist

[sonicde]
Include = /etc/pacman.d/mirrorlist
```

Then `pacman -Syu` as usual. Check `curl http://<host-ip>:8282/` for a
status page (configured repos, cache size, last GC) and `docker logs`
for per-request hit/miss lines.

The extra repos bring their own signing keys, and the proxy does not
change anything about them (it only shuffles bytes, including `.sig`
files - verification happens on your machine, exactly as with the
upstream directly). With the stock `SigLevel = Required
DatabaseOptional` (the pacman default), `pacman -Sy` works right away -
a missing *database* signature is fine - and installing a package from
them asks for the repo owner's key once. Import it as described on the
respective repo's page; typically (the key id is shown in pacman's
"unknown trust" error output, and `<repo>` is `xlibre`/`sonicde`):

    sudo pacman-key --recv-keys <KEYID>
    sudo pacman-key --lsign-key <KEYID>

Keep the default SigLevel for real machines. `SigLevel = Never` would
switch package verification for those repos off entirely and is not
used or recommended anywhere here (it exists only inside `e2e.sh`, for
its disposable test client).

Without docker compose:

```bash
docker build -t arch-cache-mirror .
docker run -d --name arch-cache-mirror -p 8282:8080 \
    --user "$(id -u):$(id -g)" \
    -v /var/cache/arch-mirror:/var/cache/arch-mirror \
    -e OFFICIAL_MIRRORS='https://geo.mirror.pkgbuild.com/$repo/os/$arch https://mirror.rackspace.com/archlinux/$repo/os/$arch' \
    -e 'EXTRA_REPOS=xlibre=https://packages.xlibre.net/arch/stable/$arch;sonicde=https://sonicde-arch.github.io/$arch' \
    arch-cache-mirror
```

The `-e` lines carry the repo configuration that compose provides; without
them the mirror serves the official repos only (their mirrors default in
code), while the extra repositories are deployment configuration whose
home is docker-compose.yml.

## Configuration (environment)

| Variable           | Default                                    | Meaning                                                                                              |
|--------------------|--------------------------------------------|------------------------------------------------------------------------------------------------------|
| `LISTEN_ADDR`      | `0.0.0.0`                                  | listen address                                                                                        |
| `LISTEN_PORT`      | `8080`                                     | listen port                                                                                           |
| `CACHE_DIR`        | `/var/cache/arch-mirror`                   | cache root (mirrors the URL layout: `<repo>/os/<arch>/<file>`)                                        |
| `CACHE_SIZE`       | `0`                                        | total cache size cap, e.g. `20G`, `500M`; `0` = unlimited; once exceeded, oldest files are deleted until 90% of the cap |
| `CACHE_AGE`        | `0`                                        | delete files untouched for this long, e.g. `30d`, `12h`; `0` = never                                  |
| `KEEP_VERSIONS`    | `0`                                        | superseded package versions to keep per package+arch (ordering uses pacman's own version comparison); `0` = only the latest |
| `GC_INTERVAL`      | `3600`                                     | seconds between pruning passes                                                                        |
| `DB_TTL`           | `10m`                                      | max age of cached db copies; requests for older copies fetch fresh from upstream; `0` = on every request |
| `FRESH_WAIT`       | `5`                                        | max seconds such a db request waits for the fresh retrieval before being served the cached copy; `0` = serve cached immediately |
| `OFFICIAL_REPOS`   | `core extra multilib`                      | repos served from `OFFICIAL_MIRRORS`                                                                  |
| `OFFICIAL_MIRRORS` | geo.mirror.pkgbuild.com, mirror.rackspace.com (code default; also pinned in docker-compose.yml; space-separated, tried in order) | upstream URL templates containing `$repo` and/or `$arch` |
| `EXTRA_REPOS`      | *none in code* — defined in docker-compose.yml | additional repos as `name=url` pairs separated by `;` or newlines; the url is a template containing `$arch` |

The extra repositories are **deployment configuration, not code**:
`docker-compose.yml` ships them via `EXTRA_REPOS` (note the `$$`
escaping compose requires):

```
xlibre  = https://packages.xlibre.net/arch/stable/$arch
sonicde = https://sonicde-arch.github.io/$arch
```

The proxy serves every repository under the uniform local layout
`/<repo>/os/<arch>/<filename>` regardless of the upstream's layout, so
one mirrorlist line covers all of them. A three-segment local layout
`/<repo>/<arch>/<filename>` works too.

## Cache pruning

A periodic pass (`GC_INTERVAL`, also run ~30 s after startup):

1. **version retention** - groups package files by (repo, arch,
   pkgname) and keeps the newest `KEEP_VERSIONS + 1` versions, deleting
   the rest together with their `.sig`. Version ordering is an exact
   port of pacman's `vercmp` (differentially tested against the
   `vercmp` binary over thousands of version pairs), so the proxy and
   pacman always agree on which version is newest - including oddities
   like `1.0rc1 < 1.0` vs `1.0.rc1 > 1.0` and epoch handling.
2. **age limit** (`CACHE_AGE`) - files whose mtime (== last download
   time) is older than the limit go away; dbs are exempt in practice
   because refreshes touch them.
3. **size limit** (`CACHE_SIZE`) - when the total exceeds the cap, the
   oldest files are deleted until the total is back to 90% of the cap.

Leftover temp files from crashed downloads are swept after 24 h. Files
currently being downloaded are never touched.

## Why a docker-compose file is worth it

`docker compose up -d --build` is the whole operation: image build,
port publishing, cache volume, restart policy (`unless-stopped` keeps
the mirror alive across host reboots) and environment configuration in
one reviewed file instead of a long `docker run` incantation. It also
makes the three operational must-haves explicit and durable: the
bind-mounted `./cache` (so the cache survives image upgrades), the
uid:gid mapping to the calling host user (so the cache stays
host-user owned) and the env defaults. Healthcheck comes from the Dockerfile (a stdlib-only
`/healthz` probe), so `docker ps` shows mirror health without extra
packages. The only cost is the compose plugin itself, which ships with
Docker everywhere nowadays.

## Caveats

- Plain HTTP on the LAN, no authentication - by design, like every
  pacman mirror; do not expose it to the internet. The container runs as
  a non-root `mirror` user (uid/gid 1000); docker-compose.yml maps that
  to the calling host user (`user: "${UID:-1000}:${GID:-1000}"`), so the
  bind-mounted `./cache` stays owned by your user. On the common
  single-user host (uid 1000) this just works; otherwise put `UID`/`GID`
  in a `.env` file next to `docker-compose.yml`
  (`env UID=$(id -u) GID=$(id -g) docker compose up` also works). A
  mismatch fails loudly: the mirror cannot write the cache dir and
  exits. An empty `cache/` ships in the repository (kept via
  `cache/.gitignore`; its runtime contents stay ignored), so a fresh
  clone already has a user-owned cache dir. If you delete it later,
  recreate it before `up`: `mkdir cache` - when `./cache` is missing at
  container create, dockerd auto-creates the bind-mount source as
  `root:root` (the daemon runs as root), which trips exactly that
  PermissionError crash-loop (an empty root-owned leftover needs no
  sudo: `rmdir cache && mkdir cache`).
- If you keep real upstream mirrors below the proxy line in
  `mirrorlist`, pacman will use them as fallback when the proxy is
  down (nice), but the same file must not be `Include`d by the extra
  repos (their Server lines would 404 noisily there). Either keep the
  mirrorlist proxy-only, or use a second file for the official repos.
- A db first-fetch (repo not cached at all) streams to the client while
  it downloads - bytes flow continuously, but pacman shows an unknown
  size for that one transfer (chunked, since some upstreams lie about
  Content-Length). Concurrent first requests for the same file share the
  one download, exactly like package misses. Definitive
  upstream 404s are negative-cached for 5 minutes (`NEGATIVE_TTL_SECONDS`
  in `server.py`): a `.db.sig` that starts to exist upstream, or a
  package released mid-window, is picked up after at most that long.
- Metadata freshness: a sync always *triggers* a fresh retrieval for
  stale dbs and delivers it whenever upstream answers within
  `FRESH_WAIT`; only when the upstream is slower than that does a
  client see the cached copy (and the fresh one lands for the next
  sync). Set `FRESH_WAIT=0` for strictly-non-blocking behavior or
  raise it if your upstream is reliably slow.
- Some upstreams declare a wrong `Content-Length` (observed on a
  GitHub Pages edge serving `sonicde.db` a few bytes short): since dbs
  are downloaded whole and served from the cache file, clients never
  notice; the truncated body is accepted and logged with a warning.
- On upstream mirror rotation the local layout stays stable; clients
  never need a mirrorlist change.

## Development

`server.py` is a single-file aiohttp app; `test_mirror.py` covers the
pure logic (version comparison, size/duration parsing, GC passes,
env parsing) plus a loopback integration test with a stub upstream
(cache miss streaming, cache hit, fresh-on-request db retrieval, the
FRESH_WAIT stale fallback, short-body upstream, 404 pass-through with
negative caching, unknown repo, same-file single-flight). Tests need
`aiohttp` and write only to `./tmp`:

```bash
python test_mirror.py             # host, needs aiohttp
docker run --rm arch-cache-mirror python /app/test_mirror.py
```

The version-comparison port is additionally verified by a differential
test against the `vercmp` binary from the `pacman` package (2500
version pairs, 0 mismatches at the time of writing).

### End-to-end test

`./e2e.sh` exercises the real thing: it builds the image, runs the
in-image unit/integration tests (as the non-root `mirror` user), boots
the mirror on a throwaway docker network - as the uid:gid mapped from
`docker-compose.yml` - next to a genuine `archlinux:latest` client and
checks the full path - health/status endpoints, db cache miss →
upstream fetch → cache hit with host-user-owned cache files, a cold
`pacman -Sy` (including the `xlibre`/`sonicde` repos and real signature
verification), a warm sync that must not touch upstream databases
(DB_TTL), a package install through the proxy, and the negative cache.
Eight PASS lines mean everything worked:

```bash
./e2e.sh                 # full run (~2-4 min), cleans up after itself
./e2e.sh --skip-build    # reuse the already-built image
./e2e.sh --keep          # keep containers + cache for debugging
                         # (proxy stays on 127.0.0.1:<printed port>)
```

Notes:

- needs docker and outbound network to the Arch mirrors plus
  `packages.xlibre.net` / `sonicde-arch.github.io` (the client image is
  pulled automatically);
- the mirror container's environment is taken from
  `docker-compose.yml` (`docker compose config` resolves it to an
  env-file, including the `$$` → `$` unescaping), so the e2e run tests
  exactly the deployment configuration - the repo list therefore lives
  in one place only;
- first syncs depend on upstream mirror speed; the client never aborts
  early (databases stream through the proxy), but a full cold run on a
  slow mirror can take a few minutes;
- on failure the stage header, the client output and `FAIL: <reason>`
  point at the broken step; rerun with `--keep` and inspect
  `docker logs e2e-acm-proxy`.

## Files

| File                 | Purpose                                                     |
|----------------------|-------------------------------------------------------------|
| `server.py`          | the whole mirror: config, serving, caching, GC               |
| `test_mirror.py`     | unit + loopback integration tests                            |
| `e2e.sh`             | full-stack e2e test (build, real pacman client, assertions)  |
| `Dockerfile`         | Arch-based image (`python-aiohttp` from pacman, healthcheck) |
| `docker-compose.yml` | LAN deployment defaults (port, volume, env, repo config)     |
