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
| http://nas:8080 | -----------------------> | miss?       -> stream|-->| mirror.rackspace.com
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
  single upstream fetch); only a first-time fetch (nothing cached yet)
  blocks unconditionally.
- the repository -> upstream mapping is built at startup from
  environment variables; `core`/`extra`/`multilib` come with sensible
  defaults, `xlibre` and `sonicde` are preconfigured.
- concurrent requests for the same file are served by one shared
  download (per-file locks), so five machines running `pacman -Syu` at
  once still produce a single upstream fetch per file.

## Quickstart

On the box that will host the cache (any machine with Docker; port 8080
must be reachable from the LAN):

```bash
cd arch-cache-mirror
docker compose up -d --build     # cache persists in ./cache/
```

On every Arch machine of the house, put this as the **first** line of
`/etc/pacman.d/mirrorlist`:

```
Server = http://<host-ip>:8080/$repo/os/$arch
```

and attach the extra repositories in `/etc/pacman.conf` (they reuse the
same mirrorlist entry - `$repo` is substituted per section):

```ini
[xlibre]
Include = /etc/pacman.d/mirrorlist

[sonicde]
Include = /etc/pacman.d/mirrorlist
```

Then `pacman -Syu` as usual. Check `curl http://<host-ip>:8080/` for a
status page (configured repos, cache size, last GC) and `docker logs`
for per-request hit/miss lines.

Signature/key setup for the extra repos is unchanged by the proxy (it
shuffles bytes, including `.sig` files): import the repo owner's key as
you would when using the upstream directly. The example above sets
`SigLevel = Never`, which is *not* recommended for real machines.

Without docker compose:

```bash
docker build -t arch-cache-mirror .
docker run -d --name arch-cache-mirror -p 8080:8080 \
    -v /var/cache/arch-mirror:/var/cache/arch-mirror \
    arch-cache-mirror
```

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
| `OFFICIAL_MIRRORS` | geo.mirror.pkgbuild.com, mirror.rackspace.com (space-separated, tried in order) | upstream URL templates containing `$repo` and/or `$arch`         |
| `EXTRA_REPOS`      | `xlibre=...;sonicde=...` (see below)       | additional repos as `name=url` pairs separated by `;` or newlines; the url is a template containing `$arch` |

Defaults for the extra repos:

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
makes the two operational must-haves explicit and durable: the
bind-mounted `./cache` (so the cache survives image upgrades) and the
env defaults. Healthcheck comes from the Dockerfile (a stdlib-only
`/healthz` probe), so `docker ps` shows mirror health without extra
packages. The only cost is the compose plugin itself, which ships with
Docker everywhere nowadays.

## Caveats

- Plain HTTP on the LAN, no authentication - by design, like every
  pacman mirror; do not expose it to the internet. The container runs
  as root so it can own a bind-mounted cache volume; add `user:` to the
  compose service and chown the volume yourself if you want to drop
  privileges.
- If you keep real upstream mirrors below the proxy line in
  `mirrorlist`, pacman will use them as fallback when the proxy is
  down (nice), but the same file must not be `Include`d by the extra
  repos (their Server lines would 404 noisily there). Either keep the
  mirrorlist proxy-only, or use a second file for the official repos.
- A db first-fetch (repo not cached at all) streams to the client while
  it downloads - bytes flow continuously, but pacman shows an unknown
  size for that one transfer and a concurrent second client for the
  same not-yet-cached file waits for the first to finish. Definitive
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
pure logic (version comparison, size/duration parsing, GC passes) plus
a loopback integration test with a stub upstream (cache miss streaming,
cache hit, fresh-on-request db retrieval, the FRESH_WAIT stale fallback,
short-body upstream, 404 pass-through, unknown repo). Tests need
`aiohttp` and write only to `./tmp`:

```bash
python test_mirror.py             # host, needs aiohttp
docker run --rm arch-cache-mirror python /app/test_mirror.py
```

The version-comparison port is additionally verified by a differential
test against the `vercmp` binary from the `pacman` package (2500
version pairs, 0 mismatches at the time of writing).

## Files

| File                 | Purpose                                                     |
|----------------------|-------------------------------------------------------------|
| `server.py`          | the whole mirror: config, serving, caching, GC               |
| `test_mirror.py`     | unit + loopback integration tests                            |
| `Dockerfile`         | Arch-based image (`python-aiohttp` from pacman, healthcheck) |
| `docker-compose.yml` | LAN deployment defaults (port, volume, env)                  |
