from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple


class PackageInfo(NamedTuple):
    deps: list[str]
    provides: list[str]


_VERSION_PATTERN = re.compile(r"[<>=!].*$")


def _strip_version(dep: str) -> str:
    return _VERSION_PATTERN.sub("", dep).strip()


def _parse_dep(dep: str) -> list[str]:
    return [_strip_version(alt) for alt in dep.split("|")]


_GRAPHICAL_INDICATORS: frozenset[str] = frozenset({
    "egl-gbm",
    "egl-wayland",
    "fltk",
    "fontconfig",
    "gtk2",
    "gtk3",
    "gtk4",
    "libdecor",
    "libgl",
    "libglvnd",
    "libva",
    "libvdpau",
    "libwayland-client",
    "libwayland-cursor",
    "libwayland-egl",
    "libwayland-server",
    "libx11",
    "libxau",
    "libxaw",
    "libxcb",
    "libxcomposite",
    "libxcursor",
    "libxdamage",
    "libxdmcp",
    "libxext",
    "libxfixes",
    "libxfont2",
    "libxft",
    "libxi",
    "libxinerama",
    "libxkbfile",
    "libxmu",
    "libxpm",
    "libxpresent",
    "libxrandr",
    "libxrender",
    "libxres",
    "libxshmfence",
    "libxss",
    "libxt",
    "libxtst",
    "libxv",
    "libxvmc",
    "libxxf86vm",
    "mesa",
    "qt5-base",
    "qt6-base",
    "sdl12-compat",
    "sdl2",
    "sdl3",
    "ttf-font",
    "wayland",
    "wayland-protocols",
    "wxwidgets-common",
    "wxwidgets-gtk3",
    "xcb-proto",
    "xorg-server",
    "xorg-xwayland",
    "xorgproto",
    "xwayland",
})


_VULKAN_PREFIX = "vulkan-"


def _is_graphical_indicator(name: str) -> bool:
    return name in _GRAPHICAL_INDICATORS or name.startswith(_VULKAN_PREFIX)


def sort_packages(packages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for pkg in packages:
        if pkg not in seen:
            seen.add(pkg)
            result.append(pkg)
    result.sort(key=str.lower)
    return result


def classify_packages(
    packages: list[str],
    *,
    query_fn: Callable[[list[str]], dict[str, list[str]]],
) -> tuple[list[str], list[str], list[str]]:
    unique = sort_packages(packages)
    if not unique:
        return [], [], []

    deps_map = dict(query_fn(unique))
    found = set(deps_map)
    queried: set[str] = set(unique)

    graphical: list[str] = []
    missing: list[str] = []
    pending: list[str] = []
    for pkg in unique:
        if _is_graphical_indicator(pkg):
            graphical.append(pkg)
        elif pkg not in found:
            missing.append(pkg)
        elif _has_graphical_dep(deps_map.get(pkg, [])):
            graphical.append(pkg)
        else:
            pending.append(pkg)

    if not pending:
        return sort_packages([]), sort_packages(graphical), sort_packages(missing)

    for _depth in range(10):
        frontier: set[str] = set()
        for pkg in pending:
            for dep in deps_map.get(pkg, []):
                if dep not in queried:
                    frontier.add(dep)

        if not frontier:
            break

        queried.update(frontier)
        deps_map.update(query_fn(list(frontier)))

        still_pending: list[str] = []
        for pkg in pending:
            if _dep_tree_has_graphical(pkg, deps_map):
                graphical.append(pkg)
            else:
                still_pending.append(pkg)
        pending = still_pending

        if not pending:
            break

    return sort_packages(pending), sort_packages(graphical), sort_packages(missing)


def minimize_packages(
    packages: list[str],
    *,
    query_fn: Callable[[list[str]], dict[str, PackageInfo]],
) -> tuple[list[str], list[str], list[str]]:
    unique = sort_packages(packages)
    if not unique:
        return [], [], []

    info: dict[str, PackageInfo] = dict(query_fn(unique))
    found = [p for p in unique if p in info]
    virtual = [p for p in unique if p not in info]

    _discover(info, found, query_fn)
    graph = _dependency_graph(info)
    minimal = _source_representatives(graph, preferred=set(found))
    reachable = _reachable(minimal, graph)
    providers = _providers_index(info)

    kept = set(minimal)
    dropped = [p for p in found if p not in kept]
    missing: list[str] = []
    for name in virtual:
        if providers.get(name, set()) & reachable:
            dropped.append(name)
        else:
            missing.append(name)

    return sort_packages(minimal), sort_packages(dropped), sort_packages(missing)


def _dep_tree_has_graphical(root: str, deps_map: dict[str, list[str]]) -> bool:
    seen: set[str] = {root}
    stack: list[str] = list(deps_map.get(root, []))
    while stack:
        dep = stack.pop()
        if _is_graphical_indicator(dep):
            return True
        if dep not in seen:
            seen.add(dep)
            stack.extend(deps_map.get(dep, []))
    return False


def _has_graphical_dep(deps: list[str]) -> bool:
    return any(_is_graphical_indicator(dep) for dep in deps)


def _single_dep_names(deps: list[str]) -> list[str]:
    # Deps with alternatives ("a|b") are resolved by pacman at install
    # time, so they must not be inferred as deterministic edges.
    names: list[str] = []
    for dep in deps:
        alts = _parse_dep(dep)
        if len(alts) == 1:
            names.append(alts[0])
    return names


def _discover(
    info: dict[str, PackageInfo],
    roots: list[str],
    query_fn: Callable[[list[str]], dict[str, PackageInfo]],
) -> None:
    seen: set[str] = set(roots)
    frontier: list[str] = [p for p in roots if p in info]
    while frontier:
        wanted: set[str] = set()
        for pkg in frontier:
            wanted.update(_single_dep_names(info[pkg].deps))
        new_names = sorted(wanted - seen)
        seen.update(wanted)
        if not new_names:
            break
        info.update(query_fn(new_names))
        frontier = [n for n in new_names if n in info]


def _dependency_graph(info: dict[str, PackageInfo]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for name, pkg_info in info.items():
        targets = {
            dep for dep in _single_dep_names(pkg_info.deps)
            if dep in info and dep != name
        }
        graph[name] = sorted(targets)
    return graph


def _strongly_connected_components(
    graph: dict[str, list[str]],
) -> list[list[str]]:
    index_of: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    for root in graph:
        if root in index_of:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, edge_i = work.pop()
            if edge_i == 0:
                index_of[node] = counter
                lowlink[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            descended = False
            edges = graph[node]
            while edge_i < len(edges):
                target = edges[edge_i]
                edge_i += 1
                if target not in index_of:
                    work.append((node, edge_i))
                    work.append((target, 0))
                    descended = True
                    break
                if target in on_stack:
                    lowlink[node] = min(lowlink[node], index_of[target])
            if descended:
                continue
            if lowlink[node] == index_of[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])

    return components


def _source_representatives(
    graph: dict[str, list[str]], preferred: set[str],
) -> list[str]:
    components = _strongly_connected_components(graph)
    comp_of = {node: i for i, comp in enumerate(components) for node in comp}
    has_incoming = [False] * len(components)
    for name, targets in graph.items():
        for target in targets:
            if comp_of[target] != comp_of[name]:
                has_incoming[comp_of[target]] = True

    roots: list[str] = []
    for i, comp in enumerate(components):
        if not has_incoming[i]:
            roots.append(min(comp, key=lambda n: (n not in preferred, n.lower())))
    return roots


def _reachable(roots: list[str], graph: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))
    return seen


def _providers_index(info: dict[str, PackageInfo]) -> dict[str, set[str]]:
    providers: dict[str, set[str]] = {}
    for name, pkg_info in info.items():
        for provide in pkg_info.provides:
            alts = _parse_dep(provide)
            if len(alts) == 1:
                providers.setdefault(alts[0], set()).add(name)
    return providers
