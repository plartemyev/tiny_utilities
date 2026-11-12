#!/usr/bin/env bash
# On-target build orchestrator: checks out the latest tagged release of
# zai-org/ZCode (ZCODE_REF pins an explicit ref), strips
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
# Layout: out/ (or /var/cache/zcode-build/out on archinstaller targets) is
# the published pacman repository (packages + zcode.db);
# cache/ is the persistent state (upstream shallow checkout, pinned Node,
# pnpm store, electron cache, gem home); tmp/ is per-run scratch, wiped upfront.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE="${ZCODE_CACHE:-$DIR/cache}"
WORK="${ZCODE_WORK:-$DIR/tmp}"
OUT="${ZCODE_OUT:-$DIR/out}"
# on archinstaller targets the published repo lives outside the (0700) home:
# pacman's download sandbox fetches file:// repositories as the unprivileged
# 'alpm' user, which cannot read the home directory
if [ -z "${ZCODE_OUT:-}" ] && [ -d /var/cache/zcode-build/out ] \
    && [ -w /var/cache/zcode-build/out ]; then
    OUT=/var/cache/zcode-build/out
fi
REF="${ZCODE_REF:-}"   # empty: the latest upstream version tag
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
# Telemetry build-env hygiene: the ENDPOINT/AUTO_UPDATE variables are
# compile-time capability injections (scripts/build-time-config.mjs) —
# explicitly empty means the capability is compiled out; public checkouts
# have no config/private/ defaults anyway. ZCODE_DIST_BASE_URL is different:
# build:zcode REQUIRES it to be set (its default lives in the internal-only
# config/private/), so it gets a dummy URL — with auto-update compiled out
# nothing ever fetches from it.
# ---------------------------------------------------------------------------
export ZCODE_ARMS_RUM_ENDPOINT=""
export ZCODE_TELEMETRY_REPORT_ENDPOINT=""
export ZCODE_AUTO_UPDATE=""
export COREPACK_ENABLE_PROJECT_SPEC=0
export ZCODE_DIST_BASE_URL="http://127.0.0.1:8283/"
[ -n "$ELECTRON_MIRROR" ] && export ELECTRON_MIRROR

# ---------------------------------------------------------------------------
# 1. Persistent shallow checkout of upstream (cache/src), pinned to the
#    latest tagged release by default (ZCODE_REF pins any explicit ref; the
#    nightly therefore only ever ships tagged releases, never main). A
#    fetch + forced detach + clean keeps the tree byte-identical to the ref
#    while --depth 1 keeps the transfer small. ZCODE_SHALLOW=0 drops the
#    depth for exotic refs (old commit SHAs).
# ---------------------------------------------------------------------------
SRC=$CACHE/src
DEPTH="--depth 1"
[ "${ZCODE_SHALLOW:-1}" = 1 ] || DEPTH=""
if [ ! -d "$SRC/.git" ]; then
    git clone $DEPTH "$UPSTREAM_URL" "$SRC"
fi
for attempt in 1 2 3; do
    if git -C "$SRC" fetch $DEPTH --prune --prune-tags --tags origin; then break; fi
    [ "$attempt" = 3 ] && die "git fetch of upstream failed 3 times"
    sleep $((attempt * 20))
done
if [ -n "$REF" ]; then
    git -C "$SRC" fetch $DEPTH --prune origin "$REF"
    REF_AT=FETCH_HEAD
    REF_LABEL=$REF
else
    # latest version tag, version-sorted ("v3.18.0" > "v3.9.0"); pruned
    # upstream tags disappear here too, so re-releases re-trigger builds
    REF_LABEL=$(git -C "$SRC" tag --sort=-v:refname \
        | grep -E "^v?[0-9]+([.][0-9]+){1,3}([-+.].*)?$" | head -1)
    [ -n "$REF_LABEL" ] || die "no upstream version tag found (set ZCODE_REF to pin an explicit ref)"
    REF_AT="refs/tags/$REF_LABEL"
fi
git -C "$SRC" checkout --force --detach "$REF_AT"
git -C "$SRC" clean -fdxq
COMMIT=$(git -C "$SRC" rev-parse --short=12 HEAD)
log "checkout $REF_LABEL @ $COMMIT"

# ---------------------------------------------------------------------------
# 1b. Skip the build entirely when the resolved release, our scripts and
#     the desktop flag are all unchanged since the last successful build:
#     the nightly then costs one fetch and exits ("already have the latest
#     tag"). ZCODE_FORCE=1 overrides (e.g. after wiping the cache).
# ---------------------------------------------------------------------------
TOOLS_SHA=$(cat "$DIR/build.sh" "$DIR/strip-telemetry.sh" "$DIR/strip_telemetry.py" \
    "$DIR/verify-stripped.sh" "$DIR/packaging/zcode/PKGBUILD" "$DIR/packaging/zcode-wrapper" \
    "$DIR/packaging/zcode-desktop/PKGBUILD" \
    "$DIR/packaging/zcode-desktop/zcode-desktop.install" | sha256sum | cut -d' ' -f1)
if [ -z "${ZCODE_FORCE:-}" ] && [ -f "$OUT/build-stamp.txt" ]; then
    read -r _ _ STAMP_COMMIT _ STAMP_TOOLS STAMP_DESKTOP STAMP_REF < "$OUT/build-stamp.txt" || true
    if [ "$COMMIT" = "${STAMP_COMMIT:-}" ] && [ "$TOOLS_SHA" = "${STAMP_TOOLS:-}" ] \
        && [ "$BUILD_DESKTOP" = "${STAMP_DESKTOP:-}" ] \
        && [ "$REF_LABEL" = "${STAMP_REF:-}" ]; then
        log "up to date ($REF_LABEL @ $COMMIT); nothing to build (ZCODE_FORCE=1 overrides)"
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
# tooling (appimage tools, rpmbuild) and download artifacts for targets we
# never ship. The config's linux target list is the single mechanism:
# electron-builder (current version) rejects target names as positional
# arguments ("Unknown argument: pacman"), so no bundle.mjs arg hack.
BUNDLE_MJS=$SRC/packages/desktop/scripts/bundle.mjs
CONFIG_JS=$SRC/packages/desktop/electron-builder.config.js
config_anchor='target: ["AppImage", "deb", "rpm", "pacman"],'
grep -qF "$config_anchor" "$CONFIG_JS" || die "electron-builder linux target anchor missing"
sed -i 's|target: \["AppImage", "deb", "rpm", "pacman"\],|target: ["pacman"],|' "$CONFIG_JS"
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
# Build the workspace. Newer upstream has build:sea:prepare (it also
# type-builds @zcode/shared, which carries no plain build script); older
# tags only have `pnpm -r build` — desktop is excluded there (its own
# production bundle runs later via bundle:desktop) and shared needs the
# explicit project-references type-build.
if node -e "process.exit(require('./package.json').scripts['build:sea:prepare'] ? 0 : 1)"; then
    pnpm build:sea:prepare
else
    pnpm -r --filter=!@zcode/desktop build
    if [ -d packages/shared ]; then
        pnpm exec tsc -b packages/shared --force
    fi
fi
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
    # the app binary: a top-level file under opt/<dir>/ whose name carries
    # "zcode" (upstream variants differ: ".../zcode", ".../ZCode",
    # ".../zcode-preview")
    INNER_BIN=$(awk -v d="opt/$OPT_DIR" '
        index($0, d "/") == 1 {
            rest = substr($0, length(d) + 2)
            if (index(rest, "/") == 0 && tolower(rest) ~ /zcode/) { print; exit }
        }' "$PKGDIR/listing.txt")
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
# keep only the newest package file per package name BEFORE the db update,
# so the database exactly matches the surviving files. The globs must stay
# UNQUOTED (a quoted "zcode-[0-9]" is a literal string and matches nothing —
# the prune silently collected every old release forever); `|| true`
# neutralizes the no-match exit under pipefail.
for prefix in zcode-[0-9] zcode-desktop-[0-9]; do
    { ls "$OUT"/$prefix*.pkg.tar.zst 2>/dev/null || true; } | sort -V | head -n -1 \
        | while read -r old; do
            rm -f "$old"
            log "pruned old package $old"
        done
done
repo-add "$OUT/zcode.db.tar.gz" "$OUT"/zcode-*.pkg.tar.zst
# pacman accepts both spellings; serve the canonical short name
rm -f "$OUT/zcode.db"
ln -s zcode.db.tar.gz "$OUT/zcode.db"

printf '%s %s %s %s %s %s %s\n' "$VERSION" "$PKGREL" "$COMMIT" "$(date -u +%FT%TZ)" \
    "$TOOLS_SHA" "$BUILD_DESKTOP" "$REF_LABEL" > "$OUT/build-stamp.txt"
chmod 644 "$OUT/build-stamp.txt" "$OUT"/zcode.db* "$OUT"/*.pkg.tar.zst
log "local repository updated: $OUT ($VERSION-$PKGREL, commit $COMMIT)"
