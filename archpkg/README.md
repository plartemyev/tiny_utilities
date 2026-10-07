# archpkg

Arch Linux package list sorter, graphical-stack classifier and install-list
minimizer.

## CLI

```
archpkg PKG [PKG ...]            # deduplicate and sort alphabetically
archpkg --console-only PKG [...]  # separate console-only from graphical
archpkg --minimize PKG [...]      # drop packages pulled in as deps of others
```

## Python API

```python
from archpkg import sort_packages, classify_packages, minimize_packages
from archpkg.pacman import query_packages, query_pkg_info

sorted_list = sort_packages(["foo", "bar", "foo"])
# → ["bar", "foo"]

console, graphical = classify_packages(
    ["htop", "firefox", "yay"],
    query_fn=query_packages,
)
# → (["htop", "yay"], ["firefox"])

minimal, pulled, missing = minimize_packages(
    ["sonic-win", "sonic-terminal", "sonic-login-manager", "sonicde-meta"],
    query_fn=query_pkg_info,
)
# → (["sonicde-meta"], ["sonic-login-manager", "sonic-terminal", "sonic-win"], [])

# query functions can be replaced with any callable; query_packages returns
# {pkg_name: [dep_names]} and query_pkg_info returns
# {pkg_name: PackageInfo(deps, provides)} — neither has to talk to pacman.
```

## Install

```bash
poetry install
```

Optional: install `pyalpm` for faster local dependency lookups instead of
shelling out to `pacman -Si`.

## Test

```bash
poetry run pytest
```

## How classification works

A package is classified as **graphical** if it directly depends on one of the
known X11/Wayland/graphics libraries (e.g. `libx11`, `mesa`, `wayland`,
`qt6-base`, `sdl2`, etc.) or if its own name starts with `vulkan-` (any
Vulkan-related package). Everything else is treated as **console-only**.
The full indicator list is in `archpkg/core.py`.

## How minimization works

`--minimize` consults the sync databases (`pacman -Si`, so the list does not
have to be installed yet) and keeps only the packages nothing else in the list
pulls in transitively; the rest is reported as "pulled as dependencies".
Mutual-dependency cycles keep one representative instead of dropping both
members. Names not found in the sync databases are excluded from the result
and reported as missing, with one exception: a virtual name (e.g. `ttf-font`)
that is already satisfied by a package of the computed set — directly or
transitively — counts as pulled. Alternative dependencies (`a|b`) are
deliberately never inferred as edges (pacman resolves the choice at install
time), so such packages are always kept.
