#!/usr/bin/env python3
"""Enrich the Codebook (Zed) and IntelliJ spell-checker dictionaries from each other.

Both files are rewritten with the merged word set:
  * Codebook global dictionary: TOML -> words = ["...", ...] (sorted case-insensitively)
  * IntelliJ cached dictionary: XML  -> <w> records (sorted like the IDE: ordinal)

Deduplication is case-insensitive (both checkers match words case-insensitively);
when the same word appears in several casings, the all-lowercase record is kept.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from xml.sax.saxutils import escape

DEFAULT_ZED_DICT = Path("~/.config/codebook/codebook.toml")
DEFAULT_INTELLIJ_DICT = Path("~/Documents/Private/utils/pycharm/spellchecker-dictionary.xml")


def read_zed(path: Path) -> list[str]:
    """Read the word list from the Codebook TOML dictionary."""
    assert path.is_file(), f"not a file: {path}"
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    words = data.get("words", [])
    assert all(isinstance(word, str) for word in words), f"non-string entries in {path}"
    return words


def read_intellij(path: Path) -> tuple[str, list[str]]:
    """Read the component name and word list from the IntelliJ dictionary XML."""
    assert path.is_file(), f"not a file: {path}"
    root = ET.parse(path).getroot()
    component = root.find("component")
    assert component is not None and component.get("name"), f"no <component name=...> in {path}"
    words = [word for element in root.iter("w") if (word := element.text or "").strip()]
    return component.get("name"), words


def merge_words(*word_lists: list[str]) -> dict[str, str]:
    """Union the word lists; key = lowercase, value = kept record (prefer lowercase)."""
    canonical: dict[str, str] = {}
    for words in word_lists:
        for word in words:
            key = word.lower()
            kept = canonical.get(key)
            if kept is None or (word == key and kept != key):
                canonical[key] = word
    return canonical


def atomic_write(path: Path, text: str) -> bool:
    """Write text to path atomically (same-dir tmp + rename); True when content changed."""
    if path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


TOML_WORDS_BLOCK = re.compile(r"(?ms)^words\s*=\s*\[.*?^\]\s*$")
TOML_WORDS_INLINE = re.compile(r"^words\s*=\s*\[[^\]]*\]", re.M)


def write_zed(path: Path, words: Iterable[str]) -> bool:
    """Rewrite ONLY the `words` array in the Codebook TOML (any other keys,
    e.g. `dictionaries`, comments and formatting are preserved); True when changed."""
    ordered = sorted(words, key=str.lower)
    if ordered:
        entries = ",\n".join(f"    {json.dumps(word, ensure_ascii=False)}" for word in ordered)
        block = f"words = [\n{entries},\n]"
    else:
        block = "words = []"
    old = path.read_text(encoding="utf-8")
    if TOML_WORDS_BLOCK.search(old) or TOML_WORDS_INLINE.search(old):
        new = TOML_WORDS_BLOCK.sub(lambda _: block, old, count=1)
        new = TOML_WORDS_INLINE.sub(lambda _: block, new, count=1)
    else:
        new = old.rstrip("\n") + "\n\n" + block + "\n"
    return atomic_write(path, new)


def write_intellij(path: Path, component_name: str, words: Iterable[str]) -> bool:
    """Rewrite the IntelliJ XML with the merged words; True when changed."""
    lines = ["<application>", f'  <component name="{escape(component_name)}">', "    <words>"]
    lines.extend(f"      <w>{escape(word)}</w>" for word in sorted(words))
    lines.extend(["    </words>", "  </component>", "</application>", ""])
    return atomic_write(path, "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync (enrich) the Codebook/Zed and IntelliJ spell-checker dictionaries both ways."
    )
    parser.add_argument(
        "--zed-dict", type=Path, default=DEFAULT_ZED_DICT, metavar="TOML",
        help=f"Codebook dictionary (default: {DEFAULT_ZED_DICT})",
    )
    parser.add_argument(
        "--intellij-dict", type=Path, default=DEFAULT_INTELLIJ_DICT, metavar="XML",
        help=f"IntelliJ dictionary (default: {DEFAULT_INTELLIJ_DICT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.zed_dict = args.zed_dict.expanduser()
    args.intellij_dict = args.intellij_dict.expanduser()
    zed_words = read_zed(args.zed_dict)
    component_name, intellij_words = read_intellij(args.intellij_dict)
    merged = merge_words(zed_words, intellij_words)
    dropped = len(zed_words) + len(intellij_words) - len(merged)
    added_zed = sum(1 for key in merged if key not in {word.lower() for word in zed_words})
    added_intellij = sum(1 for key in merged if key not in {word.lower() for word in intellij_words})
    updated_zed = write_zed(args.zed_dict, merged.values())
    updated_intellij = write_intellij(args.intellij_dict, component_name, merged.values())
    if updated_zed or updated_intellij:
        print(f"{len(zed_words)} zed + {len(intellij_words)} intellij records -> "
              f"{len(merged)} unique words ({dropped} duplicate record(s) dropped)")
    for label, path, added, updated in (
        ("zed", args.zed_dict, added_zed, updated_zed),
        ("intellij", args.intellij_dict, added_intellij, updated_intellij),
    ):
        change = f"+{added} words, " if added else ""
        print(f"{path} [{label}]: {change}{'updated' if updated else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
