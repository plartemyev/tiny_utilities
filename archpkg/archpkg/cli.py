from __future__ import annotations

import argparse

from archpkg.core import sort_packages, classify_packages
from archpkg.pacman import query_packages


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="archpkg",
        description="Sort and classify Arch Linux packages.",
    )
    parser.add_argument(
        "packages",
        nargs="+",
        metavar="PKG",
        help="package names to sort",
    )
    parser.add_argument(
        "--console-only",
        action="store_true",
        help="separate console-only packages from those requiring X11/Wayland",
    )

    args = parser.parse_args(argv)

    dropped = len(args.packages) - len(set(args.packages))

    if args.console_only:
        console, graphical, missing = classify_packages(
            args.packages, query_fn=query_packages,
        )
        print()
        _print_group("Console-only packages", console)
        print()
        _print_group("Graphical packages", graphical)
        print()
        _print_group("Missing packages", missing)
    else:
        sorted_pkgs = sort_packages(args.packages)
        print()
        print("===SORTED PACKAGES:===")
        print(" ".join(sorted_pkgs))
        print()
        _print_group("Missing packages", _find_missing(sorted_pkgs))

    if dropped:
        plural = "s" if dropped > 1 else ""
        print(f"\n{dropped} duplicate{plural} removed.")


def _print_group(heading: str, packages: list[str]) -> None:
    if packages:
        print(f"{heading}:")
        print(" ".join(packages))
    else:
        print(f"{heading}: (none)")


def _find_missing(packages: list[str]) -> list[str]:
    found = set(query_packages(packages))
    return [p for p in packages if p not in found]
