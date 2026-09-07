# archpkg

Arch Linux package list sorter and graphical-stack classifier.

## CLI

```
archpkg PKG [PKG ...]            # deduplicate and sort alphabetically
archpkg --console-only PKG [...]  # separate console-only from graphical
```

## Python API

```python
from archpkg import sort_packages, classify_packages
from archpkg.pacman import query_packages

sorted_list = sort_packages(["foo", "bar", "foo"])
# → ["bar", "foo"]

console, graphical = classify_packages(
    ["htop", "firefox", "yay"],
    query_fn=query_packages,
)
# → (["htop", "yay"], ["firefox"])

# query_packages can be replaced with any callable that returns
# {pkg_name: [dep_names]} — the function does not have to talk to pacman.
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
