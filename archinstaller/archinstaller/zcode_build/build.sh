#!/usr/bin/env bash
# On-target build orchestrator: checks out the latest zai-org/ZCode, strips
# the telemetry surface, builds the zcode (CLI/TUI/web) and — with
# ZCODE_DESKTOP=1 — zcode-desktop packages, and publishes them into a local
# pacman repository at <script-dir>/out. The [zcode] repository registered
# in /etc/pacman.conf points there (Server = file:///home/<user>/zcode-build/out),
# so a plain `pacman -Syu` picks up whatever this script last published.
#
# Runs as a regular user (makepkg refuses root); everything it needs is
# fetched into the persistent cache/ next to this script, so re-runs are
# incremental and a nightly run with unchanged upstream exits after the
# fetch (see the up-to-date check below). Invoked three ways:
#   - by archinstaller over SSH right after the first boot (initial build);
#   - nightly by the zcode-update.timer user unit;
#   - manually: cd ~/zcode-build && ./build.sh
#
# Layout: out/ is the served pacman repository (packages + zcode.db);
# cache/ is the persistent state (upstream shallow checkout, pinned Node,
# pnpm store, electron cache, gem home); tmp/ is per-run scratch, wiped upfront.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE="${ZCODE_CACHE:-$DIR/cache}"
WORK="${ZCODE_WORK:-$DIR/tmp}"
OUT="${ZCODE_OUT:-$DIR/out}"
REF="${ZCODE_REF:-origin/main}"
UPSTREAM_URL="${ZCODE_UPSTREAM_URL:-https://github.com/zai-org/ZCode.git}"
BUILD_DESKTOP="${ZCODE_DESKTOP:-0}"
ELECTRON_MIRROR="${ZCODE_ELECTRON_MIRROR:-}"   # default: upstream's npmmirror

log() { echo "[build] $(date -u +%H:%M:%S) $*"; }
die() { echo "[build] FAIL: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run as a regular user, not root (makepkg refuses root)"

# one build at a time: the nightly timer, manual runs and an archinstaller
# rerun must not race each other on the same cache
exec 9>"$DIR/.build.lock"
if ! flock -n 9; then
    die "another build is already running (holds $DIR/.build.lock)"
fi

mkdir -p "$CACHE" "$OUT" "$WORK" "$CACHE/home"
export HOME=$CACHE/home

for tool in git curl python3 makepkg repo-add tar xz zstd; do
    command -v "$tool" >/dev/null || die "missing required tool: $tool (pacman -S base-devel git)"
done
if [ "$BUILD_DESKTOP" = 1 ]; then
    for tool in ruby gem; do
        command -v "$tool" >/dev/null || die "ZCODE_DESKTOP=1 needs $tool (pacman -S ruby ruby-rubygems)"
    done
    # fpm (electron-builder's pacman target) is a ruby gem; keep it inside
    # the cache so the target's gem home stays untouched
    export GEM_HOME=$CACHE/gems
    export GEM_PATH=$GEM_HOME
    export PATH="$GEM_HOME/bin:$PATH"
    if ! command -v fpm >/dev/null; then
        gem install fpm --no-document
        log "installed fpm into $GEM_HOME"
    fi
fi

# ---------------------------------------------------------------------------
# Telemetry build-env hygiene: these are compile-time capability injections
# (scripts/build-time-config.mjs). Explicitly empty = the capability is
# compiled out; public checkouts have no config/private/ defaults anyway.
# ---------------------------------------------------------------------------
export ZCODE_ARMS_RUM_ENDPOINT=""
export ZCODE_TELEMETRY_REPORT_ENDPOINT=""
export ZCODE_AUTO_UPDATE=""
export COREPACK_ENABLE_PROJECT_SPEC=0
export ZCODE_DIST_BASE_URL=""
[ -n "$ELECTRON_MIRROR" ] && export ELECTRON_MIRROR

# ---------------------------------------------------------------------------
# 1. Persistent shallow checkout of upstream (cache/src). A fetch + forced
#    detach + clean keeps the tree byte-identical to the ref (our strip edits
#    never survive a failed/retried run) while --depth 1 keeps the transfer
#    at one tree instead of the whole history. ZCODE_SHALLOW=0 drops the
#    depth for exotic refs (old commit SHAs).
# ---------------------------------------------------------------------------
SRC=$CACHE/src
DEPTH="--depth 1"
[ "${ZCODE_SHALLOW:-1}" = 1 ] || DEPTH=""
if [ ! -d "$SRC/.git" ]; then
    git clone $DEPTH "$UPSTREAM_URL" "$SRC"
fi
for attempt in 1 2 3; do
    if git -C "$SRC" fetch $DEPTH --prune origin; then break; fi
    [ "$attempt" = 3 ] && die "git fetch of upstream failed 3 times"
    sleep $((attempt * 20))
done
if [ "$REF" != "origin/main" ]; then
    git -C "$SRC" fetch $DEPTH --prune origin "$REF"
    REF_AT=FETCH_HEAD
else
    REF_AT=$REF
fi
git -C "$SRC" checkout --force --detach "$REF_AT"
git -C "$SRC" clean -fdxq
COMMIT=$(git -C "$SRC" rev-parse --short=12 HEAD)
log "checkout $REF @ $COMMIT"

# ---------------------------------------------------------------------------
# 1b. Skip the build entirely when upstream and our scripts are unchanged:
#     the nightly timer then costs a fetch and nothing else. ZCODE_FORCE=1
#     overrides (e.g. after wiping the cache or pinning a different ref).
# ---------------------------------------------------------------------------
TOOLS_SHA=$(cat "$DIR/build.sh" "$DIR/strip-telemetry.sh" "$DIR/strip_telemetry.py" \
    "$DIR/verify-stripped.sh" "$DIR/packaging/zcode/PKGBUILD" "$DIR/packaging/zcode-wrapper" \
    "$DIR/packaging/zcode-desktop/PKGBUILD" \
    "$DIR/packaging/zcode-desktop/zcode-desktop.install" | sha256sum | cut -d' ' -f1)
if [ -z "${ZCODE_FORCE:-}" ] && [ -f "$OUT/build-stamp.txt" ]; then
    read -r _ _ STAMP_COMMIT _ STAMP_TOOLS STAMP_DESKTOP < "$OUT/build-stamp.txt" || true
    if [ "$COMMIT" = "${STAMP_COMMIT:-}" ] && [ "$TOOLS_SHA" = "${STAMP_TOOLS:-}" ] \
        && [ "$BUILD_DESKTOP" = "${STAMP_DESKTOP:-}" ]; then
        log "up to date ($COMMIT, tools $TOOLS_SHA); nothing to build (ZCODE_FORCE=1 overrides)"
        exit 0
    fi
fi

# hygiene: the private build-defaults file and any stray env files would
# re-enable telemetry at build time
[ ! -e "$SRC/config/private" ] || die "config/private exists in a public checkout?!"
[ ! -e "$SRC/.env" ] || die ".env exists in the checkout"
[ ! -e "$SRC/.env.local" ] || die ".env.local exists in the checkout"

# ---------------------------------------------------------------------------
# 2. Apply our customizations (telemetry strip)
# ---------------------------------------------------------------------------
bash "$DIR/strip-telemetry.sh" "$SRC"

# Build only the pacman target on Linux: AppImage/deb/rpm would need extra
# tooling (appimage tools, rpmbuild) and download more artifacts for targets
# we never ship.
BUNDLE_MJS=$SRC/packages/desktop/scripts/bundle.mjs
anchor='archBuilderFlagMap[arch],'
grep -qF "$anchor" "$BUNDLE_MJS" || die "bundle.mjs buildArgs anchor missing"
sed -i "s|$anchor|$anchor \"pacman\",|" "$BUNDLE_MJS"
log "desktop bundle limited to the pacman target"

# ---------------------------------------------------------------------------
# 3. Pinned toolchain (mise.toml is upstream's source of truth)
# ---------------------------------------------------------------------------
NODE_VERSION=$(sed -n 's/^node = "\(.*\)"/\1/p' "$SRC/mise.toml")
[ -n "$NODE_VERSION" ] || die "cannot read node pin from mise.toml"
PNPM_VERSION=$(sed -n 's/.*"pnpm@\([0-9][0-9.]*\)".*/\1/p' "$SRC/package.json" | head -1)
[ -n "$PNPM_VERSION" ] || die "cannot read pnpm pin from package.json"
NODE_TARBALL=$CACHE/node/node-v$NODE_VERSION-linux-x64.tar.xz
NODE_DIR=$CACHE/node/node-$NODE_VERSION
if [ ! -x "$NODE_DIR/bin/node" ]; then
    mkdir -p "$CACHE/node"
    cd "$CACHE/node"
    curl -fsSLO "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt"
    curl -fsSLO "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz"
    grep " node-v$NODE_VERSION-linux-x64.tar.xz\$" SHASUMS256.txt | sha256sum -c -
    mkdir -p "$NODE_DIR"
    tar -xJf "$NODE_DIR/../node-v$NODE_VERSION-linux-x64.tar.xz" -C "$NODE_DIR" --strip-components=1
    rm -f SHASUMS256.txt
    cd /
fi
# the pristine extracted runtime is vendored into packages as-is; the pnpm
# global install gets its own prefix so it never pollutes NODE_DIR
export PATH="$NODE_DIR/bin:$CACHE/pnpm-bin/bin:$PATH"
node --version
if [ ! -x "$CACHE/pnpm-bin/bin/pnpm" ]; then
    npm install --global "pnpm@$PNPM_VERSION" --prefix "$CACHE/pnpm-bin" >/dev/null
fi
pnpm --version
log "toolchain: node $NODE_VERSION, pnpm $PNPM_VERSION"

# ---------------------------------------------------------------------------
# 4. Build the CLI/TUI/web distribution
# ---------------------------------------------------------------------------
cd "$SRC"
export ELECTRON_CACHE=$CACHE/electron
pnpm install --no-frozen-lockfile --prefer-offline --store-dir "$CACHE/pnpm-store"
pnpm build:zcode
VERSION=$(node -p "require('./package.json').version")
TARBALL=$SRC/dist/zcode/releases/$VERSION/zcode-$VERSION.tar.gz
[ -f "$TARBALL" ] || die "build:zcode produced no tarball"
log "zcode dist $VERSION built"

bash "$DIR/verify-stripped.sh" "$SRC" cli

# ---------------------------------------------------------------------------
# 5. Build the desktop package (electron-builder, pacman target)
# ---------------------------------------------------------------------------
DESKTOP_ARTIFACT=""
if [ "$BUILD_DESKTOP" = 1 ]; then
    pnpm bundle:desktop -- --os linux --arch x64
    DESKTOP_ARTIFACT=$(ls "$SRC"/packages/desktop/dist/*linux*x64*.pkg.tar.zst 2>/dev/null | head -1)
    [ -n "$DESKTOP_ARTIFACT" ] || die "desktop bundle produced no pacman artifact"
    log "desktop artifact: $(basename "$DESKTOP_ARTIFACT")"

    bash "$DIR/verify-stripped.sh" "$SRC" desktop "$DESKTOP_ARTIFACT"
fi

# ---------------------------------------------------------------------------
# 6. Version policy: pkgrel 1 for a new upstream version, date-based for
#    same-version rebuilds (nightly runs must always compare as newer)
# ---------------------------------------------------------------------------
if ls "$OUT"/zcode-"$VERSION"-*.pkg.tar.zst >/dev/null 2>&1; then
    PKGREL=$(date -u +%Y%m%d)
else
    PKGREL=1
fi
log "packaging version $VERSION, pkgrel $PKGREL (from commit $COMMIT)"

# ---------------------------------------------------------------------------
# 7. Package: zcode (CLI + web, with the pinned Node runtime vendored)
# ---------------------------------------------------------------------------
PKGDIR=$WORK/pkg-zcode
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR/src/opt/zcode" "$PKGDIR/src/opt/zcode/node" "$PKGDIR/src/usr/bin"
tar -xzf "$TARBALL" -C "$PKGDIR/src/opt"   # contains the zcode/ directory
[ -x "$PKGDIR/src/opt/zcode/bin/zcode.mjs" ] || die "dist tarball layout unexpected"
tar -xJf "$NODE_TARBALL" -C "$PKGDIR/src/opt/zcode/node" --strip-components=1
[ -x "$PKGDIR/src/opt/zcode/node/bin/node" ] || die "vendored node extraction failed"
install -m 755 "$DIR/packaging/zcode-wrapper" "$PKGDIR/src/usr/bin/zcode"
tar -C "$PKGDIR/src" -cf "$PKGDIR/zcode-tree.tar" opt usr

sed -e "s/@VERSION@/$VERSION/" -e "s/@PKGREL@/$PKGREL/" \
    "$DIR/packaging/zcode/PKGBUILD" > "$PKGDIR/PKGBUILD"
cd "$PKGDIR"
makepkg --force --nodeps --noconfirm
ZCODE_PKG=$(ls zcode-"$VERSION"-"$PKGREL"-*.pkg.tar.zst)
[ -n "$ZCODE_PKG" ] || die "makepkg produced no zcode package"
log "packaged $ZCODE_PKG"

# ---------------------------------------------------------------------------
# 8. Package: zcode-desktop (re-packed electron-builder pacman artifact)
# ----------------------------------------------------------------------------
if [ "$BUILD_DESKTOP" = 1 ]; then
    PKGDIR=$WORK/pkg-desktop
    rm -rf "$PKGDIR"
    mkdir -p "$PKGDIR"
    cp "$DESKTOP_ARTIFACT" "$PKGDIR/upstream.pkg.tar.zst"
    # discover the /opt layout + inner binary for the launcher symlink and the
    # chrome-sandbox path for the .install hook
    tar -tf "$PKGDIR/upstream.pkg.tar.zst" > "$PKGDIR/listing.txt"
    OPT_DIR=$(awk -F/ '/^opt\// && !/^opt\/$/ {print $2; exit}' "$PKGDIR/listing.txt")
    [ -n "$OPT_DIR" ] || die "cannot find the opt/ directory in the desktop artifact"
    SANDBOX=$(awk -v d="opt/$OPT_DIR" '$0 ~ "^" d "/.*chrome-sandbox$" {print; exit}' "$PKGDIR/listing.txt")
    [ -n "$SANDBOX" ] || die "cannot find chrome-sandbox in the desktop artifact"
    INNER_BIN=$(awk -v d="opt/$OPT_DIR" '$0 ~ "^" d "/[^/]+$" && $0 ~ /(zcode|ZCode)$/ {print; exit}' "$PKGDIR/listing.txt")
    [ -n "$INNER_BIN" ] || die "cannot find the app binary in the desktop artifact"
    # the artifact's own usr/bin entry (if any) would collide with the CLI's
    # /usr/bin/zcode: drop it, we ship our own zcode-desktop symlink instead
    EXTRA_EXCLUDES=""
    if grep -q '^usr/bin/' "$PKGDIR/listing.txt"; then
        EXTRA_EXCLUDES="--exclude=usr/bin"
        log "dropping the artifact's own usr/bin (collides with the zcode CLI)"
    fi
    sed -e "s/@VERSION@/$VERSION/" -e "s/@PKGREL@/$PKGREL/" \
        -e "s|@INNER_BIN@|$INNER_BIN|" \
        -e "s|@SANDBOX@|$SANDBOX|" -e "s|@EXTRA_EXCLUDES@|$EXTRA_EXCLUDES|" \
        "$DIR/packaging/zcode-desktop/PKGBUILD" > "$PKGDIR/PKGBUILD"
    sed -e "s|@SANDBOX@|$SANDBOX|" \
        "$DIR/packaging/zcode-desktop/zcode-desktop.install" > "$PKGDIR/zcode-desktop.install"
    cd "$PKGDIR"
    makepkg --force --nodeps --noconfirm
    DESKTOP_PKG=$(ls zcode-desktop-"$VERSION"-"$PKGREL"-*.pkg.tar.zst)
    [ -n "$DESKTOP_PKG" ] || die "makepkg produced no zcode-desktop package"
    log "packaged $DESKTOP_PKG"
fi

# ---------------------------------------------------------------------------
# 9. Publish into the local pacman repository. The repo database is only
#    touched after a fully successful build + verify, so a failing nightly
#    keeps pacman -Syu serving the last good packages.
# ---------------------------------------------------------------------------
install -m 644 "$WORK/pkg-zcode/$ZCODE_PKG" "$OUT/$ZCODE_PKG"
if [ "$BUILD_DESKTOP" = 1 ]; then
    install -m 644 "$WORK/pkg-desktop/$DESKTOP_PKG" "$OUT/$DESKTOP_PKG"
fi
repo-add "$OUT/zcode.db.tar.gz" "$OUT"/zcode-*.pkg.tar.zst
# pacman accepts both spellings; serve the canonical short name
rm -f "$OUT/zcode.db"
ln -s zcode.db.tar.gz "$OUT/zcode.db"

# keep only the newest package file per package name (the db above is the
# index; stale files would otherwise accumulate forever). The [0-9] boundary
# keeps "zcode-*" from also matching the zcode-desktop files.
for prefix in "zcode-[0-9]" "zcode-desktop-[0-9]"; do
    ls "$OUT/$prefix"*.pkg.tar.zst 2>/dev/null | sort -V | head -n -1 | while read -r old; do
        rm -f "$old"
        log "pruned old package $old"
    done
done
printf '%s %s %s %s %s %s\n' "$VERSION" "$PKGREL" "$COMMIT" "$(date -u +%FT%TZ)" \
    "$TOOLS_SHA" "$BUILD_DESKTOP" > "$OUT/build-stamp.txt"
chmod 644 "$OUT/build-stamp.txt" "$OUT"/zcode.db* "$OUT"/*.pkg.tar.zst
log "local repository updated: $OUT ($VERSION-$PKGREL, commit $COMMIT)"
