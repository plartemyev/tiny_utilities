"""Smoke test for the zcode_build telemetry strip scripts.

Builds a synthetic checkout containing exactly the anchors the strip
asserts on (upstream-shaped snippets), runs strip-telemetry.sh against it
and verifies every layer of the policy: import redirect, manifest
surgery, source neutralization, stubs, file removals.
"""
import json
import subprocess
from pathlib import Path

import pytest

BUILD_DIR = Path(__file__).resolve().parent.parent / "archinstaller" / "zcode_build"
STRIP = BUILD_DIR / "strip-telemetry.sh"


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_checkout(root: Path) -> None:
    write(root, "packages/desktop/src/main/index.ts", (
        'import armsRum from "@arms/rum-electron";\n'
        'import armsRumBrowser from "@arms/rum-electron/browser";\n'
        "export function boot(): void {\n"
        "  armsRum.init({});\n"
        '  armsRumBrowser.sendEvent("x");\n'
        "}\n"
    ))
    write(root, "packages/desktop/test/mocks/armsRumElectronStub.ts", (
        'import armsRum from "@arms/rum-electron";\n'
        "export default armsRum;\n"
    ))
    write(root, "package.json", json.dumps({
        "name": "zcode-root",
        "pnpm": {"patchedDependencies": {
            "@arms/rum-electron@0.0.3": "patches/@arms__rum-electron@0.0.3.patch",
        }},
    }))
    write(root, "packages/desktop/package.json", json.dumps({
        "name": "desktop",
        "dependencies": {
            "@arms/rum-electron": "0.0.3",
            "@opentelemetry/exporter-metrics-otlp-proto": "^0.200.0",
            "@opentelemetry/exporter-trace-otlp-proto": "^0.200.0",
            "@opentelemetry/resources": "^1.0.0",
            "@opentelemetry/sdk-metrics": "^1.0.0",
            "@opentelemetry/sdk-trace-base": "^1.0.0",
            "electron": "33.0.0",
        },
    }))
    write(root, "apps/zcode-cli/packages/telemetry/package.json", json.dumps({
        "name": "telemetry",
        "dependencies": {
            "@opentelemetry/api": "^1.0.0",       # stays: pure types
            "@opentelemetry/context-async-hooks": "^0.200.0",
            "@opentelemetry/exporter-metrics-otlp-proto": "^0.200.0",
            "@opentelemetry/exporter-trace-otlp-proto": "^0.200.0",
            "@opentelemetry/otlp-exporter-base": "^0.200.0",
            "@opentelemetry/resources": "^1.0.0",
            "@opentelemetry/sdk-metrics": "^1.0.0",
            "@opentelemetry/sdk-trace-base": "^1.0.0",
            "ai": "^4.0.0",                        # stays: vercel AI sdk
        },
    }))
    write(root, "patches/@arms__rum-electron@0.0.3.patch", "fake patch\n")
    write(root, "apps/zcode-cli/packages/telemetry/src/bootstrap.ts", (
        "export function resolveOtlpTraceEndpoint(env: EnvRecord): string | undefined {\n"
        "  return env.OTLP_URL;\n"
        "}\n"
        "\n"
        "export function resolveOtlpMetricEndpoint(env: EnvRecord): string | undefined {\n"
        "  return env.OTLP_METRIC_URL;\n"
        "}\n"
        "\n"
        "async function createPreparedOwner(\n"
        "  env: EnvRecord,\n"
        "  options: PrepareModelTelemetryOptions,\n"
        "): Promise<AgentTelemetryRuntimeOwner> {\n"
        '  const exporter = await import("./otlp-exporter.js");\n'
        "  return { exporter, env, options };\n"
        "}\n"
        "\n"
        "function resolveTelemetryIdentity(env: EnvRecord): string {\n"
        '  return env.DEVICE_MID ?? "anonymous";\n'
        "}\n"
    ))
    write(root, "apps/zcode-cli/packages/telemetry/src/otlp-exporter.ts",
          "export const gone = 1;\n")
    write(root, "packages/desktop/src/main/rendererActionTraceExporter.ts", (
        'import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";\n'
        'import type { SpanExporter } from "@opentelemetry/sdk-trace-base";\n'
        "\n"
        "export function createRendererActionTraceExporter(env: EnvRecord): SpanExporter {\n"
        "  return new OTLPTraceExporter({ url: env.OTLP_URL });\n"
        "}\n"
        "\n"
        "export function validHttpUrl(url: string | undefined): boolean {\n"
        '  return !!url && url.startsWith("https://");\n'
        "}\n"
    ))
    write(root, "packages/desktop/src/main/localTtftExporter.ts", "stale stub\n")
    bundle = (
        "const runtimeModules = [\n"
        '  "@opentelemetry/sdk-metrics",\n'
        '  "@opentelemetry/exporter-trace-otlp-proto",\n'
        '  "@opentelemetry/exporter-metrics-otlp-proto",\n'
        '  "electron",\n'
        "];\n"
        "export { runtimeModules };\n"
    )
    write(root, "packages/desktop/scripts/bundle.mjs", bundle)
    write(root, "packages/desktop/electron-builder.config.js", bundle)


def run_strip(checkout: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(STRIP), str(checkout)],
                          capture_output=True, text=True, timeout=120)


def test_strip_applies_every_layer(tmp_path):
    checkout = tmp_path / "src"
    fixture_checkout(checkout)
    result = run_strip(checkout)
    assert result.returncode == 0, result.stderr

    index = (checkout / "packages/desktop/src/main/index.ts").read_text()
    assert 'from "../armsRumStub.js"' in index
    residual = subprocess.run(
        ["grep", "-rl", 'from "@arms/rum-electron', str(checkout / "packages/desktop/src")],
        capture_output=True, text=True).stdout
    assert residual == ""
    stub = (checkout / "packages/desktop/src/armsRumStub.ts").read_text()
    assert "export default armsRum" in stub

    assert not (checkout / "patches/@arms__rum-electron@0.0.3.patch").exists()
    root_manifest = json.loads((checkout / "package.json").read_text())
    assert root_manifest["pnpm"]["patchedDependencies"] == {}

    desktop_deps = json.loads(
        (checkout / "packages/desktop/package.json").read_text())["dependencies"]
    assert "@arms/rum-electron" not in desktop_deps
    assert "@opentelemetry/sdk-metrics" not in desktop_deps
    assert desktop_deps["electron"] == "33.0.0"

    telemetry_deps = json.loads(
        (checkout / "apps/zcode-cli/packages/telemetry/package.json"
         ).read_text())["dependencies"]
    assert "@opentelemetry/otlp-exporter-base" not in telemetry_deps
    assert "@opentelemetry/api" in telemetry_deps   # deliberately kept
    assert "ai" in telemetry_deps                   # deliberately kept

    bootstrap = (checkout / "apps/zcode-cli/packages/telemetry/src/bootstrap.ts").read_text()
    assert bootstrap.count("return undefined; // telemetry strip") == 2
    assert "never activate" in bootstrap            # createPreparedOwner replaced
    assert not (checkout / "apps/zcode-cli/packages/telemetry/src/otlp-exporter.ts").exists()

    exporter = (checkout / "packages/desktop/src/main/rendererActionTraceExporter.ts").read_text()
    assert "OTLPTraceExporter" not in exporter
    assert "validHttpUrl" in exporter               # utilities survive
    ttft = (checkout / "packages/desktop/src/main/localTtftExporter.ts").read_text()
    assert "createLocalTtftExporter" in ttft

    for relative in ("packages/desktop/scripts/bundle.mjs",
                     "packages/desktop/electron-builder.config.js"):
        assert "sdk-metrics" not in (checkout / relative).read_text()
        assert '"electron"' in (checkout / relative).read_text()


def test_strip_fails_visibly_on_drifted_upstream(tmp_path):
    checkout = tmp_path / "src"
    fixture_checkout(checkout)
    # simulate upstream drift: rename the patch entry the strip asserts on
    manifest = json.loads((checkout / "package.json").read_text())
    del manifest["pnpm"]["patchedDependencies"]["@arms/rum-electron@0.0.3"]
    (checkout / "package.json").write_text(json.dumps(manifest))
    result = run_strip(checkout)
    assert result.returncode != 0
    assert "FAIL" in result.stderr
    assert "patchedDependencies" in result.stderr


def test_payload_carries_the_strip_scripts():
    import base64
    import io
    import tarfile

    from archinstaller.steps import zcode_build_payload
    payload = zcode_build_payload()
    assert len(payload) > 1000
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload)), mode="r:gz") as tar:
        names = tar.getnames()
        modes = {m.name: m.mode for m in tar.getmembers()}
    for name in ("build.sh", "strip-telemetry.sh", "strip_telemetry.py",
                 "verify-stripped.sh", "packaging/zcode/PKGBUILD",
                 "packaging/zcode-wrapper",
                 "packaging/zcode-desktop/PKGBUILD",
                 "packaging/zcode-desktop/zcode-desktop.install"):
        assert name in names, name
    assert modes["build.sh"] == 0o755
    assert modes["strip-telemetry.sh"] == 0o755
    assert modes["strip_telemetry.py"] == 0o644
    assert "README.md" not in names          # repo docs stay out of the payload
    assert not any(n.startswith("tmp/") for n in names)  # dev tests too
    assert "packaging/zcode/PKGBUILD" in modes


def test_zcode_update_units_bake_the_desktop_flag():
    from archinstaller.steps import zcode_update_units
    service, timer = zcode_update_units(desktop=True)
    assert "Environment=ZCODE_DESKTOP=1" in service
    assert "build.sh" in service
    assert "OnCalendar=*-*-* 03:17:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer

    console_service, _ = zcode_update_units(desktop=False)
    assert "ZCODE_DESKTOP" not in console_service


def test_build_script_syntax():
    for name in ("build.sh", "strip-telemetry.sh", "verify-stripped.sh"):
        result = subprocess.run(["bash", "-n", str(BUILD_DIR / name)],
                                capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_git_and_early_exit_mechanics():
    """The persistent-shallow-checkout + up-to-date-exit regression tests
    (synthetic upstream, never touches the real repository)."""
    for script in ("git-mechanics.sh", "build-early-exit.sh"):
        result = subprocess.run(["bash", str(BUILD_DIR / "tmp" / script)],
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, f"{script}: {result.stdout}\n{result.stderr}"
