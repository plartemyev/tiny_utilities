from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from archpkg.core import PackageInfo, _strip_version

if TYPE_CHECKING:
    from collections.abc import Iterable

_PYALPM_AVAILABLE = False
try:
    import pyalpm  # type: ignore[import-untyped]

    _PYALPM_AVAILABLE = True
except ImportError:
    pass


def query_packages(package_names: Iterable[str]) -> dict[str, list[str]]:
    names = list(package_names)
    if _PYALPM_AVAILABLE:
        result = _query_via_pyalpm(names)
        if result:
            return _resolve_groups(names, result)
    return _query_via_pacman(names)


def query_pkg_info(package_names: Iterable[str]) -> dict[str, PackageInfo]:
    names = list(package_names)
    if _PYALPM_AVAILABLE:
        result = _query_info_via_pyalpm(names)
        if result:
            return _resolve_info_groups(names, result)
    return _query_info_via_pacman(names)


def _query_via_pyalpm(package_names: Iterable[str]) -> dict[str, list[str]]:
    handle = pyalpm.Handle("/", "/var/lib/pacman")
    local_db = handle.get_localdb()
    sync_dbs = _sync_dbs(handle)

    need = set(package_names)
    result: dict[str, list[str]] = {}

    for db in (local_db, *sync_dbs):
        for name in sorted(need):
            pkg = db.get_pkg(name)
            if pkg is not None:
                deps = _extract_depnames(pkg.depends)
                result[name] = [_strip_version(d) for d in deps]
                need.discard(name)

    return result


def _query_info_via_pyalpm(
    package_names: Iterable[str],
) -> dict[str, PackageInfo]:
    handle = pyalpm.Handle("/", "/var/lib/pacman")
    local_db = handle.get_localdb()
    sync_dbs = _sync_dbs(handle)

    need = set(package_names)
    result: dict[str, PackageInfo] = {}

    for db in (local_db, *sync_dbs):
        for name in sorted(need):
            pkg = db.get_pkg(name)
            if pkg is not None:
                result[name] = PackageInfo(
                    deps=[
                        _strip_version(d) for d in _extract_depnames(pkg.depends)
                    ],
                    provides=[
                        _strip_version(d) for d in _extract_depnames(pkg.provides)
                    ],
                )
                need.discard(name)

    return result


def _sync_dbs(handle: pyalpm.Handle) -> list[pyalpm.DB]:
    sync_root = Path(handle.dbpath) / "sync"
    sync_dbs: list[pyalpm.DB] = []
    if sync_root.is_dir():
        for entry in sorted(sync_root.iterdir()):
            if entry.suffix == ".db":
                db = handle.register_syncdb(
                    entry.stem, pyalpm.SIG_DATABASE_OPTIONAL,
                )
                if db is not None:
                    sync_dbs.append(db)
    return sync_dbs


def _extract_depnames(depends: list[object]) -> list[str]:
    if not depends:
        return []
    first = depends[0]
    if isinstance(first, str):
        return depends  # type: ignore[return-value]
    return [d.name for d in depends]  # type: ignore[union-attr]


def _query_via_pacman(package_names: Iterable[str]) -> dict[str, list[str]]:
    names = sorted(set(package_names))
    if not names:
        return {}

    proc = subprocess.run(
        ["pacman", "-Si", *names],
        capture_output=True,
        text=True,
        timeout=30,
    )

    result: dict[str, list[str]] = {}
    current_pkg: str | None = None

    for line in proc.stdout.splitlines():
        if line.startswith("Name "):
            current_pkg = line.split(":", 1)[1].strip()
            result[current_pkg] = []
        elif line.startswith("Depends On") and current_pkg is not None:
            deps_str = line.split(":", 1)[1].strip()
            if deps_str and deps_str != "None":
                result[current_pkg] = [
                    _strip_version(d) for d in deps_str.split()
                ]

    return _resolve_groups(names, result)


def _parse_sync_output(output: str) -> dict[str, PackageInfo]:
    result: dict[str, PackageInfo] = {}
    current_pkg: str | None = None

    for line in output.splitlines():
        if line.startswith("Name "):
            current_pkg = line.split(":", 1)[1].strip()
            result[current_pkg] = PackageInfo(deps=[], provides=[])
        elif current_pkg is not None and line.startswith("Provides"):
            provides_str = line.split(":", 1)[1].strip()
            if provides_str and provides_str != "None":
                result[current_pkg] = PackageInfo(
                    deps=result[current_pkg].deps,
                    provides=[_strip_version(p) for p in provides_str.split()],
                )
        elif current_pkg is not None and line.startswith("Depends On"):
            deps_str = line.split(":", 1)[1].strip()
            if deps_str and deps_str != "None":
                result[current_pkg] = PackageInfo(
                    deps=[_strip_version(d) for d in deps_str.split()],
                    provides=result[current_pkg].provides,
                )

    return result


def _query_info_via_pacman(
    package_names: Iterable[str],
) -> dict[str, PackageInfo]:
    names = sorted(set(package_names))
    if not names:
        return {}

    proc = subprocess.run(
        ["pacman", "-Si", *names],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return _resolve_info_groups(names, _parse_sync_output(proc.stdout))


def _resolve_groups(
    names: list[str], result: dict[str, list[str]],
) -> dict[str, list[str]]:
    unfound = [n for n in names if n not in result]
    if not unfound:
        return result

    proc = subprocess.run(
        ["pacman", "-Sg", *unfound],
        capture_output=True,
        text=True,
        timeout=10,
    )

    unfound_set = set(unfound)
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] in unfound_set:
            result.setdefault(parts[0], []).append(parts[1])

    return result


def _resolve_info_groups(
    names: list[str], result: dict[str, PackageInfo],
) -> dict[str, PackageInfo]:
    unfound = [n for n in names if n not in result]
    if not unfound:
        return result

    proc = subprocess.run(
        ["pacman", "-Sg", *unfound],
        capture_output=True,
        text=True,
        timeout=10,
    )

    unfound_set = set(unfound)
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] in unfound_set:
            info = result.setdefault(parts[0], PackageInfo(deps=[], provides=[]))
            result[parts[0]] = PackageInfo(
                deps=[*info.deps, parts[1]],
                provides=info.provides,
            )

    return result
