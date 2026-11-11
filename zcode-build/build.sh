#!/usr/bin/env bash
# In-container build orchestrator. Invoked by nightly.sh (host cron) as:
#   docker run --rm -u <uid>:<gid> -v ./cache:/cache -v ./repo:/repo \
#       [-e ZCODE_REF=<git-ref>] zcode-builder /build.sh
# Produces/updates the pacman repo at /repo: zcode.db{,.sig},
# zcode-<ver>...pkg.tar.zst, zcode-desktop-...pkg.tar.zst, zcode-repo.asc,
# healthz.
#
# Layout: /cache is the persistent volume (upstream git mirror, pinned Node
# runtime, pnpm store, electron cache, GPG home); /repo is the served pacman
# repository; /work is container-local scratch.
set -euo pipefail

REPO=/repo
CACHE=/cache
WORK=/work
SRC=$WORK/src
REF="${ZCODE_REF:-origin/main}"
ELECTRON_MIRROR="${ZCODE_ELECTRON_MIRROR:-}"   # default: upstream's npmmirror

log() { echo "[build] $(date -u +%H:%M:%S) $*"; }
die() { echo "[build] FAIL: $*" >&2; exit 1; }

mkdir -p "$CACHE" "$WORK" "$REPO" "$CACHE/home"
export HOME=$CACHE/home
export GNUPGHOME=$CACHE/gnupg

# ---------------------------------------------------------------------------
# Telemetry build-env hygiene: these are compile-time capability injections
# (scripts/build-time-config.mjs). Explicitly empty = the capability is
# compiled out; public checkouts have no config/private/ defaults anyway.
# ---------------------------------------------------------------------------
export ZCODE_ARMS_RUM_ENDPOINT=""
export ZCODE_TELEMETRY_REPORT_ENDPOINT=""
export ZCODE_AUTO_UPDATE=""
export COREPACK_ENABLE_PROJECT_SPEC=0
export ZCODE_DIST_BASE_URL="http://127.0.0.1:8283/"  # unused: we consume the tarball directly
[ -n "$ELECTRON_MIRROR" ] && export ELECTRON_MIRROR

# ---------------------------------------------------------------------------
# 1. Fresh checkout of upstream main via the persistent bare mirror
# ---------------------------------------------------------------------------
MIRROR=$CACHE/upstream.git
if [ ! -d "$MIRROR" ]; then
    git clone --bare https://github.com/zai-org/ZCode.git "$MIRROR"
fi
for attempt in 1 2 3; do
    if git -C "$MIRROR" fetch --prune origin; then break; fi
    [ "$attempt" = 3 ] && die "git fetch of upstream failed 3 times"
    sleep $((attempt * 20))
done
rm -rf "$SRC"
git clone --quiet "$MIRROR" "$SRC"
git -C "$SRC" checkout --quiet --detach "$REF"
COMMIT=$(git -C "$SRC" rev-parse --short=12 HEAD)
# a pristine tree: our edits must not survive a failed/retried run
log "checkout $REF @ $COMMIT"

# hygiene: the private build-defaults file and any stray env files would
# re-enable telemetry at build time
[ ! -e "$SRC/config/private" ] || die "config/private exists in a public checkout?!"
[ ! -e "$SRC/.env" ] || die ".env exists in the checkout"
[ ! -e "$SRC/.env.local" ] || die ".env.local exists in the checkout"

# ---------------------------------------------------------------------------
# 2. Apply our customizations (telemetry strip)
# ---------------------------------------------------------------------------
/build-files/strip-telemetry.sh "$SRC"

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
pnpm install --no-frozen-lockfile --store-dir "$CACHE/pnpm-store"
pnpm build:zcode
VERSION=$(node -p "require('./package.json').version")
TARBALL=$SRC/dist/zcode/releases/$VERSION/zcode-$VERSION.tar.gz
[ -f "$TARBALL" ] || die "build:zcode produced no tarball"
log "zcode dist $VERSION built"

/build-files/verify-stripped.sh "$SRC" cli

# ---------------------------------------------------------------------------
# 5. Build the desktop package (electron-builder, pacman target)
# ---------------------------------------------------------------------------
pnpm bundle:desktop -- --os linux --arch x64
DESKTOP_ARTIFACT=$(ls "$SRC"/packages/desktop/dist/*linux*x64*.pkg.tar.zst 2>/dev/null | head -1)
[ -n "$DESKTOP_ARTIFACT" ] || die "desktop bundle produced no pacman artifact"
log "desktop artifact: $(basename "$DESKTOP_ARTIFACT")"

/build-files/verify-stripped.sh "$SRC" desktop "$DESKTOP_ARTIFACT"

# ---------------------------------------------------------------------------
# 6. Version policy: pkgrel 1 for a new upstream version, date-based for
#    same-version rebuilds (pacman must see the package as newer)
# ---------------------------------------------------------------------------
if ls "$REPO"/zcode-"$VERSION"-*.pkg.tar.zst >/dev/null 2>&1; then
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
install -m 755 /build-files/packaging/zcode-wrapper "$PKGDIR/src/usr/bin/zcode"
tar -C "$PKGDIR/src" -cf "$PKGDIR/zcode-tree.tar" opt usr

sed -e "s/@VERSION@/$VERSION/" -e "s/@PKGREL@/$PKGREL/" \
    /build-files/packaging/zcode/PKGBUILD > "$PKGDIR/PKGBUILD"
cd "$PKGDIR"
makepkg --force --nodeps --noconfirm
ZCODE_PKG=$(ls zcode-"$VERSION"-"$PKGREL"-*.pkg.tar.zst)
[ -n "$ZCODE_PKG" ] || die "makepkg produced no zcode package"
log "packaged $ZCODE_PKG"

# ---------------------------------------------------------------------------
# 8. Package: zcode-desktop (re-packed electron-builder pacman artifact)
# ----------------------------------------------------------------------------
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
    -e "s|@OPT_DIR@|$OPT_DIR|" -e "s|@INNER_BIN@|$INNER_BIN|" \
    -e "s|@SANDBOX@|$SANDBOX|" -e "s|@EXTRA_EXCLUDES@/$EXTRA_EXCLUDES/" \
    /build-files/packaging/zcode-desktop/PKGBUILD > "$PKGDIR/PKGBUILD"
cp /build-files/packaging/zcode-desktop/zcode-desktop.install "$PKGDIR/"
cd "$PKGDIR"
makepkg --force --nodeps --noconfirm
DESKTOP_PKG=$(ls zcode-desktop-"$VERSION"-"$PKGREL"-*.pkg.tar.zst)
[ -n "$DESKTOP_PKG" ] || die "makepkg produced no zcode-desktop package"
log "packaged $DESKTOP_PKG"

# ---------------------------------------------------------------------------
# 9. Update the pacman repo (signed)
# ---------------------------------------------------------------------------
if [ ! -f "$GNUPGHOME/pubring.kbx" ] && [ ! -f "$GNUPGHOME/secring.gpg" ]; then
    mkdir -p "$GNUPGHOME"
    chmod 700 "$GNUPGHOME"
    gpg --batch --passphrase '' --quick-generate-key \
        "zcode-build local repository <zcode-build@localhost>" default default never
    log "generated the repository signing key"
fi
chmod 700 "$GNUPGHOME"
gpg --batch --yes --export --armor > "$REPO/zcode-repo.asc"
KEY=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr/ {print $10; exit}')
[ -n "$KEY" ] || die "cannot resolve the signing key"

install -m 644 "$WORK/pkg-zcode/$ZCODE_PKG" "$REPO/$ZCODE_PKG"
install -m 644 "$WORK/pkg-desktop/$DESKTOP_PKG" "$REPO/$DESKTOP_PKG"
repo-add --sign --key "$KEY" "$REPO/zcode.db.tar.gz" \
    "$REPO/$ZCODE_PKG" "$REPO/$DESKTOP_PKG"
# pacman accepts both spellings; serve the canonical short name
rm -f "$REPO/zcode.db" "$REPO/zcode.db.sig"
ln -s zcode.db.tar.gz "$REPO/zcode.db"
[ -f "$REPO/zcode.db.tar.gz.sig" ] && ln -sf zcode.db.tar.gz.sig "$REPO/zcode.db.sig"
chmod 644 "$REPO"/zcode.db* "$REPO"/*.pkg.tar.zst "$REPO"/zcode-repo.asc 2>/dev/null || true

# keep only the newest package file per package name (the db above is the
# index; stale files would otherwise accumulate forever). The [0-9] boundary
# keeps "zcode-*" from also matching the zcode-desktop files.
for prefix in "zcode-[0-9]" "zcode-desktop-[0-9]"; do
    ls "$REPO/$prefix"*.pkg.tar.zst 2>/dev/null | sort -V | head -n -1 | while read -r old; do
        rm -f "$old" "$old.sig"
        log "pruned old package $old"
    done
done
printf 'ok\n' > "$REPO/healthz"
printf '%s %s %s %s\n' "$VERSION" "$PKGREL" "$COMMIT" "$(date -u +%FT%TZ)" > "$REPO/build-stamp.txt"
chmod 644 "$REPO/healthz" "$REPO/build-stamp.txt"
log "repository updated: $REPO ($VERSION-$PKGREL, commit $COMMIT)"
