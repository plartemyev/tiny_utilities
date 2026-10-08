#!/usr/bin/env python3
"""Harvest spelling issues from codebook-lsp and auto-classify the flagged words.

Pipeline (subcommand `harvest`):
  1. `codebook-lsp lint -u <files>` -> deduplicated set of flagged words.
  2. Package-manager filter: pacman / dnf / apt / zypper. Each package manager is
     queried ONCE (single subshell per list; direct DB parsing needs PM-specific
     libraries/format parsers — one C-speed `pacman -Slq` beats them for
     portability). All names go into a Python set: per-term membership is O(1),
     i.e. the batching happens at the DB-read level, not per term.
  3. Path filter: terms that EQUAL a whole component of an installed package's
     file path, after splitting every path on realistic separators
     (- / . _ space). Paths are read once (`pacman -Qlq`) and exploded into a
     component set; per-term membership is O(1) whole-word matching.
  4. LLM filter for the remainder: an LLM judges "valid technical term vs
     spelling issue". Serial (one term per call) or batched (N terms per call).
     Default provider: ollama on 127.0.0.1:11434.
  5. `codebook-lsp add -g <terms...>` (batched: one process for all terms) for
     packages + llm_validated sets. Only with --apply; otherwise dry run.

Subcommand `benchmark` measures correctness and latency of LLM models on a
labeled corpus (serial vs batch, thinking on vs off).

No third-party dependencies (urllib, tomllib, subprocess only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CODEBOOK_LSP_FALLBACKS = sorted(
    Path.home().glob(".local/share/zed/extensions/work/codebook/codebook-lsp-v*/codebook-lsp")
)
LLM_DEADLINE_S = 300  # hard deadline for a single LLM call (laptop, slow models)
CACHE_DIR = Path.home() / ".cache" / "codebook-harvest"
PM_NAMES_TTL_S = 24 * 3600


def find_codebook_lsp(explicit: str | None) -> Path:
    """Locate the codebook-lsp binary: --codebook-lsp, PATH, then Zed's work dir."""
    if explicit:
        path = Path(explicit).expanduser()
        assert path.is_file(), f"codebook-lsp not found: {path}"
        return path
    from_path = shutil.which("codebook-lsp")
    if from_path:
        return Path(from_path)
    for candidate in reversed(CODEBOOK_LSP_FALLBACKS):  # highest version last
        if candidate.is_file():
            return candidate
    sys.exit("error: codebook-lsp not found (PATH or ~/.local/share/zed/extensions/work/codebook)")


# ---------------------------------------------------------------- harvesting


def expand_targets(entries: list[str]) -> list[str]:
    """Expand target paths: files pass through; directories yield either git
    tracked files (when the directory is inside a git work tree) or all files
    from a recursive walk (skipping .git internals)."""
    git = shutil.which("git")
    files: list[str] = []
    for entry in entries:
        entry = os.path.expanduser(entry)
        if not os.path.isdir(entry):
            files.append(entry)
            continue
        in_repo = False
        if git:
            probe = subprocess.run(
                [git, "-C", entry, "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=60)
            in_repo = probe.returncode == 0 and probe.stdout.strip() == "true"
        if in_repo:
            listed = subprocess.run(
                [git, "-C", entry, "ls-files"], capture_output=True, text=True,
                timeout=300, check=True)
            candidates = (os.path.join(entry, name) for name in listed.stdout.splitlines())
            source = "git tracked"
        else:
            walk_files = []
            for root, dirs, names in os.walk(entry):
                dirs[:] = [d for d in dirs if d != ".git"]
                walk_files.extend(os.path.join(root, name) for name in names)
            candidates = walk_files
            source = "recursive walk"
        before = len(files)
        files.extend(candidate for candidate in candidates if os.path.isfile(candidate))
        print(f"[0] {entry}: {len(files) - before} files ({source})")
    return list(dict.fromkeys(files))  # dedupe, keep order


def lint_words(cb: Path, files: list[str]) -> set[str]:
    """Run `codebook-lsp lint -u` and collect the unique flagged words."""
    result = subprocess.run(
        [str(cb), "lint", "-u", *files], capture_output=True, text=True, timeout=600
    )
    if result.returncode not in (0, 1):
        sys.exit(f"error: codebook-lsp lint failed: {result.stderr.strip()}")
    words = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^.+:\d+:\d+\s+(\S+)\s*$", line)
        if match:
            words.add(match.group(1))
    return words


def add_words(cb: Path, words: set[str], global_dict: bool) -> None:
    """Add words to the codebook dictionary in one batched call."""
    if not words:
        return
    cmd = [str(cb), "add"]
    if global_dict:
        cmd.append("--global")
    cmd.extend(sorted(words))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        sys.exit(f"error: codebook-lsp add failed: {result.stderr.strip()}")


# ------------------------------------------------------------ package manager


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])}...: {result.stderr.strip()[:200]}")
    return result.stdout


class PackageDB:
    """One-shot package names + installed paths for a package manager.

    Optimization notes: querying the DB once per run and doing set membership
    in Python is O(1) per term. Parsing pacman's zstd tarball DBs directly
    (Python 3.14 compression.zstd) saves ~100ms vs `pacman -Slq` but adds
    format-parsing code for zero practical gain — the subshell IS the index.
    """

    PM_COMMANDS = {
        "pacman": ("pacman",),
        "dnf": ("dnf",),
        "apt": ("apt",),
        "zypper": ("zypper",),
    }

    def __init__(self, pm: str):
        self.pm = pm
        if not shutil.which(self.PM_COMMANDS[pm][0]):
            raise RuntimeError(f"package manager not found: {pm}")

    def available_names(self) -> set[str]:
        """All package names known to the PM (repos + installed), lowercased."""
        cached = self._load_cache()
        if cached is not None:
            return cached
        names = {
            "pacman": self._pacman_names,
            "dnf": self._dnf_names,
            "apt": self._apt_names,
            "zypper": self._zypper_names,
        }[self.pm]()
        names = {name.lower() for name in names}
        self._save_cache(names)
        return names

    def installed_paths(self) -> list[str]:
        """File paths of all installed packages (best effort; empty if unsupported)."""
        if self.pm == "pacman":
            return _run(["pacman", "-Qlq"]).splitlines()
        if self.pm in ("dnf", "zypper") and shutil.which("rpm"):
            return _run(["rpm", "-qla"]).splitlines()
        if self.pm == "apt" and shutil.which("apt-file"):
            return _run(["apt-file", "list"]).split()  # "pkg: /path" entries
        print(f"warning: installed-path search not supported for {self.pm}", file=sys.stderr)
        return []

    def installed_components(self) -> set[str]:
        """Whole path components of all installed files (split on - / . _ space),
        cached like package names: rebuilding splits ~1M paths every run."""
        cache_file = CACHE_DIR / f"{self.pm}-components.json"
        if cache_file.is_file():
            data = json.loads(cache_file.read_text())
            if time.time() - data["ts"] <= PM_NAMES_TTL_S:
                return set(data["components"])
        components: set[str] = set()
        for path in self.installed_paths():
            components.update(PATH_SEPARATORS.split(path.lower()))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"ts": time.time(), "components": sorted(components)}))
        return components

    def _pacman_names(self) -> set[str]:
        names = set(_run(["pacman", "-Slq"]).splitlines())
        names.update(_run(["pacman", "-Qq"]).splitlines())
        return names

    def _dnf_names(self) -> set[str]:
        names = set()
        if shutil.which("dnf"):
            for line in _run(["dnf", "-q", "--cacheonly", "list", "available"]).splitlines()[1:]:
                parts = line.split()
                if parts and "." not in parts[0]:
                    names.add(parts[0])
        if shutil.which("rpm"):
            names.update(_run(["rpm", "-qa", "--qf", "%{NAME}\n"]).splitlines())
        return names

    def _apt_names(self) -> set[str]:
        names = set(_run(["apt-cache", "pkgnames"]).splitlines())
        names.update(_run(["dpkg-query", "-W", "-f=${Package}\n"]).splitlines())
        return names

    def _zypper_names(self) -> set[str]:
        names = set()
        for line in _run(["zypper", "-q", "se", "-s", "-t", "package"]).splitlines():
            parts = line.split()
            if len(parts) > 3:
                names.add(parts[2])  # "i+ | name | version | ..."
        if shutil.which("rpm"):
            names.update(_run(["rpm", "-qa", "--qf", "%{NAME}\n"]).splitlines())
        return names

    def _load_cache(self) -> set[str] | None:
        cache_file = CACHE_DIR / f"{self.pm}-names.json"
        if not cache_file.is_file():
            return None
        data = json.loads(cache_file.read_text())
        if time.time() - data["ts"] > PM_NAMES_TTL_S:
            return None
        return set(data["names"])

    def _save_cache(self, names: set[str]) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{self.pm}-names.json"
        cache_file.write_text(json.dumps({"ts": time.time(), "names": sorted(names)}))


PATH_SEPARATORS = re.compile(r"[-/._ ]+")


def classify_by_packages(words: set[str], db: PackageDB) -> tuple[set[str], set[str]]:
    """Split words into (packages_set, remainder) using names + installed paths.

    A path hit requires the term to equal a WHOLE path component after splitting
    on realistic separators (- / . _ space) — plain substring matching let
    fragments like `insta` (from install*) slip through.
    """
    names = db.available_names()
    packages = {word for word in words if word.lower() in names}
    remainder = words - packages
    if not remainder:
        return packages, remainder
    components = db.installed_components()
    path_hits = {word for word in remainder if word.lower() in components}
    return packages | path_hits, remainder - path_hits


# ------------------------------------------------------------------ LLM step

PROMPT_SERIAL = (
    "Is it a valid technical/specialized word spelling or a spelling issue: `{term}`? "
    "The word was lowercased up the pipeline before passing to you, so ignore the case. "
    "Treat concatenated multi-word term as a valid and correct term. "
    "Context is a software source code. Do not overthink. "
    "Answer only `0` if valid, `1` if it is a spelling issue."
)

PROMPT_BATCH = (
    "Is it a valid technical/specialized word spelling or a spelling issue: `[{terms}]`? "
    "The word was lowercased up the pipeline before passing to you, so ignore the case. "
    "Treat concatenated multi-word term as a valid and correct term. "
    "Context is a software source code. Do not overthink. "
    "Answer only `0` if valid, `1` if it is a spelling issue in place of a word, "
    "example output format: `[0, 1, 1, 0, 0]`."
)

BIT = re.compile(r"(?<![0-9])[01](?![0-9])")


def llm_chat(base_url: str, model: str, prompt: str, think: bool, timeout: int) -> tuple[str, bool, bool]:
    """One ollama /api/chat call.

    Returns (content, think_supported, thinks_anyway). `content` has any
    embedded <think> block stripped; `thinks_anyway` marks hybrid models that
    think even with think=false (then the whole call just needs more
    num_predict headroom, see below).
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": 2048 if think else 512},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 400 and think:  # model likely has no thinking support
            return "", False, False
        print(f"warning: LLM HTTP {error.code}", file=sys.stderr)
        return "", True, False
    except (TimeoutError, urllib.error.URLError) as error:  # deadline hit / conn dropped
        timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
        print(f"warning: LLM call {'timed out after ' + str(timeout) + 's' if timed_out else f'failed: {error}'}",
              file=sys.stderr)
        return "", True, False
    content = body["message"]["content"]
    thinks_anyway = not think and "<think>" in content
    if "<think>" in content:  # hybrid thinker: keep only the post-think answer
        content = content.rsplit("</think>", 1)[-1]
    return content, True, thinks_anyway


def llm_verdicts(base_url: str, model: str, terms: list[str], batch_size: int,
                 think: bool, timeout: int) -> tuple[dict[str, int], dict[str, object]]:
    """Judge terms via LLM. Returns ({term: 0|1}, stats)."""
    stats: dict[str, object] = {"calls": 0, "parse_fail": 0, "think_unsupported": False,
                                "thinks_anyway": False, "latencies": [], "fail_samples": []}
    verdicts: dict[str, int] = {}
    if batch_size <= 1:
        for term in terms:
            start = time.monotonic()
            content, supported, thinks_anyway = llm_chat(
                base_url, model, PROMPT_SERIAL.format(term=term), think, timeout)
            stats["latencies"].append(time.monotonic() - start)
            stats["calls"] += 1
            stats["thinks_anyway"] = stats["thinks_anyway"] or thinks_anyway
            if not supported:
                stats["think_unsupported"] = True
                content, _, _ = llm_chat(base_url, model, PROMPT_SERIAL.format(term=term), False, timeout)
                stats["calls"] += 1
            bits = BIT.findall(content)
            if bits:
                verdicts[term] = int(bits[0])
            else:
                stats["parse_fail"] += 1
                if len(stats["fail_samples"]) < 3:  # type: ignore[arg-type]
                    stats["fail_samples"].append(content[:200])  # type: ignore[union-attr]
    else:
        for chunk_start in range(0, len(terms), batch_size):
            chunk = terms[chunk_start:chunk_start + batch_size]
            start = time.monotonic()
            content, supported, thinks_anyway = llm_chat(
                base_url, model, PROMPT_BATCH.format(terms=", ".join(chunk)), think, timeout)
            stats["latencies"].append(time.monotonic() - start)
            stats["calls"] += 1
            stats["thinks_anyway"] = stats["thinks_anyway"] or thinks_anyway
            if not supported:
                stats["think_unsupported"] = True
                content, _, _ = llm_chat(
                    base_url, model, PROMPT_BATCH.format(terms=", ".join(chunk)), False, timeout)
                stats["calls"] += 1
            bits = [int(bit) for bit in BIT.findall(content)]
            if len(bits) == len(chunk):
                verdicts.update(dict(zip(chunk, bits)))
            else:
                stats["parse_fail"] += len(chunk)
                if len(stats["fail_samples"]) < 3:  # type: ignore[arg-type]
                    stats["fail_samples"].append(f"got {len(bits)} bits: {content[:200]}")  # type: ignore[union-attr]
    return verdicts, stats


# ------------------------------------------------------------------ benchmark

# Corpus: every unique word codebook flags in archinstaller/script.py (2026-10-08),
# hand-labeled. Invalid (spelling issues / artifacts): euo (`set -euo` flag cluster),
# xef (hex 0xef), ipv (ipv4/ipv6 fragment), imagesdparm (real typo: sdl_imagesdparm
# is not a package — should be sdl2_image + sdparm). All other terms are real
# packages, commands, library prefixes, config filenames or concatenated terms.
BENCH_INVALID = {"euo", "xef", "ipv", "imagesdparm"}
BENCH_VALID_SAMPLE = [
    "silverlightbottompanel", "iface", "archlinux", "mirrorlist", "nox",       # user's examples + concat
    "dhcpcd", "hdparm", "lsscsi", "jfsutils", "inetutils",                     # real pacman packages
    "vkd", "tpd", "dzn", "rav", "aribb",                                       # split parts of real names
    "blendr", "grml", "espeakup", "imvirt", "terragrunt",                      # tricky real packages
    "unmaps", "reinstalls", "esac", "mkconfig", "noconfirm",                   # English / shell
    "kcminputrc", "lookandfeel", "LPIB", "sdkresolver", "gopls",               # configs / acronyms / tools
    "psycopg", "passff", "gfxstream", "lsign", "ublock",                       # niche technical terms
]

MODELS = ["lfm2.5:8b", "granite4.2:3b", "ornith-1.5:9b"]


def benchmark(args: argparse.Namespace) -> None:
    labels = {term: 0 for term in BENCH_VALID_SAMPLE} | {term: 1 for term in BENCH_INVALID}
    terms = sorted(labels)
    results = []
    for model in args.models:
        for think in (False, True):
            # untimed warm-up: model load + think-capability probe
            _, supported, _ = llm_chat(args.base_url, model, PROMPT_SERIAL.format(term="validword"), think, args.timeout)
            if not supported:
                print(f"{model} think={think}: no thinking support, skipping (think=on falls back to plain)")
            for mode, batch_size in (("serial", 1), (f"batch{args.batch_size}", args.batch_size)):
                start = time.monotonic()
                verdicts, stats = llm_verdicts(
                    args.base_url, model, terms, batch_size, think, args.timeout
                )
                wall = time.monotonic() - start
                judged = {t: v for t, v in verdicts.items() if t in labels}
                correct = sum(1 for t, v in judged.items() if v == labels[t])
                latencies = sorted(stats["latencies"])
                row = {
                    "model": model, "mode": mode, "think": think,
                    "wall_s": round(wall, 1), "calls": stats["calls"],
                    "lat_mean_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
                    "lat_max_s": round(latencies[-1], 2) if latencies else None,
                    "accuracy": f"{correct}/{len(labels)}",
                    "judged": len(judged),
                    "parse_fail": stats["parse_fail"],
                    "think_unsupported": bool(stats["think_unsupported"]),
                    "thinks_anyway": bool(stats["thinks_anyway"]),
                    "wrong": sorted(t for t, v in judged.items() if v != labels[t]),
                    "fail_samples": stats["fail_samples"],
                }
                results.append(row)
                print(json.dumps(row, ensure_ascii=False))
    args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"saved: {args.out}")


# --------------------------------------------------------------------- main


def harvest(args: argparse.Namespace) -> None:
    cb = find_codebook_lsp(args.codebook_lsp)
    files = expand_targets(args.files)
    if not files:
        sys.exit("error: no files to check")
    words = lint_words(cb, files)
    print(f"[1] codebook-lsp flagged {len(words)} unique words")
    if args.skip_pkg:
        packages, remainder = set(), words
    else:
        try:
            db = PackageDB(args.pm)
            packages, remainder = classify_by_packages(words, db)
            print(f"[2] package names: {len([w for w in packages if w.lower() in db.available_names()])}, "
                  f"installed-path matches: {len(packages)}")
        except RuntimeError as error:
            print(f"warning: package filter skipped ({error})", file=sys.stderr)
            packages, remainder = set(), words
    llm_validated: set[str] = set()
    if remainder and not args.skip_llm:
        verdicts, stats = llm_verdicts(
            args.base_url, args.model, sorted(remainder), args.batch_size, args.think, args.timeout
        )
        llm_validated = {term for term, bit in verdicts.items() if bit == 0}
        remainder -= llm_validated
        print(f"[3] llm ({args.model}, batch={args.batch_size}, think={args.think}): "
              f"{stats['calls']} calls, {stats['parse_fail']} parse failures -> "
              f"{len(llm_validated)} validated")
    to_add = packages | llm_validated
    if args.apply:
        add_words(cb, to_add, global_dict=True)
        print(f"[4] added {len(to_add)} words via codebook-lsp add --global")
    else:
        print(f"[4] dry run: {len(to_add)} words would be added (use --apply)")
    print(f"\n--- packages set ({len(packages)}) ---")
    print(" ".join(sorted(packages)))
    print(f"\n--- llm_validated set ({len(llm_validated)}) ---")
    print(" ".join(sorted(llm_validated)))
    print(f"\n--- remainder / unidentified ({len(remainder)}) ---")
    if remainder:
        quoted = " ".join(shlex.quote(word) for word in sorted(remainder))
        print("tip: spot more valid words below? add them in one batch (trim first):")
        print(f"  {cb} add -g {quoted}")
    print(" ".join(sorted(remainder)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_harvest = sub.add_parser("harvest", help="lint files and classify flagged words")
    p_harvest.add_argument("files", nargs="+", metavar="FILE",
                           help="file or directory (git-tracked files if in a git "
                                "work tree, else all files recursively)")
    p_harvest.add_argument("--codebook-lsp", help="path to codebook-lsp (default: PATH or Zed work dir)")
    p_harvest.add_argument("--pm", default="pacman", choices=sorted(PackageDB.PM_COMMANDS))
    p_harvest.add_argument("--skip-pkg", action="store_true", help="skip package/path filtering")
    p_harvest.add_argument("--skip-llm", action="store_true", help="skip the LLM round")
    p_harvest.add_argument("--provider", default="ollama", choices=["ollama"],
                           help="LLM provider (only ollama implemented so far)")
    p_harvest.add_argument("--base-url", default="http://127.0.0.1:11434")
    p_harvest.add_argument("--model", default="granite4.2:3b",
                           help="LLM model (default: granite4.2:3b — benchmark winner, see benchmark subcommand)")
    p_harvest.add_argument("--batch-size", type=int, default=1,
                           help="terms per LLM call; 1 = serial (default: 1 — batch proven unreliable, "
                                "models return wrong verdict counts)")
    p_harvest.add_argument("--think", action="store_true", help="enable model thinking mode")
    p_harvest.add_argument("--timeout", type=int, default=LLM_DEADLINE_S,
                           help=f"per-call LLM deadline in seconds (default: {LLM_DEADLINE_S})")
    p_harvest.add_argument("--apply", action="store_true",
                           help="actually run codebook-lsp add --global (default: dry run)")
    p_harvest.set_defaults(func=harvest)

    p_bench = sub.add_parser("benchmark", help="benchmark LLM models on the labeled corpus")
    p_bench.add_argument("--models", nargs="+", default=MODELS)
    p_bench.add_argument("--base-url", default="http://127.0.0.1:11434")
    p_bench.add_argument("--batch-size", type=int, default=10)
    p_bench.add_argument("--timeout", type=int, default=LLM_DEADLINE_S)
    p_bench.add_argument("--out", type=Path, default=CACHE_DIR / "benchmark.json")
    p_bench.set_defaults(func=benchmark)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
