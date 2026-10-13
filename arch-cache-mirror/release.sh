#!/bin/bash
# release.sh - publish arch-cache-mirror to Docker Hub as a multi-arch image
#
# Builds and pushes BOTH architecture images, then assembles the shared
# `latest` tag as an OCI image index (manifest list) referencing them:
#
#   - amd64: built on this machine (the plain Dockerfile)
#   - arm64: built on the Pi (Dockerfile.alarm; building it anywhere else
#     means a qemu cross-build, an order of magnitude slower - see README
#     "Raspberry Pi / arm64")
#
# ALWAYS both + the index: re-pointing `latest` at only one freshly pushed
# architecture would silently serve stale code to the other platform.
# `docker run <repo>:latest` (or compose without `platform:`) then picks
# the right image automatically - same semantics on both arches.
#
# Requirements:
# - `docker login` on this machine AND on the Pi (each machine pushes its
#   own build)
# - ssh access to the Pi (sources are synced via tar-over-ssh; the Pi has
#   no rsync)
# Env overrides: HUB_REPO (plartemyev/arch-cache-mirror),
#   PI_HOST (root@10.11.0.22), PI_DIR (/root/arch-cache-mirror)

set -euo pipefail

HUB_REPO="${HUB_REPO:-plartemyev/arch-cache-mirror}"
PI_HOST="${PI_HOST:-root@10.11.0.22}"
PI_DIR="${PI_DIR:-/root/arch-cache-mirror}"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# --- amd64: build + push on this machine -----------------------------------
say "building ${HUB_REPO}:amd64"
docker build -t "${HUB_REPO}:amd64" .
arch="$(docker image inspect --format '{{.Architecture}}' "${HUB_REPO}:amd64")"
[ "$arch" = amd64 ] || die "local image is $arch, expected amd64 (release from an x86_64 host)"
say "pushing ${HUB_REPO}:amd64"
docker push "${HUB_REPO}:amd64" || die "push failed - docker login first?"

# --- arm64: sync sources, build + push on the Pi ----------------------------
say "syncing sources to ${PI_HOST}:${PI_DIR}"
tar czf - --exclude=./tmp --exclude=./cache --exclude=__pycache__ \
	--exclude='*.pyc' --exclude=docker-compose.override.yml . \
	| ssh "$PI_HOST" "mkdir -p '$PI_DIR' && tar xzf - -C '$PI_DIR'"
say "building ${HUB_REPO}:arm64 on the Pi"
ssh "$PI_HOST" "cd '$PI_DIR' && docker build -f Dockerfile.alarm -t '${HUB_REPO}:arm64' ." \
	|| die "arm64 build failed on ${PI_HOST}"
arch="$(ssh "$PI_HOST" "docker image inspect --format '{{.Architecture}}' '${HUB_REPO}:arm64'")"
[ "$arch" = arm64 ] || die "Pi image is $arch, expected arm64"
say "pushing ${HUB_REPO}:arm64"
ssh "$PI_HOST" "docker push '${HUB_REPO}:arm64'" \
	|| die "Pi push failed - docker login on ${PI_HOST} first?"

# --- the multi-arch index ----------------------------------------------------
say "assembling ${HUB_REPO}:latest (OCI image index)"
export DOCKER_CLI_EXPERIMENTAL=enabled  # manifest commands on older CLIs
docker manifest rm "${HUB_REPO}:latest" >/dev/null 2>&1 || true
docker manifest create "${HUB_REPO}:latest" \
	--amend "${HUB_REPO}:amd64" \
	--amend "${HUB_REPO}:arm64" >/dev/null
docker manifest push "${HUB_REPO}:latest"

say "done - docker manifest inspect ${HUB_REPO}:latest:"
docker manifest inspect "${HUB_REPO}:latest" | grep -E '"architecture"' || true
