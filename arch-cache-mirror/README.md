# arch-cache-mirror

A caching Arch Linux repository mirror for the home LAN, shipped as
Docker images (x86_64 Arch Linux base, arm64 Arch Linux ARM base). Point
every machine's `/etc/pacman.d/mirrorlist` at it once and all of them
download packages and databases from your LAN; the upstream mirrors are
only hit on the first request of any file.

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
  atomically renamed into place.  A repository that nevertheless
  republishes a filename in place is handled by the db-driven validation
  described in the Caveats.
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
- **byte ranges** (pacman resumes an interrupted download by
  re-requesting its missing tail with a `Range:` header - a server that
  answers that with a plain 200 aborts the resume): cached files are
  sliced locally (206 + `Content-Range`, 416 past EOF); on a miss the
  range is relayed to the upstream and its 206 streams through without
  caching (partials never land in the cache); an upstream that ignores
  the range is downloaded whole into the cache while only the requested
  window is forwarded - a resuming client may give up on a far window,
  but its retry then resumes from the now-cached copy;
- the repository -> upstream mapping is built at startup from
  environment variables; `core`/`extra`/`multilib` come with sensible
  defaults, `xlibre` and `sonicde` are preconfigured, and Arch Linux
  ARM's repos are served for ARM clients (see the ALARM tier in
  [Raspberry Pi / arm64](#raspberry-pi--arm64-arch-linux-arm)).
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
| `ALARM_ARCHES`     | `aarch64 armv7h`                           | client architectures served from the Arch Linux ARM tier; empty = tier off                             |
| `ALARM_REPOS`      | `core extra alarm aur`                     | repos of the ALARM tier (shared names become per-arch mirror overrides; ARM-only names exist for those arches only) |
| `ALARM_MIRRORS`    | `http://mirror.archlinuxarm.org/$arch/$repo` | ALARM upstream URL templates containing `$repo` and/or `$arch`; empty = tier off                      |

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

## Raspberry Pi / arm64 (Arch Linux ARM)

`Dockerfile.alarm` builds the same mirror on top of **Arch Linux ARM**
(the official `archlinux` image is amd64-only, and no community ALARM
base image is maintained anymore - the base is the official rolling
rootfs tarball from os.archlinuxarm.org):

```bash
cd arch-cache-mirror
docker compose -f docker-compose.yml -f docker-compose.arm64.yml up -d --build
```

Ports, volumes, cache limits and `EXTRA_REPOS` all come from
`docker-compose.yml` (the arm64 file only swaps the build). Cross-building
from an x86 host also works wherever qemu-user binfmt is registered
(`docker build -f Dockerfile.alarm --platform linux/arm64 .`).

Arch Linux ARM is a separate distribution from Arch Linux: its own
mirrors (`mirror.archlinuxarm.org`, upstream layout `/$arch/$repo`), its
own keyring, no database signatures, repos `core`/`extra`/`alarm`/`aur`.
The mirror absorbs the differences through the **ALARM tier** (code
defaults, no extra configuration): requests whose `$arch` is `aarch64`
or `armv7h` fetch `core`/`extra` - and the ARM-only `alarm`/`aur` - from
ALARM mirrors, while the same repo names keep the x86_64 upstreams for
x86_64 clients. The cache layout is per-arch anyway, so one instance
serves the whole LAN and every machine still uses the same one-line
mirrorlist:

```
Server = http://<pi>:8282/$repo/os/$arch
```

(on the Pi itself, `<pi>` is `127.0.0.1`; keeping the previous ALARM
mirror as a second `Server` line preserves the upstream fallback)

ALARM clients must use this `/$repo/os/$arch` form: ALARM's native
`/$arch/$repo` shape is an *upstream* layout and would be misread as the
proxy's local `/<repo>/<arch>/<file>` fallback. Otherwise an ALARM
machine stays stock - `/etc/pacman.conf` sections (`core`, `extra`,
`alarm`, `aur`) untouched, package verification against
`archlinuxarm-keyring` exactly as with the upstream directly. The
x86_64-only `xlibre`/`sonicde` repos are simply never requested by ARM
clients.

SD-card note: a pacman cache is write-heavy over a long life (the 20G
`CACHE_SIZE` cap trades eviction-driven re-downloads for bounded
growth); if the card is small or precious, point the `./cache` bind
mount at a USB SSD instead.

## Publishing to Docker Hub

`./release.sh` builds and pushes both images and re-assembles the shared
tag - amd64 on the releasing host, arm64 on the Pi (the qemu
cross-build is an order of magnitude slower) - and finally creates the
`latest` **OCI image index** referencing both. `docker run
<repo>:latest` (or compose without `platform:`) then picks the right
architecture automatically; the semantics are identical on both (same
env, ports, healthcheck).

    ./release.sh    # defaults: HUB_REPO=plartemyev/arch-cache-mirror
                    #            PI_HOST=root@10.11.0.22  PI_DIR=/root/arch-cache-mirror

Requirements: `docker login` on the releasing host *and* on the Pi (each
machine pushes its own build). The script always rebuilds and re-pushes
both architectures before re-creating the index - an index re-pointed at
only one freshly pushed arch would silently serve stale code to the
other platform - so `latest` always points at the index, never at a
bare image (the `:amd64`/`:arm64` tags remain as per-arch escape
hatches). Note the index has no `linux/arm/v7` entry: armv7h userlands
get a clean "no matching manifest" pull error.

Using the Hub image instead of building it - the same deployment
configuration as `docker-compose.yml`, minus the build:

```yaml
services:
  arch-cache-mirror:
    image: plartemyev/arch-cache-mirror:latest
    # run as the calling host user so ./cache stays host-user owned
    user: "${UID:-1000}:${GID:-1000}"
    restart: unless-stopped
    ports:
      - "8282:8080"
    environment:
      CACHE_SIZE: "20G"
      CACHE_AGE: "0"
      KEEP_VERSIONS: "0"
      GC_INTERVAL: "3600"
      DB_TTL: "10m"
      FRESH_WAIT: "5"
      OFFICIAL_MIRRORS: "https://geo.mirror.pkgbuild.com/$$repo/os/$$arch https://mirror.rackspace.com/archlinux/$$repo/os/$$arch"
      EXTRA_REPOS: "xlibre=https://packages.xlibre.net/arch/stable/$$arch;sonicde=https://sonicde-arch.github.io/$$arch"
    volumes:
      - ./cache:/var/cache/arch-mirror
```

(On arm64 hosts this pulls the Arch Linux ARM image from the same tag -
`docker-compose.arm64.yml` is only needed when building from source.)

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
  it downloads - bytes flow continuously, with the true size from
  upstream. Concurrent first requests for the same file share the
  one download, exactly like package misses. Definitive
  upstream 404s are negative-cached for 5 minutes (`NEGATIVE_TTL_SECONDS`
  in `server.py`): a `.db.sig` that starts to exist upstream, or a
  package released mid-window, is picked up after at most that long.
- Metadata freshness: a sync always *triggers* a fresh retrieval for
  stale dbs and delivers it whenever upstream answers within
  `FRESH_WAIT`; only when the upstream is slower than that does a
  client see the cached copy (and the fresh one lands for the next
  sync).  A 304 revalidation renews the cached copy's mtime, so an
  unchanged upstream db counts as fresh for another `DB_TTL` - repos
  whose upstream honors `If-Modified-Since` (e.g. GitHub Pages) are not
  re-contacted on every sync.  Set `FRESH_WAIT=0` for
  strictly-non-blocking behavior or raise it if your upstream is
  reliably slow.
- Upstream content negotiation: the proxy requests
  `Accept-Encoding: identity` from upstreams. CDN-fronted repos (GitHub
  Pages on Fastly) otherwise serve gzip variants whose `Content-Length`
  describes the compressed bytes while the proxy streams the
  decompressed body - pacman 7.x compares the relayed length against the
  size recorded in the repository database and aborts with `Maximum file
  size exceeded` (curl error 63). Identity encoding removes the variant
  mismatch at the source; a genuinely truncated upstream transfer aborts
  the stream and nothing lands in the cache.
- Republishing repositories: real Arch mirrors never change a package
  file's content under the same filename, but some repos (Sonic DE)
  rebuild packages without bumping versions and re-upload them in place.
  A stale cached copy then contradicts the fresh db clients sync against
  (pacman aborts with curl error 63, or fails the sha256 check after a
  full download), so every landed db generation is parsed and cached
  packages it lists with a different size are pruned together with their
  signatures - the next request re-downloads the current build.
  Packages the db does not mention are older generations and stay
  subject to GC/`KEEP_VERSIONS`.
- On upstream mirror rotation the local layout stays stable; clients
  never need a mirrorlist change.

## DNS resilience

Docker's embedded resolver (`127.0.0.11`) snapshots the host's
nameservers when the container is created and never refreshes them: a
host that roams networks leaves the container querying a dead resolver
(fixed ~4 s failover, not configurable).  On such a host every upstream
db refresh fails and the mirror silently serves stale dbs - pacman then
reports "nothing to do" while days of updates are pending (this is how a
real roam outage looked: `Temporary failure in name resolution` for every
upstream at 07:45 UTC, healthy again hours later after the host returned
to the resolver's network).

The mirror therefore bypasses the embedded resolver with a bind-mounted
resolver file and manages it like archinstaller manages its guests' DNS:

- `dns-resolv.conf` (mounted read-only as `/etc/resolv.conf`) gives the
  container glibc resolver semantics: per-server `timeout:1` failover and
  hot reload - glibc re-reads the file on change, so a long-running
  server picks up edits without a restart (verified).  The shipped
  content is the network-independent baseline (public resolvers only).
- `dns-roam-hook.sh` is a NetworkManager dispatcher hook that rewrites
  that file in place on every network event: the current connection's
  DNS servers first (each probed alive with a 1 s `drill` query), public
  fallbacks last, capped at glibc's `MAXNS=3`.  Same sources as
  archinstaller's DNS fallback hook (dispatcher env, `nmcli -f DHCP4/6
  dev show` parse fallback).  Install it with:

      sudo install -m755 dns-roam-hook.sh \
           /etc/NetworkManager/dispatcher.d/90-arch-cache-mirror-dns

  Test run without installing: `ACM_DNS_LOCK=./tmp/l ./dns-roam-hook.sh
  <iface> manual`.  The rewrite is in place only (`printf > file`) and
  idempotent: renaming (mv, `sed -i`) would swap the inode out from
  under the bind mount, and the container never needs a restart, so
  in-flight downloads are never aborted.  The hook rewrites the tracked
  `dns-resolv.conf` with this host's resolvers; `git checkout --
  dns-resolv.conf` restores the shipped baseline.
- The image healthcheck additionally requires `getent hosts
  archlinux.org` to succeed, so resolution breakage surfaces as
  `(health: unhealthy)` in `docker ps` instead of being discovered
  through pacman behavior.

On networks that block outbound DNS to the public resolvers the hook's
probing keeps the lease server first; with the hook not installed, the
shipped baseline still works on any network with working internet DNS.

## Serving libvirt `lan-routed` guests (nft DNAT bypass)

Guests of a libvirt **routed** network (`<forward mode='route'/>`, e.g.
the `lan-routed` network in this repo's deployment notes) could not reach
the mirror from inside their VMs: `curl: Connection refused after 0 ms`,
while ping to the host and host-local access worked.  Mechanism: docker's
nat PREROUTING DNAT rewrites guest traffic to the published port
(`8282 -> 172.x.x.x:8080`) *before* routing, which turns it into
forwarded traffic; libvirt's nftables firewall for routed networks
(table `ip libvirt_network`, regenerated on every net-start) accepts
guest forwarding only out of the declared forward device and **rejects**
everything else arriving on the bridge.  nftables evaluates every base
chain at a hook, so docker's parallel accept at the same priority cannot
save the packet - the guest gets icmp port-unreachable (= "refused").

`lan-routed-bypass.nft` + `lan-routed-bypass.service` fix this without
touching docker or libvirt: a nat rule at priority `dstnat - 1` installs
a PORT-ONLY no-op DNAT binding (`dnat to :8282`, no address pinned, so
host-LAN-IP changes need no change here) for guest traffic to the port,
which ends NAT lookup for the connection; the destination stays the host
IP the guest targeted, the packet is locally delivered to INPUT and
docker-proxy (bound on `0.0.0.0:8282`) serves it.  A plain `accept`
verdict does NOT work here: unlike iptables' single nat table,
independent nft nat base chains are still consulted after an accept
(verified empirically with competing DNAT rules), so a real NAT
expression is required.  Guests additionally need the port in firewalld's
`libvirt-to-host` POLICY: its allow chain (DHCP/DNS/SSH/TFTP/ICMP) ends
in a reject that runs BEFORE the zone rules, so a port added to the
`libvirt-routed` zone is unreachable dead code.  Install (idempotent;
verified with a netns replica of the docker-DNAT + libvirt-reject
topology, then live from a guest):

    sudo install -Dm644 lan-routed-bypass.nft /etc/nft.d/lan-routed-bypass.nft
    sudo install -m644 lan-routed-bypass.service /etc/systemd/system/lan-routed-bypass.service
    sudo systemctl daemon-reload && sudo systemctl enable --now lan-routed-bypass.service
    sudo firewall-cmd --policy=libvirt-to-host --add-port=8282/tcp
    sudo firewall-cmd --permanent --policy=libvirt-to-host --add-port=8282/tcp

To expose another host-published docker port to the guests, add one more
`dnat` line to the nft file and the matching firewall-cmd pair.  The
table is owned by this unit alone: docker, libvirt and firewalld
regenerate only their own tables, so it survives all of their restarts
(including `firewall-cmd --reload`, which libvirt answers by re-applying
its zone bindings).  Guests should address the mirror via the static
`lan-routed` gateway (`http://192.168.1.225:8282`, this network's own
address) instead of the host's roaming LAN IP; archinstaller does this
automatically for VM targets by using the guest's default gateway.

## Development

`server.py` is a single-file aiohttp app; `test_mirror.py` covers the
pure logic (version comparison, size/duration parsing, Range
parsing/resolution, GC passes, env parsing) plus a loopback integration
test with a stub upstream (cache miss streaming, cache hit,
fresh-on-request db retrieval, the FRESH_WAIT stale fallback, short-body
upstream, 404 pass-through with negative caching, unknown repo,
same-file single-flight, byte-range resume: cached slices, upstream 206
relay, a range-ignoring upstream still filling the cache, 416, HEAD
without a body, in-place-republish pruning). Tests need `aiohttp` and
write only to `./tmp`:

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
upstream fetch → cache hit with host-user-owned cache files, byte-range
resume (cached slice, uncached relay), a cold
`pacman -Sy` (including the `xlibre`/`sonicde` repos and real signature
verification), a warm sync that must not touch upstream databases
(DB_TTL), a package install through the proxy, and the negative cache.
Ten PASS lines mean everything worked:

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
  `docker logs e2e-acm-proxy`;
- `e2e.sh` builds and exercises the amd64 image; on the Pi (or any arm64
  host) run the in-image unit/integration suite instead:
  `docker run --rm arch-cache-mirror:arm64 python /app/test_mirror.py`
  (includes a loopback test of the ALARM tier with both upstream
  layouts).

## Files

| File                 | Purpose                                                     |
|----------------------|-------------------------------------------------------------|
| `server.py`          | the whole mirror: config, serving, caching, GC               |
| `test_mirror.py`     | unit + loopback integration tests                            |
| `e2e.sh`             | full-stack e2e test (build, real pacman client, assertions)  |
| `Dockerfile`         | Arch-based image (`python-aiohttp` from pacman, healthcheck) |
| `Dockerfile.alarm`   | arm64 image variant (Arch Linux ARM rootfs tarball as base)  |
| `docker-compose.yml` | LAN deployment defaults (port, volumes, env, repo config) |
| `docker-compose.arm64.yml` | compose override for the arm64 image (build file + platform only) |
| `dns-resolv.conf`    | resolver file bind-mounted into the container (glibc-controlled DNS) |
| `dns-roam-hook.sh`   | NM dispatcher hook rewriting the resolver file on network roams  |
| `lan-routed-bypass.nft` | nft DNAT bypass so libvirt `lan-routed` guests reach the published port |
| `lan-routed-bypass.service` | oneshot unit loading the bypass table at boot |
| `release.sh`         | build + push both arch images, assemble the multi-arch `latest` index |
