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
set -euo pipefail

SRC="${1:?usage: strip-telemetry.sh <zcode-checkout>}"
cd "$SRC"

log() { echo "[strip] $*"; }
die() { echo "[strip] FAIL: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. ARMS RUM SDK removal (desktop)
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

python3 - <<'PYEOF'
import json, pathlib, sys

def edit(path, fn):
    p = pathlib.Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def drop_dep(name):
    def fn(data):
        deps = data.get("dependencies", {})
        if name not in deps:
            sys.exit(f"[strip] FAIL: {name} not in dependencies (upstream changed?)")
        del deps[name]
    return fn

edit("packages/desktop/package.json", drop_dep("@arms/rum-electron"))

def drop_patch(data):
    patches = data.get("pnpm", {}).get("patchedDependencies", {})
    key = "@arms/rum-electron@0.0.3"
    if key not in patches:
        sys.exit(f"[strip] FAIL: {key} not in root patchedDependencies (upstream changed?)")
    del patches[key]

edit("package.json", drop_patch)
print("[strip] removed @arms/rum-electron from package manifests")
PYEOF
patch_file="patches/@arms__rum-electron@0.0.3.patch"
[ -f "$patch_file" ] || die "expected patch file $patch_file missing"
rm "$patch_file"
log "removed $patch_file"

# ---------------------------------------------------------------------------
# 2. OTLP chain: agent CLI telemetry package
# ---------------------------------------------------------------------------
TB="apps/zcode-cli/packages/telemetry/src/bootstrap.ts"
python3 - "$TB" <<'PYEOF'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
note = "  return undefined; // telemetry strip: OTLP activation removed"

def early_return(signature):
    global text
    if signature not in text:
        sys.exit(f"[strip] FAIL: anchor not found in {path}: {signature!r}")
    if text.count(signature) != 1:
        sys.exit(f"[strip] FAIL: anchor not unique in {path}: {signature!r}")
    text = text.replace(signature, signature + "\n" + note, 1)

early_return("export function resolveOtlpTraceEndpoint(env: EnvRecord): string | undefined {")
early_return("export function resolveOtlpMetricEndpoint(env: EnvRecord): string | undefined {")

# Replace the whole createPreparedOwner body: it dynamically imports the
# (deleted) otlp-exporter module, so it must go entirely.
start_anchor = "async function createPreparedOwner("
end_anchor = "function resolveTelemetryIdentity("
if start_anchor not in text or end_anchor not in text:
    sys.exit(f"[strip] FAIL: createPreparedOwner anchors not found in {path}")
if text.index(end_anchor) < text.index(start_anchor):
    sys.exit(f"[strip] FAIL: createPreparedOwner anchor order unexpected in {path}")
start = text.index(start_anchor)
end = text.index(end_anchor)
replacement = (
    "async function createPreparedOwner(\n"
    "  _env: EnvRecord,\n"
    "  _options: PrepareModelTelemetryOptions,\n"
    "): Promise<AgentTelemetryRuntimeOwner | undefined> {\n"
    "  // Telemetry strip: the OTLP exporter chain was removed; this owner can\n"
    "  // never activate. See zcode-build/strip-telemetry.sh.\n"
    "  return undefined;\n"
    "}\n\n"
)
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding="utf-8")
print(f"[strip] neutralized {path.name}")
PYEOF

OTLP_EXPORTER="apps/zcode-cli/packages/telemetry/src/otlp-exporter.ts"
[ -f "$OTLP_EXPORTER" ] || die "expected $OTLP_EXPORTER missing"
rm "$OTLP_EXPORTER"
log "removed $OTLP_EXPORTER"

python3 - <<'PYEOF'
import json, pathlib, sys

path = pathlib.Path("apps/zcode-cli/packages/telemetry/package.json")
data = json.loads(path.read_text(encoding="utf-8"))
deps = data["dependencies"]
# @opentelemetry/api stays: pure types here and a transitive dep of the
# Vercel AI SDK ("ai" package).
remove = [
    "@opentelemetry/context-async-hooks",
    "@opentelemetry/exporter-metrics-otlp-proto",
    "@opentelemetry/exporter-trace-otlp-proto",
    "@opentelemetry/otlp-exporter-base",
    "@opentelemetry/resources",
    "@opentelemetry/sdk-metrics",
    "@opentelemetry/sdk-trace-base",
]
missing = [name for name in remove if name not in deps]
if missing:
    sys.exit(f"[strip] FAIL: telemetry deps not found (upstream changed?): {missing}")
for name in remove:
    del deps[name]
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("[strip] removed OTel SDK deps from the telemetry package")
PYEOF

# ---------------------------------------------------------------------------
# 3. OTLP chain: desktop main exporters (local TTFT / renderer action traces)
# ---------------------------------------------------------------------------
python3 - <<'PYEOF'
import pathlib, sys

# rendererActionTraceExporter.ts: keep the pure URL/header utilities intact
# (protocol-side helpers), remove only the OTLP exporter wiring.
path = pathlib.Path("packages/desktop/src/main/rendererActionTraceExporter.ts")
text = path.read_text(encoding="utf-8")
imports = (
    'import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";\n'
    'import type { SpanExporter } from "@opentelemetry/sdk-trace-base";\n\n'
)
if text.count(imports) != 1:
    sys.exit("[strip] FAIL: OTel imports not found in rendererActionTraceExporter.ts")
text = text.replace(imports, "", 1)
start = text.index("export function createRendererActionTraceExporter")
next_export = text.index("export function validHttpUrl")
if next_export <= start:
    sys.exit("[strip] FAIL: exporter/util order changed in rendererActionTraceExporter.ts")
replacement = (
    "// Telemetry strip: the OTLP trace exporter was removed; see\n"
    "// zcode-build/strip-telemetry.sh.\n"
    "export function createRendererActionTraceExporter(\n"
    "  _env: EnvRecord,\n"
    "): undefined {\n"
    "  return undefined;\n"
    "}\n\n"
)
text = text[:start] + replacement + text[next_export:]
path.write_text(text, encoding="utf-8")
print("[strip] neutralized rendererActionTraceExporter.ts")
PYEOF

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

python3 - <<'PYEOF'
import json, pathlib, sys

path = pathlib.Path("packages/desktop/package.json")
data = json.loads(path.read_text(encoding="utf-8"))
deps = data["dependencies"]
remove = [
    "@opentelemetry/exporter-metrics-otlp-proto",
    "@opentelemetry/exporter-trace-otlp-proto",
    "@opentelemetry/resources",
    "@opentelemetry/sdk-metrics",
    "@opentelemetry/sdk-trace-base",
]
missing = [name for name in remove if name not in deps]
if missing:
    sys.exit(f"[strip] FAIL: desktop OTel deps not found (upstream changed?): {missing}")
for name in remove:
    del deps[name]
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("[strip] removed OTel SDK deps from the desktop package")
PYEOF

# The bundler machinery injects and mechanically verifies the OTel runtime
# modules inside app.asar; with the exporters gone the entries must go too,
# or the bundle step fails on missing modules.
python3 - <<'PYEOF'
import pathlib, sys

for path, anchors in {
    "packages/desktop/scripts/bundle.mjs": [
        '  "@opentelemetry/sdk-metrics",\n',
        '  "@opentelemetry/exporter-trace-otlp-proto",\n',
        '  "@opentelemetry/exporter-metrics-otlp-proto",\n',
    ],
    "packages/desktop/electron-builder.config.js": [
        '  "@opentelemetry/sdk-metrics",\n',
        '  "@opentelemetry/exporter-trace-otlp-proto",\n',
        '  "@opentelemetry/exporter-metrics-otlp-proto",\n',
    ],
}.items():
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8")
    for anchor in anchors:
        count = text.count(anchor)
        if count != 1:
            sys.exit(f"[strip] FAIL: expected exactly one {anchor!r} in {path}, found {count}")
        text = text.replace(anchor, "")
    p.write_text(text, encoding="utf-8")
    print(f"[strip] removed OTel entries from {path}")
PYEOF

# ---------------------------------------------------------------------------
# 4. Sanity: no executable references left in the shipped trees
# ---------------------------------------------------------------------------
if grep -rn 'otlp-exporter' apps/zcode-cli/packages/telemetry/src; then
    die "residual otlp-exporter references in telemetry src"
fi
log "strip complete"
