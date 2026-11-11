#!/usr/bin/env python3
"""Manifest and source edits of the zcode-build telemetry strip.

Every edit asserts its anchor and fails (exit 1) otherwise: when upstream
moves this code, the nightly build must stop and keep serving the last good
packages, never silently ship telemetry back in.

The shell parts of the strip (no-op stub files, import redirects, file
removals, residual-import sanity checks) stay in strip-telemetry.sh, which
calls this script once; see that script for the full policy write-up.
"""

import json
import pathlib
import sys


def die(message: str) -> None:
    print(f"[strip] FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def read_text(root: pathlib.Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        die(f"expected {relative} missing in the checkout")
    return path.read_text(encoding="utf-8")


def write_text(root: pathlib.Path, relative: str, text: str) -> None:
    (root / relative).write_text(text, encoding="utf-8")


def edit_json(root: pathlib.Path, relative: str, fn) -> None:
    """Load a manifest, apply fn(data) in place, write it back canonical."""
    path = root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def drop_dependencies(names: list[str]):
    """edit_json callback: remove names from data["dependencies"]."""
    def fn(data):
        deps = data.get("dependencies", {})
        missing = [name for name in names if name not in deps]
        if missing:
            die(f"deps not found in dependencies (upstream changed?): {missing}")
        for name in names:
            del deps[name]
    return fn


# ---------------------------------------------------------------------------
# 1. ARMS RUM SDK removal (desktop): manifest surgery
# ---------------------------------------------------------------------------

def strip_arms_manifests(root: pathlib.Path) -> None:
    edit_json(root, "packages/desktop/package.json",
              drop_dependencies(["@arms/rum-electron"]))

    def drop_patch(data):
        patches = data.get("pnpm", {}).get("patchedDependencies", {})
        key = "@arms/rum-electron@0.0.3"
        if key not in patches:
            die(f"{key} not in root patchedDependencies (upstream changed?)")
        del patches[key]

    edit_json(root, "package.json", drop_patch)
    print("[strip] removed @arms/rum-electron from package manifests")


# ---------------------------------------------------------------------------
# 2. OTLP chain: agent CLI telemetry bootstrap
# ---------------------------------------------------------------------------

def strip_bootstrap(root: pathlib.Path) -> None:
    relative = "apps/zcode-cli/packages/telemetry/src/bootstrap.ts"
    text = read_text(root, relative)
    note = "  return undefined; // telemetry strip: OTLP activation removed"

    # Replace the WHOLE function body, not just prepend a return: TypeScript
    # does not apply control-flow narrowing inside unreachable code, so a
    # kept body after the early return fails tsc on its narrowing-sensitive
    # lines (observed live: resolveOtlp*Endpoint callers pass `string | undefined`).
    def neutralize(signature):
        nonlocal text
        if text.count(signature) != 1:
            die(f"anchor not unique in {relative}: {signature!r}")
        end = text.find("\n}\n", text.index(signature))
        if end < 0:
            die(f"closing brace not found for {signature!r} in {relative}")
        end += len("\n}\n")
        text = (text[:text.index(signature)] + signature + "\n" + note
                + "\n}\n" + text[end:])

    neutralize("export function resolveOtlpTraceEndpoint(env: EnvRecord): string | undefined {")
    neutralize("export function resolveOtlpMetricEndpoint(env: EnvRecord): string | undefined {")

    # Replace the whole createPreparedOwner body: it dynamically imports the
    # (deleted) otlp-exporter module, so it must go entirely.
    start_anchor = "async function createPreparedOwner("
    end_anchor = "function resolveTelemetryIdentity("
    if start_anchor not in text or end_anchor not in text:
        die(f"createPreparedOwner anchors not found in {relative}")
    if text.index(end_anchor) < text.index(start_anchor):
        die(f"createPreparedOwner anchor order unexpected in {relative}")
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
    write_text(root, relative, text)
    print(f"[strip] neutralized {pathlib.Path(relative).name}")


OTLP_SDK_DEPS = [
    "@opentelemetry/context-async-hooks",
    "@opentelemetry/exporter-metrics-otlp-proto",
    "@opentelemetry/exporter-trace-otlp-proto",
    "@opentelemetry/otlp-exporter-base",
    "@opentelemetry/resources",
    "@opentelemetry/sdk-metrics",
    "@opentelemetry/sdk-trace-base",
]

DESKTOP_OTEL_DEPS = [
    "@opentelemetry/exporter-metrics-otlp-proto",
    "@opentelemetry/exporter-trace-otlp-proto",
    "@opentelemetry/resources",
    "@opentelemetry/sdk-metrics",
    "@opentelemetry/sdk-trace-base",
]


def strip_telemetry_deps(root: pathlib.Path) -> None:
    # @opentelemetry/api stays: pure types here and a transitive dep of the
    # Vercel AI SDK ("ai" package).
    edit_json(root, "apps/zcode-cli/packages/telemetry/package.json",
              drop_dependencies(OTLP_SDK_DEPS))
    print("[strip] removed OTel SDK deps from the telemetry package")


# ---------------------------------------------------------------------------
# 3. OTLP chain: desktop main exporters
# ---------------------------------------------------------------------------

def strip_renderer_exporter(root: pathlib.Path) -> None:
    # rendererActionTraceExporter.ts: keep the pure URL/header utilities intact
    # (protocol-side helpers), remove only the OTLP exporter wiring.
    relative = "packages/desktop/src/main/rendererActionTraceExporter.ts"
    text = read_text(root, relative)
    imports = (
        'import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";\n'
        'import type { SpanExporter } from "@opentelemetry/sdk-trace-base";\n\n'
    )
    if text.count(imports) != 1:
        die("OTel imports not found in rendererActionTraceExporter.ts")
    text = text.replace(imports, "", 1)
    start = text.index("export function createRendererActionTraceExporter")
    next_export = text.index("export function validHttpUrl")
    if next_export <= start:
        die("exporter/util order changed in rendererActionTraceExporter.ts")
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
    write_text(root, relative, text)
    print("[strip] neutralized rendererActionTraceExporter.ts")


def strip_desktop_arms_bootstrap(root: pathlib.Path) -> None:
    # appARMSBootstrap.ts stays in the tree (its feeders are inert through
    # the stub), but the init-success log line must not ship: official
    # builds print "[arms] electron initialized" and the verify gate greps
    # the shipped asar for exactly that line.
    relative = "packages/desktop/src/main/appARMSBootstrap.ts"
    text = read_text(root, relative)
    log_line = ("    logger.info(`[arms] electron initialized"
                " env=${armsRumEnv} version=${ZCODE_VERSION}`);")
    if text.count(log_line) != 1:
        die(f"ARMS init log line not found (or not unique) in {relative}")
    text = text.replace(
        log_line,
        "    // Telemetry strip: the ARMS init-success log line was removed;\n"
        "    // see zcode-build/strip-telemetry.sh. The stubbed init() sends\n"
        "    // nothing, so that line must not ship either.",
        1,
    )
    write_text(root, relative, text)
    print(f"[strip] removed the ARMS init log line from {relative}")


def strip_desktop_deps(root: pathlib.Path) -> None:
    edit_json(root, "packages/desktop/package.json",
              drop_dependencies(DESKTOP_OTEL_DEPS))
    print("[strip] removed OTel SDK deps from the desktop package")


def strip_bundle_lists(root: pathlib.Path) -> None:
    # The bundler machinery injects and mechanically verifies the OTel runtime
    # modules inside app.asar; with the exporters gone the entries must go
    # too, or the bundle step fails on missing modules.
    targets = {
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
    }
    for relative, anchors in targets.items():
        text = read_text(root, relative)
        for anchor in anchors:
            count = text.count(anchor)
            if count != 1:
                die(f"expected exactly one {anchor!r} in {relative}, found {count}")
            text = text.replace(anchor, "")
        write_text(root, relative, text)
        print(f"[strip] removed OTel entries from {relative}")


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: strip_telemetry.py <zcode-checkout>")
    root = pathlib.Path(sys.argv[1])
    if not root.is_dir():
        die(f"not a checkout directory: {root}")
    strip_arms_manifests(root)
    strip_bootstrap(root)
    strip_telemetry_deps(root)
    strip_renderer_exporter(root)
    strip_desktop_arms_bootstrap(root)
    strip_desktop_deps(root)
    strip_bundle_lists(root)


if __name__ == "__main__":
    main()
