#!/usr/bin/env bash
# Nightly host-side entrypoint (cron). Builds the builder image if stale,
# keeps the repo server running, runs the build container once (flock-guarded
# against overlap) and logs to tmp/nightly-<date>.log.
#
# Crontab entry (03:17 — off the busy hour marks):
#   17 3 * * * /home/pasha/PycharmProjects/tiny_utilities/zcode-build/nightly.sh
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p tmp repo cache gnupg
printf 'ok\n' > repo/healthz   # repo-server healthcheck probe target

LOG="tmp/nightly-$(date +%Y%m%d).log"
exec >>"$LOG" 2>&1
echo "=== nightly run $(date -u +%FT%TZ) ==="

exec 9> tmp/nightly.lock
if ! flock -n 9; then
    echo "previous nightly run still active; skipping"
    exit 0
fi

# fail visible, fail early: a broken repo server means targets install stale
docker compose up -d --build repo

# rebuild only when the Dockerfile/scripts changed (fast no-op otherwise)
docker build -q -t zcode-builder .

# --network host: some hosts' docker default bridge cannot reach github.com
# (verified on one deployment host: bridge blackholes it while the host
# itself reaches it); harmless everywhere else, and the build only talks
# out (github, npm registry, nodejs.org)
docker run --rm \
    --network host \
    -u "$(id -u):$(id -g)" \
    -e ZCODE_REF="${ZCODE_REF:-}" \
    -e ZCODE_ELECTRON_MIRROR="${ZCODE_ELECTRON_MIRROR:-}" \
    -v "$PWD/cache:/cache" \
    -v "$PWD/repo:/repo" \
    -v "$PWD/gnupg:/cache/gnupg" \
    zcode-builder

echo "=== nightly run finished $(date -u +%FT%TZ) ==="
