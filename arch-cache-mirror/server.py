#!/usr/bin/env python3
"""arch-cache-mirror - a caching LAN mirror for pacman repositories.

Point every Arch machine's /etc/pacman.d/mirrorlist at this proxy:

    Server = http://<this-host>:8080/$repo/os/$arch

and every repository (official or custom) is served through it from the
same URL layout.  On a request the proxy:

* serves packages straight from the local cache when present (package
  files are immutable on Arch mirrors); on a miss it downloads from the
  first reachable upstream mirror while streaming the bytes to the
  requesting pacman and keeping a copy: the download lands in a
  temporary file which is atomically renamed into the cache, so the
  cache only ever gains complete files;
* serves cached metadata (.db/.files and their .sig) without upstream
  contact while younger than DB_TTL; a request for an older copy
  triggers a fresh upstream retrieval that the client waits for (bounded
  by FRESH_WAIT, so a slow or dead upstream can never trip pacman's
  10 s low-speed abort) - past that budget the cached copy is served
  while the refresh continues in the background.  A first-time fetch
  (nothing cached yet) follows the package-miss semantics exactly: one
  shared download under the per-file lock, streamed to the client
  chunked while it fills the cache, so even a multi-MB db on a slow
  upstream keeps bytes flowing and concurrent clients are served from
  the cache once it lands.  Definitive upstream 404s (e.g. the `.db.sig`
  files official repos never serve) are remembered for 5 minutes so
  repeated requests skip the doomed mirror cycle;
* periodically prunes the cache: superseded package versions
  (KEEP_VERSIONS), files untouched for CACHE_AGE and, when CACHE_SIZE
  is set, the oldest files until the total is back under the limit.

The repository -> upstream mirror map is built from environment
variables (OFFICIAL_REPOS/OFFICIAL_MIRRORS in the environment or code
defaults; EXTRA_REPOS is deployment configuration defined in
docker-compose.yml).
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cmp_to_key

from aiohttp import (
    ClientError,
    ClientPayloadError,
    ClientSession,
    ClientTimeout,
    TCPConnector,
    web,
)

LOG = logging.getLogger("arch-cache-mirror")

CHUNK_SIZE = 64 * 1024
TMP_SUBDIR = "tmp"
STALE_TMP_SECONDS = 24 * 3600
SIZE_GC_TARGET = 0.9  # once over CACHE_SIZE, shrink to 90% of it
UPSTREAM_TIMEOUT = ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=60)

DEFAULT_OFFICIAL_REPOS = "core extra multilib"
DEFAULT_OFFICIAL_MIRRORS = (
    "https://geo.mirror.pkgbuild.com/$repo/os/$arch "
    "https://mirror.rackspace.com/archlinux/$repo/os/$arch"
)
# NOTE: the xlibre/sonicde repo list is NOT defaulted here - it is
# deployment configuration, defined in docker-compose.yml (EXTRA_REPOS).

FILENAME_RE = re.compile(r"^[A-Za-z0-9._+:~-]+$")
METADATA_SUFFIXES = (".db", ".db.sig", ".files", ".files.sig")
PACKAGE_FILE_RE = re.compile(
    r"^(?P<name>.+)-(?P<version>[^-]+)-(?P<rel>[^-]+)-(?P<arch>[^-]+)"
    r"\.pkg\.tar(?:\.(?:gz|bz2|xz|zst|lrz|lz4|lzo|zstd))?$"
)
SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([kmgtp]?)b?$")
DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$")
DEFAULT_DB_TTL = "10m"
DEFAULT_FRESH_WAIT = "5"  # < pacman's 10 s low-speed abort
NEGATIVE_TTL_SECONDS = 300  # remember upstream 404s this long


# ---------------------------------------------------------------------------
# configuration

def parse_size(text: str) -> int:
    """'20G'/'500M'/'1024' -> bytes (binary units); 0 means unlimited."""
    m = SIZE_RE.match(text.strip().lower())
    if not m:
        raise ValueError("bad size: %r (want e.g. 20G, 500M, 4096)" % text)
    factor = {"": 1, "k": 2**10, "m": 2**20, "g": 2**30, "t": 2**40, "p": 2**50}
    return int(float(m.group(1)) * factor[m.group(2)])


def parse_duration(text: str) -> float:
    """'30d'/'12h'/'45m'/'90s'/'3600'/'0.5s' -> seconds; 0 means unlimited."""
    m = DURATION_RE.match(text.strip().lower())
    if not m:
        raise ValueError("bad duration: %r (want e.g. 30d, 12h, 3600)" % text)
    factor = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
    return float(m.group(1)) * factor[m.group(2)]


def human_size(num: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(num) < 1024:
            break
        num /= 1024
    return ("%d %s" if unit == "B" else "%.1f %s") % (num, unit)


@dataclass
class Repo:
    name: str
    mirrors: list[str]


@dataclass
class Config:
    listen_addr: str
    listen_port: int
    cache_dir: str
    cache_size: int
    cache_age: int
    keep_versions: int
    gc_interval: int
    db_ttl: float
    fresh_wait: float
    official_repos: list[str]
    official_mirrors: list[str]
    extra_repos: list[Repo]

    @classmethod
    def from_env(cls) -> "Config":
        extra = []
        for pair in os.environ.get("EXTRA_REPOS", "").replace("\n", ";").split(";"):
            pair = pair.strip()
            if not pair:
                continue
            name, sep, url = pair.partition("=")
            if not sep or not name.strip() or not url.strip():
                raise ValueError("bad EXTRA_REPOS entry %r (want name=url;...)" % pair)
            extra.append(Repo(name.strip(), [url.strip()]))
        return cls(
            listen_addr=os.environ.get("LISTEN_ADDR", "0.0.0.0"),
            listen_port=int(os.environ.get("LISTEN_PORT", "8080")),
            cache_dir=os.environ.get("CACHE_DIR", "/var/cache/arch-mirror"),
            cache_size=parse_size(os.environ.get("CACHE_SIZE", "0")),
            cache_age=int(parse_duration(os.environ.get("CACHE_AGE", "0"))),
            keep_versions=max(0, int(os.environ.get("KEEP_VERSIONS", "0"))),
            gc_interval=max(1, int(os.environ.get("GC_INTERVAL", "3600"))),
            db_ttl=parse_duration(os.environ.get("DB_TTL", DEFAULT_DB_TTL)),
            fresh_wait=parse_duration(os.environ.get("FRESH_WAIT", DEFAULT_FRESH_WAIT)),
            official_repos=os.environ.get("OFFICIAL_REPOS", DEFAULT_OFFICIAL_REPOS).split(),
            official_mirrors=os.environ.get(
                "OFFICIAL_MIRRORS", DEFAULT_OFFICIAL_MIRRORS).split(),
            extra_repos=extra,
        )


def build_repos(cfg: Config) -> dict[str, Repo]:
    repos: dict[str, Repo] = {}
    for name in cfg.official_repos:
        repos[name] = Repo(name, list(cfg.official_mirrors))
    for repo in cfg.extra_repos:
        repos[repo.name] = repo
    return repos


# ---------------------------------------------------------------------------
# pacman version comparison - exact port of lib/libalpm/version.c (pacman
# 6.0.2, the semantics are unchanged in 7.x) so that KEEP_VERSIONS pruning
# agrees with pacman about which package version is newest.

def _isalnum(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or ("0" <= c <= "9")


def _isdigit(c: str) -> bool:
    return "0" <= c <= "9"


def _isalpha(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def _parse_evr(evr: str) -> tuple[str, str, str | None]:
    """Split '[epoch:]version[-release]' (port of pacman's parseEVR)."""
    s = 0
    while s < len(evr) and _isdigit(evr[s]):
        s += 1
    se = evr.rfind("-", s)  # release = after the LAST hyphen
    end = se if se != -1 else len(evr)
    if s < len(evr) and evr[s] == ":":
        epoch = evr[:s] or "0"
        version = evr[s + 1:end]
    else:
        epoch = "0"
        version = evr[:end]
    return epoch, version, (evr[se + 1:] if se != -1 else None)


def _rpmvercmp(a: str, b: str) -> int:
    """Port of pacman's rpmvercmp(); a and b must differ."""
    la, lb = len(a), len(b)
    one = two = 0
    while one < la and two < lb:
        sep1 = one
        while one < la and not _isalnum(a[one]):
            one += 1
        sep2 = two
        while two < lb and not _isalnum(b[two]):
            two += 1
        if not (one < la and two < lb):
            break
        if (one - sep1) != (two - sep2):  # different separator run lengths
            return -1 if (one - sep1) < (two - sep2) else 1
        # grab the first completely alpha or completely numeric segment
        isnum = _isdigit(a[one])
        e1, e2 = one, two
        while e1 < la and (_isdigit(a[e1]) if isnum else _isalpha(a[e1])):
            e1 += 1
        while e2 < lb and (_isdigit(b[e2]) if isnum else _isalpha(b[e2])):
            e2 += 1
        seg1, seg2 = a[one:e1], b[two:e2]
        if not seg1:  # cannot happen (both start on alnum)
            return -1
        if not seg2:  # segment types differ: numeric beats alpha
            return 1 if isnum else -1
        if isnum:
            n1, n2 = seg1.lstrip("0"), seg2.lstrip("0")
            if len(n1) != len(n2):  # whichever number has more digits wins
                return 1 if len(n1) > len(n2) else -1
        if seg1 != seg2:
            return -1 if seg1 < seg2 else 1
        one, two = e1, e2

    if one >= la and two >= lb:
        return 0
    # the final showdown: a remaining alpha segment never beats an empty one
    c1 = a[one] if one < la else ""
    c2 = b[two] if two < lb else ""
    if (not c1 and not _isalpha(c2)) or _isalpha(c1):
        return -1
    return 1


def vercmp(a: str, b: str) -> int:
    """Compare pacman version strings ('[epoch:]ver[-rel]'): -1, 0 or 1.

    Notable semantics (all verified against pacman's vercmp binary):
    '1.0rc1' < '1.0' but '1.0.rc1' > '1.0'; digit tails beat empty ones
    ('1.0' < '1.0.1'); epochs compare numerically ('1:1.0' > '2.0').
    """
    if a == b:
        return 0
    e1, v1, r1 = _parse_evr(a)
    e2, v2, r2 = _parse_evr(b)
    ret = _rpmvercmp(e1, e2)
    if ret == 0:
        ret = _rpmvercmp(v1, v2)
        if ret == 0 and r1 is not None and r2 is not None:
            ret = _rpmvercmp(r1, r2)
    return ret


# ---------------------------------------------------------------------------
# cache garbage collection

@dataclass
class CacheEntry:
    path: str
    repo: str
    arch: str
    filename: str
    size: int
    mtime: float
    version: str | None = None  # 'version-rel' for package files
    dead: bool = False


def _scan_cache(root: str) -> list[CacheEntry]:
    entries = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if dirpath == root and TMP_SUBDIR in dirnames:
            dirnames.remove(TMP_SUBDIR)
        arch_dir = os.path.dirname(dirpath)  # <root>/<repo>/os/<arch>
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            try:
                st = os.stat(path)
            except FileNotFoundError:
                continue
            rel = os.path.relpath(path, root)
            parts = rel.split(os.sep)
            # layout: <root>/<repo>/os/<arch>/<filename>
            repo, arch = (parts[0], parts[2]) if len(parts) == 4 else ("", "")
            entry = CacheEntry(path, repo, arch, filename, st.st_size, st.st_mtime)
            m = PACKAGE_FILE_RE.match(filename)
            if m and repo:
                entry.version = "%s-%s" % (m["version"], m["rel"])
            entries.append(entry)
    return entries


def _unlink(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False


def _sweep_stale_tmp(root: str, now: float) -> int:
    removed = 0
    tmp_dir = os.path.join(root, TMP_SUBDIR)
    try:
        names = os.listdir(tmp_dir)
    except FileNotFoundError:
        return 0
    for name in names:
        path = os.path.join(tmp_dir, name)
        try:
            if now - os.stat(path).st_mtime > STALE_TMP_SECONDS:
                removed += _unlink(path)
        except FileNotFoundError:
            pass
    return removed


def run_gc(cfg: Config, locks: dict[str, asyncio.Lock]) -> dict:
    """Apply all pruning passes; returns stats for the status page."""
    now = time.time()
    locked = {path for path, lock in locks.items() if lock.locked()}
    entries = [e for e in _scan_cache(cfg.cache_dir) if e.path not in locked]
    by_path = {e.path: e for e in entries}
    freed_files = freed_bytes = 0

    def drop(entry: CacheEntry) -> None:
        nonlocal freed_files, freed_bytes
        if _unlink(entry.path):
            freed_files += 1
            freed_bytes += entry.size
        entry.dead = True

    # 1) superseded package versions (newest KEEP_VERSIONS+1 survive)
    if cfg.keep_versions >= 0:
        groups: dict[tuple, list[CacheEntry]] = defaultdict(list)
        for e in entries:
            if e.version:
                groups[(e.repo, e.arch, PACKAGE_FILE_RE.match(e.filename)["name"])].append(e)
        for group in groups.values():
            if len(group) <= cfg.keep_versions + 1:
                continue
            group.sort(key=cmp_to_key(lambda a, b: vercmp(a.version, b.version)), reverse=True)
            for e in group[cfg.keep_versions + 1:]:
                drop(e)
                sig = by_path.get(e.path + ".sig")
                if sig and not sig.dead:
                    drop(sig)

    # 2) age limit
    if cfg.cache_age > 0:
        for e in entries:
            if not e.dead and now - e.mtime > cfg.cache_age:
                drop(e)

    # 3) total size limit: oldest first, down to 90% of the cap
    if cfg.cache_size > 0:
        alive = sorted((e for e in entries if not e.dead), key=lambda e: e.mtime)
        total = sum(e.size for e in alive)
        target = int(cfg.cache_size * SIZE_GC_TARGET)
        for e in alive:
            if total <= target:
                break
            drop(e)
            total -= e.size

    stale_tmp = _sweep_stale_tmp(cfg.cache_dir, now)
    alive = [e for e in entries if not e.dead]
    return {
        "scanned_at": now,
        "files": len(alive),
        "bytes": sum(e.size for e in alive),
        "freed_files": freed_files,
        "freed_bytes": freed_bytes,
        "freed_tmp": stale_tmp,
    }


# ---------------------------------------------------------------------------
# HTTP serving

def _is_metadata(filename: str) -> bool:
    return filename.endswith(METADATA_SUFFIXES)


def _quiet_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@asynccontextmanager
async def file_lock(app: web.Application, path: str):
    """Serialize concurrent requests for the same cache file."""
    async with app["locks_guard"]:
        lock = app["file_locks"].setdefault(path, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        async with app["locks_guard"]:
            if not lock.locked() and app["file_locks"].get(path) is lock:
                del app["file_locks"][path]


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def handle_status(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    repos: dict[str, Repo] = request.app["repos"]
    stats = request.app.get("stats")
    lines = [
        "arch-cache-mirror",
        "",
        "client /etc/pacman.d/mirrorlist entry:",
        "    Server = http://<this-host>:%d/$repo/os/$arch" % cfg.listen_port,
        "",
        "repositories served:",
    ]
    for name in sorted(repos):
        for mirror in repos[name].mirrors:
            lines.append("  [%s] %s" % (name, mirror))
    lines += [
        "",
        "cache: %s" % cfg.cache_dir,
        "  size limit: %s, age limit: %s, keep versions: %d, db ttl: %s, fresh wait: %s"
        % (cfg.cache_size or "unlimited",
           "%ds" % cfg.cache_age if cfg.cache_age else "unlimited",
           cfg.keep_versions,
           "%gs" % cfg.db_ttl if cfg.db_ttl else "always",
           "%gs" % cfg.fresh_wait if cfg.fresh_wait else "off"),
    ]
    if stats:
        lines += [
            "  now: %d files, %s" % (stats["files"], human_size(stats["bytes"])),
            "  last gc: freed %d files (%s) + %d stale tmp"
            % (stats["freed_files"], human_size(stats["freed_bytes"]), stats["freed_tmp"]),
        ]
    return web.Response(text="\n".join(lines) + "\n")



async def handle_repo(request: web.Request) -> web.StreamResponse:
    repo_name = request.match_info["repo"]
    arch = request.match_info["arch"]
    filename = request.match_info["filename"]
    if not FILENAME_RE.match(filename):
        return web.Response(status=400, text="bad filename\n")
    repo = request.app["repos"].get(repo_name)
    if repo is None:
        return web.Response(
            status=404,
            text="unknown repository %r (serving: %s)\n"
                 % (repo_name, ", ".join(sorted(request.app["repos"]))))
    local = os.path.join(request.app["cfg"].cache_dir, repo_name, "os", arch, filename)
    negative_until = request.app["negative"].get(local)
    if negative_until and time.time() < negative_until and not os.path.exists(local):
        LOG.info("neg  %s/%s/%s (recent upstream 404)", repo_name, arch, filename)
        return web.Response(status=404,
                            text="upstream reported %s as missing recently\n" % filename)
    if _is_metadata(filename):
        return await _handle_metadata(request, repo, arch, filename, local)
    async with file_lock(request.app, local):
        if os.path.exists(local):
            LOG.info("hit  %s/%s/%s", repo_name, arch, filename)
            return web.FileResponse(local)
        outcome, response, last_status = await _fetch_upstream(
            request.app, request, repo, arch, filename, local)
        if outcome != "ok":
            return _upstream_failed(filename, last_status)
        return response


async def _fetch_upstream(app: web.Application, request: web.Request | None,
                          repo: Repo, arch: str, filename: str, local: str, *,
                          keep_partial: bool = False,
                          revalidate: bool = False,
                          ) -> tuple[str, web.StreamResponse | None, int | None]:
    """Download `filename` from the first reachable upstream mirror into
    the cache (atomic rename, so the cache only ever gains complete
    files), streaming the bytes to the requesting client at the same time
    when one is attached: package misses and first-time db fetches pass
    the request, the background refresh passes None.  Callers must hold
    the per-file lock when a concurrent fetch of the same file is
    possible.

    keep_partial (metadata only): an upstream that sends less than its
    declared Content-Length (GitHub Pages does) still yields a complete
    chunked response and a cached copy of what arrived; without it
    (packages) a short body aborts the stream instead, since the cache
    must never gain a partial package - the client retries the whole
    file.  keep_partial also omits the Content-Length passthrough so the
    chunked framing stays self-consistent.

    revalidate (background refresh only): send If-Modified-Since from the
    cached copy's mtime and treat 304 as done.

    Returns (outcome, response, last-upstream-status) with outcome 'ok',
    'not-modified' or 'failed' ('failed' means every mirror was exhausted
    before any byte reached a client; response is None then)."""
    cfg: Config = app["cfg"]
    tmp = os.path.join(cfg.cache_dir, TMP_SUBDIR, uuid.uuid4().hex + ".part")
    os.makedirs(os.path.dirname(local), exist_ok=True)
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    headers = {}
    if revalidate and os.path.exists(local):
        headers["If-Modified-Since"] = email.utils.formatdate(
            os.stat(local).st_mtime, usegmt=True)
    last_status = None
    for mirror in repo.mirrors:
        url = (mirror.replace("$repo", repo.name).replace("$arch", arch).rstrip("/")
               + "/" + filename)
        # two attempts per mirror: the second covers a stale keep-alive
        # connection (e.g. right after the upstream mirror restarted)
        attempts = 2
        while attempts:
            attempts -= 1
            prepared = False
            try:
                async with app["client"].get(url, headers=headers) as upstream:
                    if revalidate and upstream.status == 304:
                        if os.path.exists(local):
                            LOG.info("ref  %s/%s/%s (db not modified)",
                                     repo.name, arch, filename)
                            return "not-modified", None, None
                        break  # next mirror
                    if upstream.status != 200:
                        LOG.warning("upstream %s -> HTTP %d for %s",
                                    url, upstream.status, filename)
                        last_status = upstream.status
                        break  # next mirror
                    length = upstream.headers.get("Content-Length")
                    response = None
                    if request is not None:
                        response = web.StreamResponse(
                            headers={"Content-Type": "application/octet-stream"})
                        if length is not None and not keep_partial:
                            response.content_length = int(length)
                        await response.prepare(request)
                        prepared = True
                    received = 0
                    with open(tmp, "wb") as out:
                        try:
                            async for chunk in upstream.content.iter_chunked(CHUNK_SIZE):
                                out.write(chunk)
                                received += len(chunk)
                                if response is not None:
                                    await response.write(chunk)
                        except ClientPayloadError as exc:
                            if received == 0 or not keep_partial:
                                raise  # nothing arrived, or package: retry/next mirror
                            LOG.warning("upstream %s sent %d of %s declared bytes; "
                                        "keeping what arrived (%s)",
                                        url, received, length, exc)
                    os.replace(tmp, local)
                    if response is not None:
                        await response.write_eof()
                    LOG.info("miss %s/%s/%s (%s) <- %s", repo.name, arch, filename,
                             human_size(received), url)
                    return "ok", response, None
            except (ClientError, TimeoutError, OSError) as exc:
                _quiet_unlink(tmp)
                if prepared:
                    # bytes already went to the client; drop the connection and
                    # let the client retry the whole file
                    LOG.warning("stream interrupted for %s: %s", filename, exc)
                    raise
                LOG.warning("upstream %s failed for %s: %s", url, filename, exc)
                continue  # retry the same mirror, then fall through
            except asyncio.CancelledError:
                _quiet_unlink(tmp)
                raise
    _quiet_unlink(tmp)
    _remember_missing(app, local, last_status)
    return "failed", None, last_status


def _upstream_failed(filename: str, last_status: int | None) -> web.Response:
    """Response for a fetch where every mirror was exhausted before any
    byte reached the client."""
    status = 404 if last_status == 404 else 502
    return web.Response(status=status,
                        text="all upstream mirrors failed for %s\n" % filename)


def _remember_missing(app: web.Application, local: str, last_status: int | None) -> None:
    """Cache a definitive upstream 404 (e.g. the .db.sig files official
    repos never serve) so repeat requests skip the doomed mirror cycle."""
    if last_status == 404 and not os.path.exists(local):
        app["negative"][local] = time.time() + NEGATIVE_TTL_SECONDS


def _ensure_refresh(app: web.Application, repo: Repo, arch: str,
                    filename: str, local: str) -> asyncio.Task:
    """Return a running (or newly started) background refresh for the db
    file, single-flight. Requests arriving while a refresh is running
    queue exactly one more round instead of being lost."""
    task = app["refresh_tasks"].get(local)
    if task is not None and not task.done():
        app["refresh_again"].add(local)
        return task

    async def refresh() -> None:
        try:
            while True:
                outcome, last_status = await _refresh_db(
                    app, repo, arch, filename, local)
                if outcome == "failed":
                    LOG.warning("background refresh of %s failed (last HTTP status %s); "
                                "keeping the cached copy", filename, last_status)
                if local not in app["refresh_again"]:
                    break
                app["refresh_again"].discard(local)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("background refresh of %s crashed", filename)

    task = asyncio.create_task(refresh())
    app["bg_tasks"].add(task)
    app["refresh_tasks"][local] = task

    def _done(t: asyncio.Task) -> None:
        app["bg_tasks"].discard(t)
        if app["refresh_tasks"].get(local) is t:
            del app["refresh_tasks"][local]

    task.add_done_callback(_done)
    return task


async def _refresh_db(app: web.Application, repo: Repo, arch: str,
                      filename: str, local: str) -> tuple[str, int | None]:
    """One background refresh round under the per-file lock.  Skips when
    the cached copy is already fresh again (an earlier round of this
    refresh, or a first-time fetch, renewed it while further requests
    were queued)."""
    async with file_lock(app, local):
        if os.path.exists(local) and \
                time.time() - os.stat(local).st_mtime < app["cfg"].db_ttl:
            LOG.info("ref  %s/%s/%s (db already fresh)", repo.name, arch, filename)
            return "ok", None
        outcome, _, last_status = await _fetch_upstream(
            app, None, repo, arch, filename, local,
            keep_partial=True, revalidate=True)
    return outcome, last_status


async def _handle_metadata(request: web.Request, repo: Repo, arch: str,
                           filename: str, local: str) -> web.StreamResponse:
    """Databases are metadata requests that only happen on sync.  A
    first-time fetch (nothing cached yet) follows the package-miss
    semantics exactly: one shared download under the per-file lock,
    streamed to the client chunked while it fills the cache - even a
    multi-MB db on a slow upstream keeps bytes flowing, and concurrent
    clients wait for it and are then served from the cache.  A request
    for a copy older than DB_TTL triggers a single-flight background
    refresh that the client waits for (bounded by FRESH_WAIT; a slow
    upstream must never trip pacman's 10 s low-speed abort - past that
    budget the cached copy is served while the refresh continues in the
    background).  Copies younger than DB_TTL are served without upstream
    contact."""
    app = request.app
    if not os.path.exists(local):
        async with file_lock(app, local):
            if not os.path.exists(local):  # a concurrent client may have won
                outcome, response, last_status = await _fetch_upstream(
                    app, request, repo, arch, filename, local, keep_partial=True)
                if outcome != "ok":
                    return _upstream_failed(filename, last_status)
                return response
    age = time.time() - os.stat(local).st_mtime
    if age >= app["cfg"].db_ttl:
        task = _ensure_refresh(app, repo, arch, filename, local)
        if app["cfg"].fresh_wait > 0:
            done, _ = await asyncio.wait({task}, timeout=app["cfg"].fresh_wait)
            if done:
                LOG.info("hit  %s/%s/%s (db refreshed from upstream)",
                         repo.name, arch, filename)
            else:
                LOG.info("hit  %s/%s/%s (db stale, upstream slower than %.1fs, "
                         "refreshing in background)", repo.name, arch, filename,
                         app["cfg"].fresh_wait)
        else:
            LOG.info("hit  %s/%s/%s (db stale, refreshing in background)",
                     repo.name, arch, filename)
    else:
        LOG.info("hit  %s/%s/%s (db fresh)", repo.name, arch, filename)
    return web.FileResponse(local)


# ---------------------------------------------------------------------------
# application wiring

async def _gc_loop(app: web.Application) -> None:
    cfg: Config = app["cfg"]
    await asyncio.sleep(30)  # let the first clients through before scanning
    while True:  # scheduler-style loop: bounded work per iteration
        try:
            stats = await asyncio.to_thread(run_gc, cfg, app["file_locks"])
            holder = app["stats"]  # mutate in place: app state is immutable
            holder.clear()         # once started
            holder.update(stats)
            LOG.info("gc: %d files, %s on disk, freed %d files (%s) + %d stale tmp",
                     stats["files"], human_size(stats["bytes"]),
                     stats["freed_files"], human_size(stats["freed_bytes"]),
                     stats["freed_tmp"])
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("gc pass failed")
        await asyncio.sleep(cfg.gc_interval)


async def on_startup(app: web.Application) -> None:
    cfg: Config = app["cfg"]
    os.makedirs(os.path.join(cfg.cache_dir, TMP_SUBDIR), exist_ok=True)
    app["client"] = ClientSession(
        timeout=UPSTREAM_TIMEOUT,
        connector=TCPConnector(limit=32),
        headers={"User-Agent": "arch-cache-mirror/1.0"},
    )
    app["gc_task"] = asyncio.create_task(_gc_loop(app))
    LOG.info("serving %d repositories on %s:%d (cache %s)",
             len(app["repos"]), cfg.listen_addr, cfg.listen_port, cfg.cache_dir)


async def on_cleanup(app: web.Application) -> None:
    app["gc_task"].cancel()
    for task in list(app["bg_tasks"]):
        task.cancel()
    await asyncio.gather(app["gc_task"], *app["bg_tasks"], return_exceptions=True)
    await app["client"].close()


def build_app(cfg: Config | None = None) -> web.Application:
    cfg = cfg or Config.from_env()
    app = web.Application()
    app["cfg"] = cfg
    app["repos"] = build_repos(cfg)
    app["file_locks"] = {}
    app["locks_guard"] = asyncio.Lock()
    app["stats"] = {}  # GC results; mutated in place by the gc loop
    app["refresh_again"] = set()  # paths whose schedule arrived during one
    app["refresh_tasks"] = {}  # db path -> in-flight refresh task
    app["negative"] = {}  # path -> expiry of a remembered upstream 404
    app["bg_tasks"] = set()
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/", handle_status)
    app.router.add_get("/{repo}/os/{arch}/{filename}", handle_repo)
    app.router.add_get("/{repo}/{arch}/{filename}", handle_repo)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    web.run_app(build_app(cfg), host=cfg.listen_addr, port=cfg.listen_port,
                access_log=None)


if __name__ == "__main__":
    main()
