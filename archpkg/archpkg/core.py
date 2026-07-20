from __future__ import annotations

from collections.abc import Callable

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
    "vulkan-icd-loader",
    "vulkan-intel",
    "vulkan-radeon",
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
        if pkg in _GRAPHICAL_INDICATORS:
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


def _dep_tree_has_graphical(root: str, deps_map: dict[str, list[str]]) -> bool:
    seen: set[str] = {root}
    stack: list[str] = list(deps_map.get(root, []))
    while stack:
        dep = stack.pop()
        if dep in _GRAPHICAL_INDICATORS:
            return True
        if dep not in seen:
            seen.add(dep)
            stack.extend(deps_map.get(dep, []))
    return False


def _has_graphical_dep(deps: list[str]) -> bool:
    return any(dep in _GRAPHICAL_INDICATORS for dep in deps)
