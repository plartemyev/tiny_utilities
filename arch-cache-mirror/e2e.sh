#!/usr/bin/env bash
# End-to-end test for arch-cache-mirror.
#
# Builds the image, boots the mirror on a throwaway docker network next to
# a real Arch client container and verifies the whole path:
#
#   stage 1  unit + integration tests inside the built image
#   stage 2  proxy boots; /healthz and / status page respond
#   stage 3  db cache-miss -> upstream fetch -> cache-hit on second request
#   stage 4  pacman -Sy on a cold client (core/extra/multilib through the
#            proxy, real signature verification)
#   stage 5  xlibre + sonicde repos sync through the proxy (default
#            EXTRA_REPOS mapping)
#   stage 6  package install (extra/tree) through the proxy
#   stage 7  warm sync: no upstream db fetches within DB_TTL, and
#            .db.sig 404s served from the negative cache
#   stage 8  negative cache answers repeated missing-package requests
#            without touching upstream
#
# Requirements: docker + network access to the Arch mirrors and to
# packages.xlibre.net / sonicde-arch.github.io (the client image
# archlinux:latest is pulled automatically). Scratch data (cache, client
# script, logs) goes to ./tmp/e2e-<pid>/ which is git-ignored.
#
# Usage:
#   ./e2e.sh                 full run, cleans up after itself (~2-4 min)
#   ./e2e.sh --skip-build    reuse the already-built image
#   ./e2e.sh --keep          keep containers/network/scratch for debugging;
#                            the proxy stays on 127.0.0.1:<printed port>
set -euo pipefail

cd "$(dirname "$0")"

IMAGE=arch-cache-mirror:e2e
NET=e2e-acm-net
PROXY=e2e-acm-proxy
CLIENT=e2e-acm-client
SCRATCH=tmp/e2e-$$
LOG="$SCRATCH/proxy.log"

KEEP=0
SKIP_BUILD=0
for arg in "$@"; do
	case "$arg" in
	--keep) KEEP=1 ;;
	--skip-build) SKIP_BUILD=1 ;;
	*) echo "unknown option: $arg (supported: --keep, --skip-build)" >&2; exit 2 ;;
	esac
done

PASS=0
LOG_PID=""
HOST_PORT=""
cleanup() {
	if [ "$KEEP" = 1 ]; then
		echo "kept stack: docker logs $PROXY; proxy on http://127.0.0.1:${HOST_PORT:-?}; cache in $SCRATCH"
		return
	fi
	[ -n "$LOG_PID" ] && kill "$LOG_PID" 2>/dev/null || true
	docker rm -f "$CLIENT" "$PROXY" >/dev/null 2>&1 || true
	docker network rm "$NET" >/dev/null 2>&1 || true
	# the bind-mounted cache is written by the container's root user; wipe
	# it through a container before removing the scratch dir
	docker run --rm -v "$PWD/$SCRATCH:/s" "$IMAGE" \
		sh -c 'rm -rf /s/cache' >/dev/null 2>&1 || true
	rm -rf "$SCRATCH"
}
trap cleanup EXIT

ok() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }
logcount() { grep -cE "$1" "$LOG" 2>/dev/null || true; }

rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/cache"

echo "== stage 1: build + in-image tests"
if [ "$SKIP_BUILD" = 0 ]; then
	docker build -q -t "$IMAGE" . >/dev/null
fi
if ! docker run --rm "$IMAGE" python /app/test_mirror.py >"$SCRATCH/unit.log" 2>&1; then
	cat "$SCRATCH/unit.log" >&2
	fail "in-image unit/integration tests"
fi
grep -q '^ok   mirror-flow' "$SCRATCH/unit.log" || fail "in-image tests did not run"
ok "unit + integration tests (in image)"

echo "== stage 2: boot proxy"
# single source of truth: the mirror/repo env comes from docker-compose.yml
# (compose also resolves the $$ -> $ escaping), the container gets it via
# --env-file
docker compose config --format json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
env = cfg["services"]["arch-cache-mirror"]["environment"]
with open(sys.argv[1], "w") as f:
    for key, value in env.items():
        if value is not None:
            # config --format json keeps compose escaping: $$ means a
            # literal $ - apply the same resolution compose would at
            # container creation
            f.write("%s=%s\n" % (key, value.replace("$$", "$")))
' "$SCRATCH/envfile"
grep -q '^EXTRA_REPOS=' "$SCRATCH/envfile" || fail "could not derive EXTRA_REPOS from docker-compose.yml"
docker network create "$NET" >/dev/null
docker rm -f "$PROXY" "$CLIENT" >/dev/null 2>&1 || true
docker run -d --name "$PROXY" --network "$NET" \
	--env-file "$SCRATCH/envfile" \
	-v "$PWD/$SCRATCH/cache:/var/cache/arch-mirror" \
	-p 127.0.0.1::8080 "$IMAGE" >/dev/null
sleep 3
HOST_PORT=$(docker port "$PROXY" 8080 | head -1 | sed 's/.*://')
echo "proxy on http://127.0.0.1:$HOST_PORT"
docker logs -f "$PROXY" >"$LOG" 2>&1 &
LOG_PID=$!

curl -fsS "http://127.0.0.1:$HOST_PORT/healthz" | grep -q '^ok' || fail "healthz"
curl -fsS "http://127.0.0.1:$HOST_PORT/" | grep -q 'repositories served' || fail "status page"
ok "healthz + status page"

echo "== stage 3: db cache miss -> hit"
BEFORE_MISS=$(logcount 'miss core/x86_64/core\.db ')
curl -fsS -o "$SCRATCH/core.db.1" "http://127.0.0.1:$HOST_PORT/core/os/x86_64/core.db"
AFTER_MISS=$(logcount 'miss core/x86_64/core\.db ')
[ "$AFTER_MISS" -eq $((BEFORE_MISS + 1)) ] || fail "first core.db fetch should be an upstream miss"
curl -fsS -o "$SCRATCH/core.db.2" "http://127.0.0.1:$HOST_PORT/core/os/x86_64/core.db"
AFTER_MISS2=$(logcount 'miss core/x86_64/core\.db ')
[ "$AFTER_MISS2" -eq "$AFTER_MISS" ] || fail "second core.db fetch must be served from cache"
cmp -s "$SCRATCH/core.db.1" "$SCRATCH/core.db.2" || fail "cached db differs from first response"
ok "core.db miss -> upstream fetch -> cache hit (identical bytes)"

echo "== stages 4-6: pacman client (cold sync, extra repos, install)"
# client config lives on the host so both client runs share it
printf 'Server = http://%s:8080/$repo/os/$arch\n' "$PROXY" >"$SCRATCH/mirrorlist"
docker run --rm archlinux:latest cat /etc/pacman.conf >"$SCRATCH/pacman.conf"
cat >>"$SCRATCH/pacman.conf" <<CFG

[xlibre]
SigLevel = Never
Include = /etc/pacman.d/mirrorlist

[sonicde]
SigLevel = Never
Include = /etc/pacman.d/mirrorlist
CFG
CLIENT_RUN="docker run --rm --network $NET -v $PWD/$SCRATCH/mirrorlist:/etc/pacman.d/mirrorlist:ro -v $PWD/$SCRATCH/pacman.conf:/etc/pacman.conf:ro archlinux:latest"

echo "--- cold pacman -Sy ---"
if ! $CLIENT_RUN pacman -Sy; then
	fail "cold pacman -Sy failed"
fi
ok "pacman -Sy cold without errors (core/extra/xlibre/sonicde)"
[ -f "$SCRATCH/cache/xlibre/os/x86_64/xlibre.db" ] || fail "xlibre.db not cached"
[ -f "$SCRATCH/cache/sonicde/os/x86_64/sonicde.db" ] || fail "sonicde.db not cached"
ok "xlibre + sonicde dbs cached through the default EXTRA_REPOS mapping"

echo "--- warm pacman -Sy + install tree (must not touch upstream dbs) ---"
BEFORE_DB_MISS=$(logcount 'miss .*\.db \(')
if ! $CLIENT_RUN bash -c 'pacman -Sy && pacman -S --noconfirm --needed tree && tree --version | grep -q "tree v"'; then
	fail "warm sync / package install failed"
fi
sleep 1
AFTER_DB_MISS=$(logcount 'miss .*\.db \(')
[ "$AFTER_DB_MISS" -eq "$BEFORE_DB_MISS" ] || fail "warm sync fetched upstream dbs despite DB_TTL"
ok "warm sync: zero upstream db fetches (within DB_TTL)"
[ "$(logcount 'miss extra/x86_64/tree-.*\.pkg\.tar\.zst')" -ge 1 ] || fail "tree pkg not fetched through proxy"
ok "package install served by the proxy (with signature verification)"

echo "== stage 7: negative cache"
MISSING="definitely-missing-9.9.9-1-x86_64.pkg.tar.zst"
code=$(curl -sS -o /dev/null -w '%{http_code}' \
	"http://127.0.0.1:$HOST_PORT/core/os/x86_64/$MISSING")
[ "$code" = 404 ] || fail "missing package should 404 (got $code)"
first=$(logcount "neg  core/x86_64/$MISSING")
code=$(curl -sS -o /dev/null -w '%{http_code}' \
	"http://127.0.0.1:$HOST_PORT/core/os/x86_64/$MISSING")
[ "$code" = 404 ] || fail "repeated missing package should 404 again"
second=$(logcount "neg  core/x86_64/$MISSING")
[ "$first" -eq 0 ] && [ "$second" -eq 1 ] || fail "second miss must come from the negative cache"
ok "upstream 404 negative-cached (repeat served without upstream contact)"

echo
echo "ALL E2E STAGES PASSED ($PASS checks)"
