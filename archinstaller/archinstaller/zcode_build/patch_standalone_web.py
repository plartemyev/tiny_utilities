#!/usr/bin/env python3
"""Standalone-web local-project patch for the zcode-build pipeline.

Upstream defect zai-org/feedback#1161 (open, P2): `zcode --web` (standalone
self-hosted server) cannot create projects or start conversations. The
standalone server owns the local filesystem but assembles its services with
a REMOTE-style ownerHostId (createServerHostServices in
packages/services/src/node.ts), while the web client addresses the machine
it talks to as "local". Three gates then reject the browser:

  1. project/index.ts route(): client hostId "local" != ownerHostId and the
     standalone server has no resolveHost -> project.host-offline (the
     "Create project" folder picker can never list a directory);
  2. project-storage/project-repository.ts saveProject(): the browser saves
     the project with hostId "local" -> project.host-immutable;
  3. the saveProject RESPONSE carries the server's own host id -> the web
     ProjectCreation.saved() treats it as a removed remote host and throws
     remote-project.host-removed (false error right after a successful save).

With the session's project requirement kept as-is (upstream design: server
sessions must belong to a project), fixing these three lets the browser
create a project for a server directory, select it, and send.

The patch is applied to the SOURCE tree before `pnpm build:zcode` (our build
compiles from source, so no hand-editing of built artifacts like the
workaround documented in the upstream issue). It is scoped to services
without resolveHost (the standalone server); desktop remote hosts, which
have resolveHost, keep byte-identical behavior, and the alias goes inert the
moment upstream supplies a resolveHost of its own (their future fix would
replace it). Every edit asserts its anchor and fails the build otherwise:
when upstream fixes or reorganizes this code, the nightly must stop and keep
serving the last good packages instead of double-patching.

Disable with ZCODE_WEB_LOCAL_PROJECTS=0 (see build.sh); the verify gate
checks the patch state either way.
"""

import pathlib
import sys


def die(message: str) -> None:
    print(f"[web-patch] FAIL: {message}", file=sys.stderr)
    sys.exit(1)


MARKER = "zcode-build standalone-web patch"

ROUTE_ANCHOR = """  const route = async (hostId?: string) => {
    if (!hostId || hostId === (options.ownerHostId ?? "local")) return null;
    if (!options.resolveHost) throw new Error("project.host-offline");
    return options.resolveHost(hostId);
  };
"""

ROUTE_REPLACEMENT = """  // MARKER (upstream: zai-org/feedback#1161): the standalone server owns
  // this machine's filesystem but keeps a remote-style ownerHostId, while
  // the web client addresses this very machine as "local". The alias below
  // exposes the server's own service to that name; desktop remote hosts
  // have resolveHost and keep byte-identical behavior, and the alias goes
  // inert the moment upstream provides a resolveHost of its own.
  const isStandaloneServer =
    !options.resolveHost && Boolean(options.ownerHostId && options.ownerHostId !== "local");
  // MARKER: presentation helper — rows leaving the standalone server always
  // carry the browser's name for this machine; storage keeps the real owner.
  const presentProject = (project: VirtualProject): VirtualProject =>
    isStandaloneServer && project.hostId !== "local" ? { ...project, hostId: "local" } : project;
  const route = async (hostId?: string) => {
    if (!hostId || hostId === (options.ownerHostId ?? "local")) return null;
    // MARKER: "local" from the browser means this server; without the alias
    // the folder picker dies with project.host-offline
    // (upstream: zai-org/feedback#1161).
    if (isStandaloneServer && hostId === "local") return null;
    if (!options.resolveHost) throw new Error("project.host-offline");
    return options.resolveHost(hostId);
  };
"""

SAVE_INPUT_ANCHOR = """      input = saveProjectSchema.parse(input);
      if (input.reuseExistingRoot && options.ownerHostId && options.ownerHostId !== "local")
        throw new Error("project.invalid-directory-open");
      const remote = await route(input.hostId);
      if (remote) return remote.saveProject(input);
"""

SAVE_INPUT_REPLACEMENT = SAVE_INPUT_ANCHOR + """      // MARKER: the browser addresses this machine as "local"; project rows
      // are partitioned under the server's own host id, so drop the alias
      // before the repository's host-immutable check
      // (upstream: zai-org/feedback#1161).
      if (isStandaloneServer && input.hostId === "local") {
        input = { ...input, hostId: undefined };
      }
"""

SAVE_RESULT_ANCHOR = """      const result = (await options.repository()).saveProject({
        ...input,
        roots,
        ...(input.primaryRoot ? { primaryRoot: normalize(input.primaryRoot) } : {}),
      });
      await changed();
      return result;
"""

SAVE_RESULT_REPLACEMENT = """      const result = (await options.repository()).saveProject({
        ...input,
        roots,
        ...(input.primaryRoot ? { primaryRoot: normalize(input.primaryRoot) } : {}),
      });
      await changed();
      // MARKER: the stored row carries the server's host id; report it to
      // the browser as "local" (its own name for this machine), or
      // ProjectCreation.saved() mistakes the owner for a removed remote host
      // and throws remote-project.host-removed
      // (upstream: zai-org/feedback#1161).
      return presentProject(result);
"""

READ_PROJECTS_ANCHOR = """    async readProjects(params) {
      const remote = await route(params?.hostId);
      return remote
        ? remote.readProjects({ includeDeleted: params?.includeDeleted })
        : projectPrimaryRootStatuses(
            (await options.repository()).readTree({
              includeDeleted: params?.includeDeleted,
              includeTasks: false,
            }).projects,
          );
    },
"""

READ_PROJECTS_REPLACEMENT = """    async readProjects(params) {
      const remote = await route(params?.hostId);
      return remote
        ? remote.readProjects({ includeDeleted: params?.includeDeleted })
        : projectPrimaryRootStatuses(
            (await options.repository()).readTree({
              includeDeleted: params?.includeDeleted,
              includeTasks: false,
            }).projects,
          ).then((projects) => projects.map(presentProject)); // MARKER: same rule as readTree
    },
"""

READ_TREE_ANCHOR = """      const tree = (await options.repository()).readTree({
        includeDeleted: params?.includeDeleted,
        includeDeletedTasks: params?.includeDeletedTasks,
      });
      return { ...tree, projects: await projectPrimaryRootStatuses(tree.projects) };
"""

READ_TREE_REPLACEMENT = """      const tree = (await options.repository()).readTree({
        includeDeleted: params?.includeDeleted,
        includeDeletedTasks: params?.includeDeletedTasks,
      });
      // MARKER: rows leaving the standalone server are presented with the
      // browser's own name for this machine ("local"); otherwise composer
      // pickers and automation lists filter them out as foreign-host rows
      // (upstream: zai-org/feedback#1161).
      const projects = (await projectPrimaryRootStatuses(tree.projects)).map(presentProject);
      return { ...tree, projects };
"""

RESTORE_ANCHOR = """      const result = repository.saveProject({
        restoreProjectId: id,
        roots: project.roots.map((root) => root.rootPath),
      });
      await changed();
      return result;
    },
"""

RESTORE_REPLACEMENT = """      const result = repository.saveProject({
        restoreProjectId: id,
        roots: project.roots.map((root) => root.rootPath),
      });
      await changed();
      // MARKER: same presentation rule as saveProject above
      // (upstream: zai-org/feedback#1161).
      return presentProject(result);
    },
"""


def replace_once(text: str, relative: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        die(f"{what} anchor not unique in {relative}: found {count} (upstream changed?)")
    # the replacements carry a literal MARKER placeholder so the anchor and
    # replacement strings stay readable; expand it before splicing
    return text.replace(anchor, replacement.replace("MARKER", MARKER), 1)


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_standalone_web.py <zcode-checkout>")
    root = pathlib.Path(sys.argv[1])
    if not root.is_dir():
        die(f"not a checkout directory: {root}")
    relative = "packages/services/src/project/index.ts"
    path = root / relative
    if not path.is_file():
        die(f"expected {relative} missing in the checkout")
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        die(f"{relative} is already patched (marker present)")

    text = replace_once(text, relative, ROUTE_ANCHOR, ROUTE_REPLACEMENT, "route()")
    text = replace_once(text, relative, SAVE_INPUT_ANCHOR, SAVE_INPUT_REPLACEMENT,
                        "saveProject input")
    text = replace_once(text, relative, SAVE_RESULT_ANCHOR, SAVE_RESULT_REPLACEMENT,
                        "saveProject result")
    text = replace_once(text, relative, READ_PROJECTS_ANCHOR, READ_PROJECTS_REPLACEMENT,
                        "readProjects")
    text = replace_once(text, relative, READ_TREE_ANCHOR, READ_TREE_REPLACEMENT, "readTree")
    text = replace_once(text, relative, RESTORE_ANCHOR, RESTORE_REPLACEMENT, "restoreProject")

    # sanity: the upstream gates stay in place (the patch only routes around
    # them for the browser's "local" alias, it does not delete the policy).
    # project.host-immutable lives in project-repository.ts, which this patch
    # never touches — the input normalization makes the check pass naturally.
    for gate in ('"project.host-offline"', '"project.remote-project-required"'):
        if gate not in text:
            die(f"upstream gate {gate} vanished from {relative}")

    path.write_text(text, encoding="utf-8")
    print(f"[web-patch] patched {relative} "
          f"(standalone local-project alias: route, saveProject in/out, "
          f"readProjects/readTree/restoreProject presentation)")


if __name__ == "__main__":
    main()
