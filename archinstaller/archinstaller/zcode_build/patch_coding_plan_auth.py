#!/usr/bin/env python3
"""Coding-plan auth fallback patch for the zcode-build pipeline.

Upstream gap (verified live against api.z.ai on 2026-11-17/18, target
code-factory-m): turns fail on the standalone CLI (`zcode -p`) and the
`--web` server's spawned runtime with
`project_token_login_failed`, while the DESKTOP on the same box, same
data directory, same stored credentials, works.

Root cause: zaiProviderAdapter.ts persists the /api/auth/z/login BUSINESS
platform JWT as `oauth:zai:access_token` ("让 oauth:zai:access_token
持久化的就是业务 token，后续不再做兜底二次交换" — the store contract is
business token, no later re-exchange). The standalone runtime's
coding-plan-api-key resolver nevertheless re-exchanges that stored token at
/api/auth/z/login — which only accepts raw Z.AI OAuth tokens — and treats
the rejection as fatal:

  POST /api/auth/z/login {token: <business JWT>} -> 200 {code:500,
  "Z.ai user information is invalid"}

while the SAME token is accepted by the business APIs it is meant for:

  GET /api/biz/customer/getCustomerInfo (Authorization: <business JWT>)
  -> 200 {code:200, organizations: [...]}

This patch makes the exchange failure non-fatal: the resolver falls through
to `loginToken = business?.token ?? oauth` (the line directly below already
supports it), so the stored business token is used as the platform token —
exactly what the desktop path effectively does. When the stored value IS a
raw OAuth token, the exchange still runs and refreshes as before; when the
stored token is expired, client.resolve's own 401 handling reports the
login state as before. No desktop/web behavior changes; when upstream fixes
or reorganizes this code the anchor assert stops the build.

Applied to the SOURCE tree before `pnpm build:zcode`; same policy as
patch_standalone_web.py (assert-driven, fails the build on anchor drift).
"""

import pathlib
import sys


def die(message: str) -> None:
    print(f"[auth-patch] FAIL: {message}", file=sys.stderr)
    sys.exit(1)


MARKER = "zcode-build coding-plan-auth patch"

ANCHOR = """              .catch(() => {
                options.observe?.({
                  family: input.family,
                  stage: "resolve",
                  code: "project_token_login_failed",
                });
                throw new CodingPlanApiKeyError("project_token_login_failed");
              })
"""

REPLACEMENT = """              .catch(() => {
                // MARKER (upstream gap): the credential store persists the
                // /api/auth/z/login BUSINESS token (zaiProviderAdapter
                // normalizes at login; that endpoint rejects business
                // tokens on re-exchange with "Z.ai user information is
                // invalid" while /api/biz/* accepts the same token). The
                // stored value is already the platform JWT the business
                // APIs take, so fall through with loginToken = oauth
                // instead of failing the whole resolution
                // (verified live 2026-11-18; see zcode-build/README.md).
                options.observe?.({
                  family: input.family,
                  stage: "resolve",
                  code: "project_token_business_token_reuse",
                });
                return undefined;
              })
"""


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_coding_plan_auth.py <zcode-checkout>")
    root = pathlib.Path(sys.argv[1])
    if not root.is_dir():
        die(f"not a checkout directory: {root}")
    relative = "apps/zcode-cli/packages/adapters/src/auth/coding-plan-api-key.ts"
    path = root / relative
    if not path.is_file():
        die(f"expected {relative} missing in the checkout")
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        die(f"{relative} is already patched (marker present)")

    count = text.count(ANCHOR)
    if count != 1:
        die(f"exchange catch-block anchor not unique in {relative}: found {count} (upstream changed?)")
    # the replacement carries a literal MARKER placeholder so the anchor and
    # replacement strings stay readable; expand it before splicing
    text = text.replace(ANCHOR, REPLACEMENT.replace("MARKER", MARKER), 1)

    # sanity: the loginToken fallback line must still be present right after
    if "const loginToken = business?.token ?? oauth;" not in text:
        die("loginToken fallback line missing (upstream changed?)")

    path.write_text(text, encoding="utf-8")
    print(f"[auth-patch] patched {relative} (business-token reuse fallback)")


if __name__ == "__main__":
    main()
