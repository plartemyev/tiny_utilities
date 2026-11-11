#!/usr/bin/env bash
# Post-build verification gate: proves the built artifacts carry no telemetry
# machinery. Any hit fails the nightly build, so the pacman repo keeps
# serving the last good packages instead of a leaky build.
#
# Usage: verify-stripped.sh <checkout> cli
#        verify-stripped.sh <checkout> desktop <electron-builder-pkg.tar.zst>
#
# Checks mirror the four layers of the strip (see strip-telemetry.sh):
#   - lockfile: the ARMS SDK and the OTLP SDK packages must be gone
#     (@opentelemetry/api is allowed: pure types here, transitive dep of
#     the Vercel AI SDK);
#   - CLI agent bundle + server entry + web dist: no OTLP/ARMS machinery;
#   - desktop app.asar: neither the file manifest nor the extracted content
#     may reference the ARMS SDK, the OTLP exporters, or the ARMS init log
#     line the official builds print ("electron initialized").
set -euo pipefail

SRC=${1:?usage: verify-stripped.sh <checkout> (cli|desktop) [artifact]}
MODE=${2:?usage: verify-stripped.sh <checkout> (cli|desktop) [artifact]}
cd "$SRC"

count() { grep -c "$1" "$2" 2>/dev/null || true; }
assert_zero() { # assert_zero <what> <n>
    if [ "$2" != "0" ]; then
        echo "[verify] FAIL: $1 (found $2)" >&2
        exit 1
    fi
    echo "[verify] ok: $1"
}

if [ "$MODE" = cli ]; then
    # the strip policy, checked where it is decided: our manifests must not
    # carry the removed SDKs (@opentelemetry/api stays: pure types, and a
    # transitive dep of the Vercel AI SDK)
    for manifest in apps/zcode-cli/packages/telemetry/package.json packages/desktop/package.json; do
        n=$(grep -cE '"@arms/|@opentelemetry/(context-async-hooks|exporter-metrics-otlp-proto|exporter-trace-otlp-proto|otlp-exporter-base|resources|sdk-metrics|sdk-trace-base)"' "$manifest" || true)
        assert_zero "$manifest free of the stripped telemetry deps" "$n"
    done
    # lockfile scope: only OUR importer blocks. Transitive OTel copies of
    # unrelated upstream dependencies (e.g. @sentry/node-core's OTel
    # integration) legitimately remain in the packages section — the whole-
    # file grep false-positived on them (observed live: 9 hits, all Sentry).
    LOCK_IMPORTERS=$(awk '
        /^importers:$/ { in_importers = 1; next }
        in_importers && /^[^ ]/ { in_importers = 0 }
        in_importers && /^  (apps\/zcode-cli\/packages\/telemetry|packages\/desktop):$/ { in_block = 1; print; next }
        in_block && /^  [^ ]/ { in_block = 0 }
        in_block { print }
    ' pnpm-lock.yaml)
    [ -n "$LOCK_IMPORTERS" ] || { echo "[verify] FAIL: importer blocks not found in pnpm-lock.yaml (format changed?)" >&2; exit 1; }
    n=$(printf '%s\n' "$LOCK_IMPORTERS" | grep -cE '@arms/|@opentelemetry/(context-async-hooks|exporter-metrics-otlp-proto|exporter-trace-otlp-proto|otlp-exporter-base|resources|sdk-metrics|sdk-trace-base)' || true)
    assert_zero "lockfile importers free of the stripped telemetry deps" "$n"

    AGENT=apps/zcode-cli/packages/cli/dist/zcode.cjs
    [ -f "$AGENT" ] || { echo "[verify] FAIL: missing agent bundle $AGENT" >&2; exit 1; }
    n=$(grep -cE 'otlp-exporter|OTLPTraceExporter|OTLPMetricExporter|@opentelemetry/exporter' "$AGENT" || true)
    assert_zero "agent bundle free of OTLP exporters" "$n"
    # the injected build-time config machinery legitimately mentions
    # ZCODE_ARMS_RUM_ENDPOINT (an empty compiled-out constant); assert the
    # SDK itself is absent instead of the constant name
    n=$(grep -c 'rum-electron' "$AGENT" || true)
    assert_zero "agent bundle free of the ARMS SDK" "$n"

    # the server entry legitimately carries OTEL_EXPORTER_OTLP_* env-var
    # NAMES (values never activate: the resolvers are stubbed to undefined);
    # assert the exporter machinery itself instead
    n=$(grep -cE 'otlp-exporter|OTLPTraceExporter|OTLPMetricExporter|@opentelemetry/exporter|@arms/' packages/server/dist/entry-http.js || true)
    assert_zero "server entry free of telemetry exporter machinery" "$n"
    # scope to served code: THIRD-PARTY-NOTICES.md legitimately (stale-)
    # attributes the removed @arms packages from pre-strip manifests.
    # `|| true` guards the pipeline: grep exits 1 on no match and
    # set -o pipefail would abort the script with no message.
    n=$({ grep -rlEi 'rum-electron|@arms/' packages/web/dist/assets packages/web/dist/index.html 2>/dev/null || true; } | wc -l)
    assert_zero "web dist free of ARMS references" "$n"
    exit 0
fi

if [ "$MODE" = desktop ]; then
    ARTIFACT=${3:?desktop mode needs the artifact path}
    [ -f "$ARTIFACT" ] || { echo "[verify] FAIL: missing artifact $ARTIFACT" >&2; exit 1; }
    TMP=$(mktemp -d "$SRC/../desktop-verify.XXXXXX")
    trap 'rm -rf "$TMP"' EXIT
    tar -xf "$ARTIFACT" -C "$TMP" --wildcards '*/resources/app.asar' \
        || { echo "[verify] FAIL: no app.asar inside $ARTIFACT" >&2; exit 1; }
    ASAR=$(find "$TMP" -name app.asar | head -1)
    ASAR_CLI=$(dirname "$(find node_modules -path '*@electron/asar/package.json' -print -quit 2>/dev/null)")/bin/asar.js
    [ -f "$ASAR_CLI" ] || { echo "[verify] FAIL: @electron/asar not found in node_modules" >&2; exit 1; }

    node "$ASAR_CLI" list "$ASAR" > "$TMP/asar-list.txt"
    # the asar manifest legitimately carries armsRumStub.js (our no-op);
    # assert the SDK module instead of the 'arms' substring
    n=$(grep -ci 'rum-electron' "$TMP/asar-list.txt" || true)
    assert_zero "app.asar manifest free of the ARMS SDK entries" "$n"
    n=$(grep -ci 'otlp-exporter' "$TMP/asar-list.txt" || true)
    assert_zero "app.asar manifest free of OTLP exporter entries" "$n"

    node "$ASAR_CLI" extract "$ASAR" "$TMP/asar"
    n=$({ grep -rl 'rum-electron' "$TMP/asar" 2>/dev/null || true; } | wc -l)
    assert_zero "app.asar content free of the ARMS SDK" "$n"
    n=$({ grep -rl 'otlp-exporter' "$TMP/asar" 2>/dev/null || true; } | wc -l)
    assert_zero "app.asar content free of the OTLP exporter chain" "$n"
    n=$({ grep -rl 'electron initialized' "$TMP/asar" 2>/dev/null || true; } | wc -l)
    assert_zero "app.asar content free of the ARMS init log line" "$n"
    exit 0
fi

echo "[verify] FAIL: unknown mode $MODE" >&2
exit 2
