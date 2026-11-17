#!/usr/bin/env python3
"""Web insecure-context patch for the zcode-build pipeline.

`zcode --web` serves the browser UI from a plain-HTTP LAN origin, which
Chromium classifies as an INSECURE context: `crypto.randomUUID` (a
secure-context-only API) is undefined there. The v4 command factory calls
it while building every createSession envelope:

    packages/ui/src/v4/commandFactory.ts
        sessionId: ... ?? `sess_${crypto.randomUUID()}`

so each browser draft-session dispatch dies client-side with
`TypeError: crypto.randomUUID is not a function` BEFORE any RPC leaves the
page — no sendConversationCommandV4 reaches the server (journal silent),
the runtime child never sees the frame, and the composer reports
草稿会话创建失败 / "Failed to send". The desktop renders in a secure
context and is unaffected; CLI/TUI don't run this UI code.

Fix: use the already-imported, context-independent `uuidv7()` (the shared
package's own portable generators exist for exactly this class of problem;
see `createUuid` in packages/shared/src/uuid.ts). Live-verified 2026-11-18
(v3.18.2, target code-factory-m): the patched console output pinned the
throw to the factory, with zero outgoing command frames.

Scope: only the send-blocking site. The other raw crypto.randomUUID call
sites (voice input, image preview, archive, plugin-ui, ttft clock) fail in
their own features, not on the send path; each is individually visible if
it ever matters.

The edit asserts its anchors and fails the build otherwise — when upstream
switches to a portable generator (or moves the code) the nightly stops and
keeps serving the last good packages. Disable with
ZCODE_WEB_SECURE_CONTEXT=0 (see build.sh); the verify gate checks the
patch state either way.
"""

import pathlib
import sys


def die(message: str) -> None:
    print(f"[web-ctx-patch] FAIL: {message}", file=sys.stderr)
    sys.exit(1)


MARKER = "zcode-build web-secure-context patch"

RELATIVE = "packages/ui/src/v4/commandFactory.ts"

ANCHOR = """          sessionId:
            (input.payload as CommandPayloadMap["createSession"]).sessionId ??
            `sess_${crypto.randomUUID()}`,
"""

REPLACEMENT = """          sessionId:
            (input.payload as CommandPayloadMap["createSession"]).sessionId ??
            // MARKER: crypto.randomUUID is undefined in insecure contexts
            // (plain-HTTP LAN origins), which killed every browser
            // createSession before any RPC; uuidv7 is already imported and
            // context-independent.
            `sess_${uuidv7()}`,
"""

# the replacement relies on this import staying in place
IMPORT_ANCHOR = 'import { uuidv7 } from "@zcode/shared";'


def main() -> None:
    if len(sys.argv) != 2:
        die(f"usage: {sys.argv[0]} <zcode-checkout>")
    root = pathlib.Path(sys.argv[1])
    if not root.is_dir():
        die(f"not a checkout directory: {root}")
    path = root / RELATIVE
    if not path.is_file():
        die(f"expected {RELATIVE} missing in the checkout")
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        die(f"{RELATIVE} is already patched (marker present)")

    count = text.count(ANCHOR)
    if count != 1:
        die(f"createSession sessionId anchor not unique in {RELATIVE}: found {count} "
            f"(upstream changed?)")
    if text.count(IMPORT_ANCHOR) < 1:
        die(f"uuidv7 import anchor missing from {RELATIVE} (upstream changed?)")
    text = text.replace(ANCHOR, REPLACEMENT.replace("MARKER", MARKER), 1)

    # the factory must not depend on secure-context crypto anywhere else
    # (match the call form, not the name — the patch comment mentions it)
    leftover = text.count("crypto.randomUUID(")
    if leftover != 0:
        die(f"{RELATIVE} still calls crypto.randomUUID {leftover}x after the patch")

    path.write_text(text, encoding="utf-8")
    print(f"[web-ctx-patch] patched {RELATIVE} "
          f"(createSession sessionId via uuidv7, insecure-context safe)")


if __name__ == "__main__":
    main()
