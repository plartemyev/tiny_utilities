#!/usr/bin/env bash
# Strips the telemetry surface out of a fresh zai-org/ZCode checkout.
#
# Policy (reviewed against the Zcode-CE community fork's telemetry.md, then
# re-derived from the upstream sources ourselves — no CE code is used):
#
#   1. ARMS RUM (desktop): the @arms/rum-electron SDK dependency is removed
#      entirely and every import is redirected to a local no-op stub. The
#      business "report*ToArms" feeder modules stay but funnel into the stub,
#      so they are inert; deleting them too (like CE does) would mean editing
#      dozens of call sites in desktop main and is not worth the nightly churn.
#   2. OTLP chain (agent CLI + desktop main): apps/zcode-cli/packages/telemetry
#      loses its exporters (otlp-exporter.ts) and activation logic
#      (resolveOtlp*Endpoint / createPreparedOwner stubbed to dead), and the
#      OTel SDK dependencies are dropped from the manifests. The desktop-side
#      localTtftExporter / rendererActionTraceExporter (TTFT metrics over OTLP)
#      are stubbed to no-ops, and the electron-builder runtime-module injection
#      + verification lists lose their OTel entries accordingly.
#   3. Event reporting (packages/services telemetryCore) and ARMS activation
#      are compile-time gated on endpoints injected from build env vars
#      (ZCODE_ARMS_RUM_ENDPOINT / ZCODE_TELEMETRY_REPORT_ENDPOINT) which are
#      empty for public-repo builds (config/private/ is internal-only).
#      build.sh enforces they stay empty and verify-stripped.sh proves no
#      endpoint leaked into any artifact.
#
# What is deliberately KEPT (matching CE's findings): deviceMid
# (billing header X-Device-Mid), local crash archive (already
# uploadToServer: false upstream), local memory diagnostics, the
# envelope.ttft protocol field, @opentelemetry/api (pure types, and a
# transitive dep of the Vercel AI SDK).
#
# Every edit asserts its anchor first and fails the build otherwise: when
# upstream moves this code, the nightly build must stop and keep serving the
# last good packages, never silently ship telemetry back in.
#
# Division of labor: this script owns the no-op stub files, the import
# redirects and the file removals; strip_telemetry.py owns every manifest
# and source-text edit.
set -euo pipefail

SRC="${1:?usage: strip-telemetry.sh <zcode-checkout>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$SRC"

log() { echo "[strip] $*"; }
die() { echo "[strip] FAIL: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. ARMS RUM SDK removal (desktop): no-op stub + import redirect
# ---------------------------------------------------------------------------
STUB="packages/desktop/src/armsRumStub.ts"
cat > "$STUB" <<'EOF'
/**
 * Telemetry strip: local no-op replacement for the @arms/rum-electron SDK.
 * Injected by zcode-build/strip-telemetry.sh; see that script for policy.
 * The members mirror everything the desktop tree calls on the SDK's default
 * export (init/sendCustom/sendEvent/setConfig/getConfig/client.useReporter).
 */
export interface ArmsRumClient {
  useReporter(reporter: unknown): void;
}

const client: ArmsRumClient = {
  useReporter(_reporter: unknown): void {},
};

const armsRum = {
  client,
  getConfig(): Record<string, unknown> {
    return { env: "local" };
  },
  init(_config: unknown): Promise<void> {
    return Promise.resolve();
  },
  sendCustom(_name: string, ..._rest: unknown[]): void {},
  sendEvent(_name: string, ..._rest: unknown[]): void {},
  setConfig(_key: string, _value: unknown): void {},
};

export default armsRum;
EOF
log "wrote $STUB"

main_importers=$(grep -rl 'from "@arms/rum-electron"' packages/desktop/src || true)
browser_importers=$(grep -rl 'from "@arms/rum-electron/browser"' packages/desktop/src || true)
[ -n "$main_importers" ] || die "no @arms/rum-electron importers found under packages/desktop/src (upstream changed?)"
sed -i 's|from "@arms/rum-electron/browser"|from "../armsRumStub.js"|' \
    $(grep -rl 'from "@arms/rum-electron/browser"' packages/desktop/src)
sed -i 's|from "@arms/rum-electron"|from "../armsRumStub.js"|' \
    $(grep -rl 'from "@arms/rum-electron"' packages/desktop/src)
# test-only mock: keep the tree consistent even though our build runs no tests
sed -i 's|from "@arms/rum-electron/browser"|from "../../src/armsRumStub.js"|' \
    packages/desktop/test/mocks/armsRumElectronStub.ts 2>/dev/null || true
sed -i 's|from "@arms/rum-electron"|from "../../src/armsRumStub.js"|' \
    packages/desktop/test/mocks/armsRumElectronStub.ts 2>/dev/null || true
if grep -rn 'from "@arms/rum-electron' packages/desktop/src; then
    die "residual @arms/rum-electron imports in packages/desktop/src"
fi
log "redirected ARMS imports ($(echo "$main_importers" | wc -l) main + $(echo "$browser_importers" | wc -l) browser)"

# ---------------------------------------------------------------------------
# 2. Every manifest/source-text edit (ARMS manifests, OTLP bootstrap
#    neutralization, OTel dependency drops, bundle/electron-builder lists)
# ---------------------------------------------------------------------------
python3 "$HERE/strip_telemetry.py" "$SRC"

# removals the python side asserts around: the patch file must exist right
# after its patchedDependencies entry was dropped, the exporter right after
# its only importer was neutralized
patch_file="patches/@arms__rum-electron@0.0.3.patch"
[ -f "$patch_file" ] || die "expected patch file $patch_file missing"
rm "$patch_file"
log "removed $patch_file"

OTLP_EXPORTER="apps/zcode-cli/packages/telemetry/src/otlp-exporter.ts"
[ -f "$OTLP_EXPORTER" ] || die "expected $OTLP_EXPORTER missing"
rm "$OTLP_EXPORTER"
log "removed $OTLP_EXPORTER"

# ---------------------------------------------------------------------------
# 3. Desktop main: local TTFT exporter stub
# ---------------------------------------------------------------------------
cat > packages/desktop/src/main/localTtftExporter.ts <<'EOF'
// Telemetry strip: the local TTFT OTLP metric exporter was removed; the
// enqueue/shutdown shape is kept for the desktop main call sites.
// Injected by zcode-build/strip-telemetry.sh; see that script for policy.
export interface LocalTtftExporterOptions {
  env: Record<string, string | undefined>;
  version: string;
  logger: { warn(...args: unknown[]): void };
}

export interface LocalTtftExporter {
  enqueue(batch: unknown): void;
  shutdown(): Promise<void>;
}

export function createLocalTtftExporter(
  _options: LocalTtftExporterOptions,
): LocalTtftExporter {
  return {
    enqueue(_batch: unknown): void {},
    async shutdown(): Promise<void> {},
  };
}
EOF
log "stubbed localTtftExporter.ts"

# ---------------------------------------------------------------------------
# 4. Sanity: no executable references left in the shipped trees
# ---------------------------------------------------------------------------
if grep -rn 'otlp-exporter' apps/zcode-cli/packages/telemetry/src; then
    die "residual otlp-exporter references in telemetry src"
fi
log "strip complete"
