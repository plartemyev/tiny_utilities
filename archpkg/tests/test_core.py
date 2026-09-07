from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from archpkg.cli import main
from archpkg.core import sort_packages, classify_packages, _has_graphical_dep
from archpkg.pacman import _strip_version, _query_via_pacman, _resolve_groups


def _fake_query_fn(packages: list[str]) -> dict[str, list[str]]:
    known: dict[str, list[str]] = {
        "bash": ["glibc", "ncurses", "readline"],
        "vim": ["glibc", "ncurses", "acl"],
        "firefox": ["gtk3", "glibc", "nss"],
        "gtk3": ["glibc", "libx11", "cairo", "pango"],
        "qt6-base": ["glibc", "libxcb", "libgl"],
        "htop": ["glibc", "ncurses"],
        "libx11": ["glibc", "libxcb"],
        "alacritty": ["libxcb", "freetype2", "fontconfig"],
        "libreoffice-fresh-ru": ["libreoffice-fresh"],
        "libreoffice-fresh": ["libxrandr", "libgl", "libxinerama"],
        "libreoffice-ru": ["libreoffice-fresh"],
        "python-build-backend": [
            "meson-python", "python-hatchling", "python-setuptools",
        ],
        "meson-python": ["meson", "patchelf", "python"],
        "python-hatchling": ["python"],
        "python-setuptools": ["python"],
        "python": ["glibc", "expat", "bzip2"],
    }
    return {p: known[p] for p in packages if p in known}


class TestSortPackages:
    def test_empty(self) -> None:
        assert sort_packages([]) == []

    def test_sorted_unique(self) -> None:
        assert sort_packages(["bash", "vim", "htop"]) == ["bash", "htop", "vim"]

    def test_drops_duplicates(self) -> None:
        assert sort_packages(["bash", "vim", "bash", "htop", "vim"]) == [
            "bash",
            "htop",
            "vim",
        ]

    def test_case_sensitive_dedup(self) -> None:
        assert sort_packages(["Bash", "vim", "alacritty", "Vim"]) == [
            "alacritty",
            "Bash",
            "vim",
            "Vim",
        ]

    def test_single_package(self) -> None:
        assert sort_packages(["bash"]) == ["bash"]


class TestHasGraphicalDep:
    def test_no_graphical_dep(self) -> None:
        assert _has_graphical_dep(["glibc", "ncurses", "readline"]) is False

    def test_has_gtk3(self) -> None:
        assert _has_graphical_dep(["glibc", "gtk3", "nss"]) is True

    def test_has_libx11(self) -> None:
        assert _has_graphical_dep(["libx11"]) is True

    def test_has_wayland(self) -> None:
        assert _has_graphical_dep(["wayland", "glibc"]) is True

    def test_has_vulkan_dep(self) -> None:
        assert _has_graphical_dep(["glibc", "vulkan-icd-loader"]) is True

    def test_vulkan_prefix_match(self) -> None:
        assert _has_graphical_dep(["vulkan-mesa-layers"]) is True

    def test_non_vulkan_prefix(self) -> None:
        assert _has_graphical_dep(["vulkanfoo"]) is False

    def test_case_sensitive_match(self) -> None:
        assert _has_graphical_dep(["GTK3"]) is False

    def test_empty_deps(self) -> None:
        assert _has_graphical_dep([]) is False


class TestClassifyPackages:
    def test_all_console(self) -> None:
        console, graphical, missing = classify_packages(
            ["bash", "vim", "htop"], query_fn=_fake_query_fn,
        )
        assert console == ["bash", "htop", "vim"]
        assert graphical == []
        assert missing == []

    def test_mixed(self) -> None:
        console, graphical, missing = classify_packages(
            ["bash", "firefox", "vim", "alacritty"], query_fn=_fake_query_fn,
        )
        assert console == ["bash", "vim"]
        assert graphical == ["alacritty", "firefox"]
        assert missing == []

    def test_all_graphical(self) -> None:
        console, graphical, missing = classify_packages(
            ["firefox", "alacritty", "gtk3"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == ["alacritty", "firefox", "gtk3"]
        assert missing == []

    def test_graphical_indicator_itself(self) -> None:
        console, graphical, missing = classify_packages(
            ["libx11"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == ["libx11"]
        assert missing == []

    def test_vulkan_packages_graphical(self) -> None:
        console, graphical, missing = classify_packages(
            ["vulkan-headers", "vulkan-mesa-layers"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == ["vulkan-headers", "vulkan-mesa-layers"]
        assert missing == []

    def test_empty_input(self) -> None:
        console, graphical, missing = classify_packages([], query_fn=_fake_query_fn)
        assert console == []
        assert graphical == []
        assert missing == []

    def test_dedup_before_classify(self) -> None:
        console, graphical, missing = classify_packages(
            ["bash", "bash", "firefox", "firefox"], query_fn=_fake_query_fn,
        )
        assert console == ["bash"]
        assert graphical == ["firefox"]
        assert missing == []

    def test_transitive_graphical_dep(self) -> None:
        console, graphical, missing = classify_packages(
            ["libreoffice-fresh-ru"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == ["libreoffice-fresh-ru"]
        assert missing == []

    def test_transitive_graphical_dep_lang_pack(self) -> None:
        console, graphical, missing = classify_packages(
            ["libreoffice-ru"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == ["libreoffice-ru"]
        assert missing == []

    def test_missing_package(self) -> None:
        console, graphical, missing = classify_packages(
            ["bash", "nope", "vim"], query_fn=_fake_query_fn,
        )
        assert console == ["bash", "vim"]
        assert graphical == []
        assert missing == ["nope"]

    def test_all_unknown(self) -> None:
        console, graphical, missing = classify_packages(
            ["nope", "also-nope"], query_fn=_fake_query_fn,
        )
        assert console == []
        assert graphical == []
        assert missing == ["also-nope", "nope"]

    def test_group_package_console(self) -> None:
        console, graphical, missing = classify_packages(
            ["python-build-backend"], query_fn=_fake_query_fn,
        )
        assert console == ["python-build-backend"]
        assert graphical == []
        assert missing == []

    def test_group_package_mixed(self) -> None:
        console, graphical, missing = classify_packages(
            ["bash", "python-build-backend", "firefox", "nope"],
            query_fn=_fake_query_fn,
        )
        assert console == ["bash", "python-build-backend"]
        assert graphical == ["firefox"]
        assert missing == ["nope"]


class TestStripVersion:
    def test_no_version(self) -> None:
        assert _strip_version("glibc") == "glibc"

    def test_gte(self) -> None:
        assert _strip_version("glibc>=2.38") == "glibc"

    def test_eq(self) -> None:
        assert _strip_version("glibc=2.38") == "glibc"

    def test_lte(self) -> None:
        assert _strip_version("glibc<=2.38") == "glibc"

    def test_lt(self) -> None:
        assert _strip_version("glibc<2.38") == "glibc"

    def test_gt(self) -> None:
        assert _strip_version("glibc>2.38") == "glibc"

    def test_with_arch_suffix(self) -> None:
        assert _strip_version("libx11>=1.8.9-1") == "libx11"


class TestQueryPacman:
    def test_parses_sync_output(self) -> None:
        output = """Repository      : core
Name            : bash
Version         : 5.2.037-1
Description     : The GNU Bourne Again shell
Architecture    : x86_64
URL             : https://www.gnu.org/software/bash/bash.html
Licenses        : GPL-3.0-or-later
Groups          : None
Provides        : sh
Depends On      : glibc  ncurses  readline>=8.0
Optional Deps   : bash-completion: for tab completion
Conflicts With  : None
Replaces        : None
Download Size   : 1.78 MiB
Installed Size  : 7.10 MiB
Packager        : Developer <dev@archlinux.org>
Build Date      : Mon 01 Jan 2024 12:00:00 AM UTC
Validated By    : MD5 Sum  SHA-256 Sum  Signature

Repository      : extra
Name            : firefox
Version         : 133.0-1
Description     : Fast, Private & Safe Web Browser
Architecture    : x86_64
URL             : https://www.mozilla.org/firefox/
Licenses        : MPL-2.0
Groups          : None
Provides        : None
Depends On      : gtk3  glibc  nss  nspr
Optional Deps   : networkmanager: Location detection via available WiFi networks
Conflicts With  : None
Replaces        : None
Download Size   : 68.00 MiB
Installed Size  : 250.00 MiB
Packager        : Developer <dev@archlinux.org>
Build Date      : Mon 01 Jan 2024 12:00:00 AM UTC
Validated By    : MD5 Sum  SHA-256 Sum  Signature"""

        expected: dict[str, list[str]] = {
            "bash": ["glibc", "ncurses", "readline"],
            "firefox": ["gtk3", "glibc", "nss", "nspr"],
        }

        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=output, stderr="",
            )
            result = _query_via_pacman(["bash", "firefox"])
            assert result == expected

    def test_no_deps(self) -> None:
        output = """Name            : meta-pkg
Depends On      : None"""
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=output, stderr="",
            )
            result = _query_via_pacman(["meta-pkg"])
            assert result == {"meta-pkg": []}

    def test_empty_input(self) -> None:
        assert _query_via_pacman([]) == {}

    def test_resolves_groups(self) -> None:
        si_output = """Name            : bash
Depends On      : glibc  ncurses"""
        sg_output = """python-build-backend meson-python
python-build-backend python-hatchling
python-build-backend python-setuptools"""

        def run_side_effect(*args, **kwargs):
            cmd = args[0]
            if "-Si" in cmd or cmd[0] == "pacman" and cmd[1] == "-Si":
                return MagicMock(returncode=0, stdout=si_output, stderr="")
            if "-Sg" in cmd or cmd[0] == "pacman" and cmd[1] == "-Sg":
                return MagicMock(returncode=0, stdout=sg_output, stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(subprocess, "run", side_effect=run_side_effect):
            result = _query_via_pacman(["bash", "python-build-backend"])
        assert result["bash"] == ["glibc", "ncurses"]
        assert result["python-build-backend"] == [
            "meson-python", "python-hatchling", "python-setuptools",
        ]

    def test_resolve_groups_no_match(self) -> None:
        input_names = ["bash", "nope"]
        result = {"bash": ["glibc", "ncurses"]}
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="error: package group 'nope' was not found",
            )
            out = _resolve_groups(input_names, result)
        assert out is result
        assert "nope" not in out

    def test_resolve_groups_partial_match(self) -> None:
        input_names = ["bash", "nope", "python-build-backend"]
        result = {"bash": ["glibc", "ncurses"]}
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="python-build-backend meson-python\npython-build-backend python-setuptools",
                stderr="error: package group 'nope' was not found",
            )
            out = _resolve_groups(input_names, result)
        assert "nope" not in out
        assert out["python-build-backend"] == ["meson-python", "python-setuptools"]


class TestCLI:
    def test_sort_basic(self, capsys) -> None:
        with patch("archpkg.cli.query_packages") as mock_query:
            mock_query.return_value = {"bash": ["glibc"], "zsh": ["glibc"]}
            main(["zsh", "bash", "bash"])
        captured = capsys.readouterr()
        assert captured.out.strip() == (
            "===SORTED PACKAGES:===\n"
            "bash zsh\n"
            "\n"
            "Missing packages: (none)\n"
            "\n"
            "1 duplicate removed."
        )

    def test_sort_console_only(self, capsys) -> None:
        with patch.object(subprocess, "run") as mock_run:
            output = """Name            : bash
Depends On      : glibc  ncurses
Name            : firefox
Depends On      : gtk3  glibc"""
            mock_run.return_value = MagicMock(
                returncode=0, stdout=output, stderr="",
            )
            main(["--console-only", "bash", "firefox"])
        captured = capsys.readouterr()
        assert "Console-only packages:" in captured.out
        assert "bash" in captured.out
        assert "Graphical packages:" in captured.out
        assert "firefox" in captured.out
        assert "Missing packages:" in captured.out

    def test_sort_missing_package(self, capsys) -> None:
        with patch("archpkg.cli.query_packages") as mock_query:
            mock_query.return_value = {"bash": ["glibc"]}
            main(["bash", "nope"])
        captured = capsys.readouterr()
        assert "===SORTED PACKAGES:===" in captured.out
        assert "bash nope" in captured.out
        assert "Missing packages:" in captured.out
        assert "nope" in captured.out

    def test_classify_missing_package(self, capsys) -> None:
        with patch.object(subprocess, "run") as mock_run:
            output = """Name            : bash
Depends On      : glibc  ncurses"""
            mock_run.return_value = MagicMock(
                returncode=0, stdout=output, stderr="",
            )
            main(["--console-only", "bash", "nope"])
        captured = capsys.readouterr()
        assert "Console-only packages:" in captured.out
        assert "bash" in captured.out
        assert "Missing packages:" in captured.out
        assert "nope" in captured.out

    def test_group_sort(self, capsys) -> None:
        with patch("archpkg.cli.query_packages") as mock_query:
            mock_query.return_value = {
                "bash": ["glibc"],
                "python-build-backend": [
                    "meson-python", "python-hatchling",
                ],
            }
            main(["python-build-backend", "bash"])
        captured = capsys.readouterr()
        assert "===SORTED PACKAGES:===" in captured.out
        assert "bash python-build-backend" in captured.out
        assert "Missing packages: (none)" in captured.out

    def test_group_classify(self, capsys) -> None:
        with patch("archpkg.cli.query_packages") as mock_query:
            mock_query.return_value = {
                "bash": ["glibc"],
                "python-build-backend": [
                    "meson-python", "python-hatchling", "python-setuptools",
                ],
                "meson-python": ["meson", "python"],
                "python-hatchling": ["python"],
                "python-setuptools": ["python"],
            }
            main(["--console-only", "bash", "python-build-backend"])
        captured = capsys.readouterr()
        assert "Console-only packages:" in captured.out
        assert "bash" in captured.out
        assert "python-build-backend" in captured.out
        assert "Graphical packages: (none)" in captured.out
        assert "Missing packages: (none)" in captured.out
