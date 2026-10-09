#!/usr/bin/env python3
"""Tests for arch-cache-mirror (needs aiohttp; run inside the container or a venv).

    python test_mirror.py          # unit tests + loopback integration test

Temp files go to ./tmp (or $ACM_TEST_TMP), never to the system temp dir.
"""

import asyncio
import email.utils
import inspect
import os
import re
import shutil
import sys
import tempfile
import time
import traceback

from aiohttp import ClientError, ClientSession, web
from aiohttp.test_utils import TestServer

import server
from server import Config, Repo, build_app, run_gc, vercmp

TMP_BASE = os.environ.get("ACM_TEST_TMP") or os.path.join(os.getcwd(), "tmp")

PKG = "foo-1.0-1-x86_64.pkg.tar.zst"


async def eventually(cond, timeout: float = 5.0) -> bool:
    """Wait for a background refresh to become observable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return bool(cond())


def _cfg(cache_dir: str, **kw) -> Config:
    defaults = dict(
        listen_addr="127.0.0.1", listen_port=0, cache_dir=cache_dir,
        cache_size=0, cache_age=0, keep_versions=0, gc_interval=3600,
        db_ttl=0,  # always revalidate: keeps the freshness assertions strict
        fresh_wait=5,  # real default: stale fallback only on slow upstreams
        official_repos=[], official_mirrors=[], extra_repos=[],
    )
    defaults.update(kw)
    return Config(**defaults)


# ---------------------------------------------------------------------------
# pure logic

VERCMP_CASES = [
    # ground truth captured from pacman's vercmp binary (pacman 7.1.0)
    ("1.0", "1.0", 0), ("1.0", "2.0", -1), ("2.0", "1.0", 1),
    ("1.0.1", "1.0", 1), ("1.0", "1.0.0", -1), ("5.2.37", "5.2.4", 1),
    ("1.0rc1", "1.0", -1), ("1.0rc", "1.0", -1), ("1.0rc1", "1.0rc2", -1),
    ("1:1.0", "2.0", 1), ("2:1.0-1", "1:1.0-2", 1),
    ("1.0a", "1.0beta", -1), ("1.0alpha", "1.0beta", -1),
    ("6.14.rc1", "6.14", 1), ("0.9", "1.0", -1), ("1.0rc1", "0.9", 1),
    ("1.0pre1", "1.0", -1), ("20260101", "20260101git123", 1),
    ("1.0_z", "1.0a", 1), ("2.2.1+r3+gabc", "2.2.1", 1),
    ("1.0-1", "1.0-2", -1), ("1.0-1", "1.0-1", 0),
    # consequences of the reference algorithm (rpmvercmp + parseEVR)
    ("1.0.rc1", "1.0", 1), ("1.0", "1.0rc1", 1), ("1..2", "1.2", 1),
    ("4.14.1", "4.14", 1), ("24.1", "24.1rc1", 1), ("1.0git", "1.0", -1),
    ("0.5", "1:0.1", -1), ("1:0.5", "0.9", 1), ("6.6.1.r1", "6.6.1", 1),
]


def test_vercmp(_base: str) -> None:
    for a, b, want in VERCMP_CASES:
        got = vercmp(a, b)
        assert got == want, "vercmp(%r, %r) = %d, want %d" % (a, b, got, want)
        assert vercmp(b, a) == -want, "vercmp not antisymmetric for %r/%r" % (a, b)
    # package filename parsing used by the GC
    m = server.PACKAGE_FILE_RE.match("foo-1.0-1-x86_64.pkg.tar.zst")
    assert m and m["name"] == "foo" and m["version"] == "1.0" and m["rel"] == "1"
    m = server.PACKAGE_FILE_RE.match("python-aiohttp-1:3.11.0-1-x86_64.pkg.tar.zst.sig")
    assert m is None  # signatures are not package files


def test_parsers(_base: str) -> None:
    assert server.parse_size("20G") == 20 * 2**30
    assert server.parse_size("500m") == 500 * 2**20
    assert server.parse_size("1.5K") == 1536
    assert server.parse_size("1024") == 1024
    assert server.parse_size("0") == 0
    assert server.parse_duration("30d") == 30 * 86400
    assert server.parse_duration("12h") == 12 * 3600
    assert server.parse_duration("45m") == 2700
    assert server.parse_duration("90s") == 90
    assert server.parse_duration("3600") == 3600
    assert server.parse_duration("0") == 0
    for bad in ("", "abc", "-5G", "1x"):
        for fn in (server.parse_size, server.parse_duration):
            try:
                fn(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("%s accepted %r" % (fn.__name__, bad))


def test_range_math(_base: str) -> None:
    f = server.parse_range
    # the forms pacman's curl sends when resuming
    assert f(None) is None
    assert f("bytes=0-0") == (0, 0)
    assert f("bytes=5-") == (5, None)
    assert f("bytes=10-19") == (10, 19)
    assert f("bytes=-5") == (-5, None)
    # ignored forms (full 200 response, like a server without range support)
    for ignored in ("", "bytes=", "bytes=-0", "bytes=abc", "items=1-2",
                    "bytes=1-2,5-9", "bytes=9-5"):
        assert f(ignored) is None, ignored

    r = server.resolve_range
    assert r((0, 0), 64) == (0, 0)
    assert r((5, None), 64) == (5, 63)
    assert r((10, 19), 64) == (10, 19)
    assert r((10, 100), 64) == (10, 63)  # end clamped to EOF
    assert r((-5, None), 64) == (59, 63)  # suffix: last 5 bytes
    assert r((-100, None), 64) == (0, 63)  # oversized suffix: whole file
    # unsatisfiable: 416
    assert r((64, None), 64) is None
    assert r((100, None), 64) is None
    assert r((0, None), 0) is None  # empty file
    assert r((-5, None), 0) is None


def test_gc(base: str) -> None:
    def write(rel: str, body: bytes, mtime: float | None = None) -> str:
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    old = time.time() - 10_000
    pkg = "repo/os/x86_64/"
    write(pkg + "foo-1.0-1-x86_64.pkg.tar.zst", b"a", old)
    foo1_sig = write(pkg + "foo-1.0-1-x86_64.pkg.tar.zst.sig", b"s", old)
    write(pkg + "foo-1.5-1-x86_64.pkg.tar.zst", b"b")
    write(pkg + "foo-2.0.0-2-x86_64.pkg.tar.zst", b"c")
    write(pkg + "foo-2.0.0-2-x86_64.pkg.tar.zst.sig", b"s")
    write(pkg + "bar-1.0-1-any.pkg.tar.zst", b"d")
    write(pkg + "repo.db", b"db", old)

    # keep_versions=0: only the newest foo survives (plus its sig)
    stats = run_gc(_cfg(base), {})
    assert os.path.exists(os.path.join(base, pkg + "foo-2.0.0-2-x86_64.pkg.tar.zst"))
    assert os.path.exists(os.path.join(base, pkg + "foo-2.0.0-2-x86_64.pkg.tar.zst.sig"))
    assert not os.path.exists(os.path.join(base, pkg + "foo-1.5-1-x86_64.pkg.tar.zst"))
    assert not os.path.exists(foo1_sig), "sig of pruned version must go too"
    assert stats["freed_files"] == 3
    assert stats["freed_bytes"] == 3 * 1  # b"a" + b"b" + the sig

    # keep_versions=2: latest + two superseded versions survive
    base2 = tempfile.mkdtemp(prefix="acm-", dir=TMP_BASE)
    try:
        os.makedirs(os.path.join(base2, pkg))
        for version in ("0.9", "1.0", "1.5", "2.0.0"):
            path = os.path.join(
                base2, pkg + "foo-%s-1-x86_64.pkg.tar.zst" % version)
            with open(path, "wb") as f:
                f.write(b"x")
        run_gc(_cfg(base2, keep_versions=2), {})
        remaining = sorted(os.listdir(os.path.join(base2, pkg)))
        assert remaining == [
            "foo-1.0-1-x86_64.pkg.tar.zst",
            "foo-1.5-1-x86_64.pkg.tar.zst",
            "foo-2.0.0-1-x86_64.pkg.tar.zst",
        ], remaining
    finally:
        shutil.rmtree(base2, ignore_errors=True)

    # age limit: everything untouched for CACHE_AGE goes, fresh files stay
    base3 = tempfile.mkdtemp(prefix="acm-", dir=TMP_BASE)
    try:
        os.makedirs(os.path.join(base3, pkg))
        write3 = lambda rel, mtime: (
            open(os.path.join(base3, rel), "wb").close(),
            os.utime(os.path.join(base3, rel), (mtime, mtime)))
        write3(pkg + "old-1.0-1-x86_64.pkg.tar.zst", old)
        write3(pkg + "new-1.0-1-x86_64.pkg.tar.zst", time.time())
        run_gc(_cfg(base3, cache_age=1000), {})
        assert not os.path.exists(os.path.join(base3, pkg + "old-1.0-1-x86_64.pkg.tar.zst"))
        assert os.path.exists(os.path.join(base3, pkg + "new-1.0-1-x86_64.pkg.tar.zst"))
    finally:
        shutil.rmtree(base3, ignore_errors=True)

    # size limit: oldest files first, down to 90% of the cap
    base4 = tempfile.mkdtemp(prefix="acm-", dir=TMP_BASE)
    try:
        os.makedirs(os.path.join(base4, pkg))
        for i, mtime in enumerate((old, old + 1, old + 2)):
            p = os.path.join(base4, pkg + "p%d-1.0-1-x86_64.pkg.tar.zst" % i)
            with open(p, "wb") as f:
                f.write(b"x" * 1000)
            os.utime(p, (mtime, mtime))
        run_gc(_cfg(base4, cache_size=1500), {})
        remaining = os.listdir(os.path.join(base4, pkg))
        assert remaining == ["p2-1.0-1-x86_64.pkg.tar.zst"], remaining
    finally:
        shutil.rmtree(base4, ignore_errors=True)

    # stale tmp files are swept
    tmp_dir = os.path.join(base, server.TMP_SUBDIR)
    os.makedirs(tmp_dir, exist_ok=True)
    stale = os.path.join(tmp_dir, "junk.part")
    with open(stale, "wb") as f:
        f.write(b"junk")
    os.utime(stale, (time.time() - server.STALE_TMP_SECONDS - 10,) * 2)
    fresh = os.path.join(tmp_dir, "fresh.part")
    with open(fresh, "wb") as f:
        f.write(b"busy")
    run_gc(_cfg(base), {})
    assert not os.path.exists(stale) and os.path.exists(fresh)


# ---------------------------------------------------------------------------
# integration: real aiohttp server + stub upstream over loopback

async def test_db_ttl(base: str) -> None:
    """A db within DB_TTL is served from cache; past it, upstream is asked."""
    upstream: dict[str, dict] = {}

    async def stub(request: web.Request) -> web.Response:
        rec = upstream[request.match_info["filename"]]
        rec["calls"] += 1
        ims = request.headers.get("If-Modified-Since")
        if ims:
            since = email.utils.mktime_tz(email.utils.parsedate_tz(ims))
            if rec["mtime"] <= since:
                return web.Response(status=304)
        return web.Response(body=rec["body"], headers={
            "Last-Modified": email.utils.formatdate(rec["mtime"], usegmt=True)})

    up_app = web.Application()
    up_app.router.add_get("/testrepo/{arch}/{filename}", stub)
    up = TestServer(up_app)
    await up.start_server()

    cache_dir = os.path.join(base, "cache")
    cfg = _cfg(cache_dir, db_ttl=3600, extra_repos=[
        Repo("test", ["http://127.0.0.1:%d/testrepo/$arch" % up.port])])
    app = build_app(cfg)
    mirror = TestServer(app)
    await mirror.start_server()
    try:
        now = time.time()
        upstream["test.db"] = dict(body=b"DB1", mtime=now - 60, calls=0)
        db_url = str(mirror.make_url("/test/os/x86_64/test.db"))
        cached_db = os.path.join(cache_dir, "test/os/x86_64/test.db")

        async with ClientSession() as http:
            async with http.get(db_url) as r:
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 1

            # within TTL: served locally, no upstream contact
            async with http.get(db_url) as r:
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 1

            # past TTL: the request waits for and delivers the fresh copy
            past = now - 7200
            os.utime(cached_db, (past, past))
            async with http.get(db_url) as r:
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 2

            # past TTL with a dead upstream: refresh fails fast (connection
            # refused), stale copy is served without eating the wait budget
            os.utime(cached_db, (past, past))
            await up.close()
            async with http.get(db_url) as r:
                assert r.status == 200 and await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 2
    finally:
        await mirror.close()
        if not up.closed:
            await up.close()


async def test_fresh_wait(base: str) -> None:
    """A slow upstream must not stall clients: past FRESH_WAIT the cached
    copy is served while the fresh retrieval continues in the background."""
    upstream: dict[str, dict] = {}

    async def stub(request: web.Request) -> web.Response:
        rec = upstream[request.match_info["filename"]]
        rec["calls"] += 1
        ims = request.headers.get("If-Modified-Since")
        if ims:
            since = email.utils.mktime_tz(email.utils.parsedate_tz(ims))
            if rec["mtime"] <= since:
                return web.Response(status=304)
        if rec.get("delay"):
            await asyncio.sleep(rec["delay"])
        return web.Response(body=rec["body"], headers={
            "Last-Modified": email.utils.formatdate(rec["mtime"], usegmt=True)})

    up_app = web.Application()
    up_app.router.add_get("/testrepo/{arch}/{filename}", stub)
    up = TestServer(up_app)
    await up.start_server()

    cache_dir = os.path.join(base, "cache")
    cfg = _cfg(cache_dir, db_ttl=0, fresh_wait=0.5, extra_repos=[
        Repo("test", ["http://127.0.0.1:%d/testrepo/$arch" % up.port])])
    app = build_app(cfg)
    mirror = TestServer(app)
    await mirror.start_server()
    try:
        now = time.time()
        upstream["test.db"] = dict(body=b"DB1", mtime=now - 60, calls=0)
        db_url = str(mirror.make_url("/test/os/x86_64/test.db"))
        cached_db = os.path.join(cache_dir, "test/os/x86_64/test.db")

        async with ClientSession() as http:
            async with http.get(db_url) as r:  # first fetch: blocking
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 1

            # upstream becomes slow AND has a newer db: the request must
            # return the cached copy within the wait budget...
            upstream["test.db"].update(body=b"DB2", mtime=now + 5, delay=3)
            started = time.time()
            async with http.get(db_url) as r:
                assert await r.read() == b"DB1"
            elapsed = time.time() - started
            assert elapsed < 2.5, "stale fallback took %.1fs" % elapsed

            # ...while the retrieval keeps running and lands in the cache
            assert await eventually(lambda: open(cached_db, "rb").read() == b"DB2",
                                    timeout=10)
            async with http.get(db_url) as r:  # next request gets the fresh db
                assert await r.read() == b"DB2"
    finally:
        await mirror.close()
        if not up.closed:
            await up.close()


async def test_mirror_flow(base: str) -> None:
    upstream: dict[str, dict] = {}

    upstream: dict[str, dict] = {}
    missing = {"calls": 0}

    async def stub(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        rec = upstream.get(filename)
        if rec is None:
            missing["calls"] += 1
            return web.Response(status=404, text="nope\n")
        rec["calls"] += 1
        ims = request.headers.get("If-Modified-Since")
        if ims:
            since = email.utils.mktime_tz(email.utils.parsedate_tz(ims))
            if rec["mtime"] <= since:
                return web.Response(status=304)
        headers = {"Last-Modified": email.utils.formatdate(rec["mtime"], usegmt=True)}
        if rec.get("cl_delta"):
            # declare more bytes than we send, then close abruptly: emulates
            # the GitHub Pages edge that serves short bodies with a stale
            # Content-Length
            resp = web.StreamResponse(status=200, headers=headers)
            resp.content_length = len(rec["body"]) + rec["cl_delta"]
            await resp.prepare(request)
            await resp.write(rec["body"])
            resp.force_close()
            request.transport.close()
            return resp
        return web.Response(body=rec["body"], headers=headers)

    up_app = web.Application()
    up_app.router.add_get("/testrepo/{arch}/{filename}", stub)
    up = TestServer(up_app)
    await up.start_server()

    cache_dir = os.path.join(base, "cache")
    cfg = _cfg(cache_dir, extra_repos=[
        Repo("test", ["http://127.0.0.1:%d/testrepo/$arch" % up.port])])
    app = build_app(cfg)
    mirror = TestServer(app)
    await mirror.start_server()
    try:
        base_url = str(mirror.make_url(""))
        now = time.time()
        upstream[PKG] = dict(body=b"PKG1", mtime=now - 60, calls=0)
        pkg_url = base_url + "/test/os/x86_64/" + PKG
        cached_pkg = os.path.join(cache_dir, "test/os/x86_64/" + PKG)

        async with ClientSession() as http:
            # miss: streams from upstream and fills the cache
            async with http.get(pkg_url) as r:
                assert r.status == 200, r.status
                assert await r.read() == b"PKG1"
            assert open(cached_pkg, "rb").read() == b"PKG1"

            # hit: immutable package is served from cache even when the
            # upstream (wrongly) changes it; no upstream contact at all
            upstream[PKG]["body"] = b"PKG2"
            async with http.get(pkg_url) as r:
                assert await r.read() == b"PKG1"
            assert upstream[PKG]["calls"] == 1

            # 3-segment local layout reaches the same cache entry
            async with http.get(base_url + "/test/x86_64/" + PKG) as r:
                assert await r.read() == b"PKG1"
            assert upstream[PKG]["calls"] == 1

            # metadata: first fetch is blocking; a stale request (ttl=0:
            # everything older than now) triggers a fresh retrieval that the
            # request itself waits for and delivers
            db_url = base_url + "/test/os/x86_64/test.db"
            cached_db = os.path.join(cache_dir, "test/os/x86_64/test.db")
            upstream["test.db"] = dict(body=b"DB1", mtime=now - 60, calls=0)
            async with http.get(db_url) as r:
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 1
            async with http.get(db_url) as r:  # unchanged upstream -> 304
                assert await r.read() == b"DB1"
            assert upstream["test.db"]["calls"] == 2
            assert open(cached_db, "rb").read() == b"DB1"
            upstream["test.db"].update(body=b"DB2", mtime=now + 5)
            async with http.get(db_url) as r:  # stale: fresh DB2 delivered
                assert await r.read() == b"DB2"
            assert upstream["test.db"]["calls"] == 3
            assert open(cached_db, "rb").read() == b"DB2"

            # upstream declaring more bytes than it sends (a genuinely
            # truncated transfer - the proxy requests identity encoding, so
            # a Content-Length mismatch can never be a variant artifact):
            # the stream aborts, nothing lands in the cache, and further
            # requests keep retrying the upstream (truncations are never
            # negative-cached)
            upstream["lie.db"] = dict(body=b"DB-LIE", mtime=now, calls=0, cl_delta=3)
            lie_cached = os.path.join(cache_dir, "test/os/x86_64/lie.db")
            for _ in range(2):
                try:
                    async with http.get(base_url + "/test/os/x86_64/lie.db") as r:
                        await r.read()
                except (ClientError, OSError):
                    pass
                else:
                    raise AssertionError("truncated upstream must fail the transfer")
            assert not os.path.exists(lie_cached)
            assert upstream["lie.db"]["calls"] == 2, \
                "truncations must not be negative-cached"

            # upstream 404 for a missing package passes through, and an
            # unknown repository is a local 404; the definitive 404 is
            # negative-cached, so the repeated request skips the upstream
            async with http.get(
                    base_url + "/test/os/x86_64/gone-1.0-1-x86_64.pkg.tar.zst") as r:
                assert r.status == 404
            assert missing["calls"] == 1
            async with http.get(
                    base_url + "/test/os/x86_64/gone-1.0-1-x86_64.pkg.tar.zst") as r:
                assert r.status == 404
            assert missing["calls"] == 1, "repeat miss must hit the negative cache"
            async with http.get(base_url + "/nope/os/x86_64/nope.db") as r:
                assert r.status == 404 and "unknown repository" in await r.text()

            # wait for the background refetch of DB2, then kill the upstream:
            # stale db still served, packages from cache
            assert await eventually(lambda: upstream["test.db"]["calls"] >= 3)
            await up.close()
            calls_at_death = upstream["test.db"]["calls"]
            async with http.get(db_url) as r:
                assert r.status == 200 and await r.read() == b"DB2"
            async with http.get(pkg_url) as r:
                assert r.status == 200 and await r.read() == b"PKG1"
            await asyncio.sleep(0.2)  # any scheduled refresh fails quietly
            assert upstream["test.db"]["calls"] == calls_at_death
    finally:
        await mirror.close()
        if not up.closed:
            await up.close()


def test_from_env(base: str) -> None:
    """from_env() defaults: repository/mirror lists are deployment
    configuration (docker-compose.yml), not code defaults."""
    keys = ("EXTRA_REPOS", "OFFICIAL_REPOS", "OFFICIAL_MIRRORS",
            "CACHE_SIZE", "CACHE_AGE", "DB_TTL", "FRESH_WAIT",
            "KEEP_VERSIONS", "GC_INTERVAL", "LISTEN_ADDR", "LISTEN_PORT",
            "CACHE_DIR")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        cfg = Config.from_env()
        assert cfg.official_repos == ["core", "extra", "multilib"]
        assert cfg.official_mirrors == [
            "https://geo.mirror.pkgbuild.com/$repo/os/$arch",
            "https://mirror.rackspace.com/archlinux/$repo/os/$arch",
        ]
        assert cfg.extra_repos == [], "extra repos belong to the deployment env"

        os.environ["OFFICIAL_REPOS"] = "core extra multilib core-testing"
        os.environ["OFFICIAL_MIRRORS"] = "https://a/$$repo/os/$$arch https://b/$$repo/os/$$arch"
        os.environ["EXTRA_REPOS"] = "x=https://x.example/$arch ;\ny=https://y.example/$arch"
        cfg = Config.from_env()
        assert cfg.official_repos == ["core", "extra", "multilib", "core-testing"]
        assert cfg.official_mirrors == ["https://a/$$repo/os/$$arch",
                                        "https://b/$$repo/os/$$arch"]
        assert [(r.name, r.mirrors) for r in cfg.extra_repos] == [
            ("x", ["https://x.example/$arch"]), ("y", ["https://y.example/$arch"])]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


async def _get(http: ClientSession, url: str) -> tuple[bytes, int]:
    async with http.get(url) as r:
        return await r.read(), r.status


async def test_single_flight(base: str) -> None:
    """Concurrent first requests for the same uncached file share one
    upstream download (per-file lock, package-miss semantics for packages
    and dbs alike): the other clients wait for the first and are then
    served from the cache."""
    upstream: dict[str, dict] = {}

    async def stub(request: web.Request) -> web.Response:
        rec = upstream[request.match_info["filename"]]
        rec["calls"] += 1
        await asyncio.sleep(0.3)  # let the concurrent clients pile up
        return web.Response(body=rec["body"], headers={
            "Last-Modified": email.utils.formatdate(rec["mtime"], usegmt=True)})

    up_app = web.Application()
    up_app.router.add_get("/testrepo/{arch}/{filename}", stub)
    up = TestServer(up_app)
    await up.start_server()

    cache_dir = os.path.join(base, "cache")
    cfg = _cfg(cache_dir, extra_repos=[
        Repo("test", ["http://127.0.0.1:%d/testrepo/$arch" % up.port])])
    app = build_app(cfg)
    mirror = TestServer(app)
    await mirror.start_server()
    try:
        now = time.time()
        async with ClientSession() as http:
            for filename, body in (("test.db", b"DB1"),
                                   ("solo-1.0-1-x86_64.pkg.tar.zst", b"PKG1")):
                upstream[filename] = dict(body=body, mtime=now - 60, calls=0)
                url = str(mirror.make_url("/test/os/x86_64/" + filename))
                cached = os.path.join(cache_dir, "test/os/x86_64/" + filename)
                results = await asyncio.gather(*[_get(http, url)] * 3)
                assert [status for _, status in results] == [200, 200, 200], results
                assert [body_ for body_, _ in results] == [body] * 3, results
                assert upstream[filename]["calls"] == 1, \
                    "concurrent first fetches must share one upstream download"
                assert open(cached, "rb").read() == body
    finally:
        await mirror.close()
        if not up.closed:
            await up.close()


async def test_ranges(base: str) -> None:
    """Byte-range support: pacman resumes interrupted downloads by
    re-requesting the missing tail with a Range header; a plain 200
    answer makes curl abort the resume ('HTTP server does not seem to
    support byte ranges')."""
    upstream: dict[str, dict] = {}
    seen_ranges: dict[str, list] = {}

    async def stub(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        rec = upstream[filename]
        rec["calls"] += 1
        body: bytes = rec["body"]
        rng = request.headers.get("Range")
        seen_ranges.setdefault(filename, []).append(rng)
        if rng is not None and rec.get("honor", True):
            m = re.match(r"^bytes=(\d*)-(\d*)$", rng)
            if m and (m[1] or m[2]):
                if m[1]:
                    start, end = int(m[1]), int(m[2] or len(body) - 1)
                else:  # suffix: last N bytes
                    start, end = max(0, len(body) - int(m[2])), len(body) - 1
                end = min(end, len(body) - 1)
                return web.Response(status=206, body=body[start:end + 1],
                                    headers={"Content-Range": "bytes %d-%d/%d"
                                             % (start, end, len(body))})
        return web.Response(body=body)

    up_app = web.Application()
    up_app.router.add_get("/testrepo/{arch}/{filename}", stub)
    up = TestServer(up_app)
    await up.start_server()

    cache_dir = os.path.join(base, "cache")
    cfg = _cfg(cache_dir, extra_repos=[
        Repo("test", ["http://127.0.0.1:%d/testrepo/$arch" % up.port])])
    app = build_app(cfg)
    mirror = TestServer(app)
    await mirror.start_server()
    try:
        body = bytes(range(64))
        now = time.time()
        upstream[PKG] = dict(body=body, mtime=now - 60, calls=0)
        upstream["stubborn-1.0-1-x86_64.pkg.tar.zst"] = dict(
            body=body, mtime=now - 60, calls=0, honor=False)
        upstream["test.db"] = dict(body=body, mtime=now - 60, calls=0)
        base_url = str(mirror.make_url(""))
        pkg_url = base_url + "/test/os/x86_64/" + PKG
        cached_pkg = os.path.join(cache_dir, "test/os/x86_64/" + PKG)
        stubborn_url = base_url + "/test/os/x86_64/stubborn-1.0-1-x86_64.pkg.tar.zst"
        cached_stubborn = os.path.join(
            cache_dir, "test/os/x86_64/stubborn-1.0-1-x86_64.pkg.tar.zst")
        db_url = base_url + "/test/os/x86_64/test.db"
        cached_db = os.path.join(cache_dir, "test/os/x86_64/test.db")

        async with ClientSession() as http:
            # resume against an uncached file: the range is relayed to the
            # upstream (the 206 comes from there) and nothing is cached
            async with http.get(pkg_url, headers={"Range": "bytes=10-19"}) as r:
                assert r.status == 206, r.status
                assert r.headers["Content-Range"] == "bytes 10-19/64"
                assert await r.read() == body[10:20]
            assert seen_ranges[PKG] == ["bytes=10-19"], "range must reach upstream"
            assert not os.path.exists(cached_pkg), \
                "a partial transfer cannot fill the cache"

            # plain GET fills the cache and advertises range support
            async with http.get(pkg_url) as r:
                assert r.status == 200 and await r.read() == body
                assert r.headers["Accept-Ranges"] == "bytes"

            # cached file: slices are served locally, upstream never asked
            for header, want in (("bytes=0-3", body[0:4]),
                                 ("bytes=60-", body[60:]),
                                 ("bytes=-5", body[59:]),
                                 ("bytes=10-100", body[10:])):
                async with http.get(pkg_url, headers={"Range": header}) as r:
                    assert r.status == 206, (header, r.status)
                    assert await r.read() == want, header
            assert upstream[PKG]["calls"] == 2

            # resuming past EOF (a .part for a smaller, replaced file): 416
            async with http.get(pkg_url, headers={"Range": "bytes=64-"}) as r:
                assert r.status == 416, r.status
                assert r.headers["Content-Range"] == "bytes */64"

            # multi-range and other unsupported headers: ignored, full 200
            async with http.get(pkg_url, headers={"Range": "bytes=0-1,5-9"}) as r:
                assert r.status == 200 and await r.read() == body

            # HEAD must answer 206 headers without any body bytes (aiohttp
            # does not suppress StreamResponse writes itself)
            reader, writer = await asyncio.open_connection(mirror.host, mirror.port)
            writer.write(("HEAD /test/os/x86_64/%s HTTP/1.1\r\n"
                          "Host: x\r\nRange: bytes=0-3\r\n"
                          "Connection: close\r\n\r\n" % PKG).encode())
            await writer.drain()
            raw = await reader.read()
            writer.close()
            head, _, rest = raw.partition(b"\r\n\r\n")
            assert b" 206 " in head.split(b"\r\n")[0], raw
            assert rest == b"", "HEAD response must not carry a body: %r" % raw

            # upstream ignores the range (answers 200 full): the proxy
            # fetches the whole file into the cache while forwarding only
            # the requested window
            async with http.get(stubborn_url, headers={"Range": "bytes=10-19"}) as r:
                assert r.status == 206
                assert r.headers["Content-Range"] == "bytes 10-19/64"
                assert await r.read() == body[10:20]
            assert open(cached_stubborn, "rb").read() == body, \
                "the range-ignoring upstream fetch must still fill the cache"
            # ...so the retry (or the next client) resumes from the cache
            async with http.get(stubborn_url, headers={"Range": "bytes=20-"}) as r:
                assert r.status == 206 and await r.read() == body[20:]

            # a db resumes the same way: relayed 206, nothing cached
            async with http.get(db_url, headers={"Range": "bytes=-7"}) as r:
                assert r.status == 206
                assert r.headers["Content-Range"] == "bytes 57-63/64"
                assert await r.read() == body[57:]
            assert not os.path.exists(cached_db)
    finally:
        await mirror.close()
        if not up.closed:
            await up.close()


TESTS = [
    ("vercmp", test_vercmp),
    ("parsers", test_parsers),
    ("range-math", test_range_math),
    ("gc", test_gc),
    ("from-env", test_from_env),
    ("mirror-flow", test_mirror_flow),
    ("db-ttl", test_db_ttl),
    ("fresh-wait", test_fresh_wait),
    ("single-flight", test_single_flight),
    ("byte-ranges", test_ranges),
]


def main() -> int:
    os.makedirs(TMP_BASE, exist_ok=True)
    failed = 0
    for name, fn in TESTS:
        base = tempfile.mkdtemp(prefix=name + "-", dir=TMP_BASE)
        try:
            if inspect.iscoroutinefunction(fn):
                asyncio.run(fn(base))
            else:
                fn(base)
            print("ok   %s" % name)
        except Exception:
            failed += 1
            print("FAIL %s\n%s" % (name, traceback.format_exc()))
        finally:
            shutil.rmtree(base, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
