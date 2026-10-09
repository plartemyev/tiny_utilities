# codebook-dictionary-harvest

Harvest spelling issues from [codebook-lsp](https://github.com/blopker/codebook) (the
spell checker behind Zed's "Possible spelling issue" hints) and automatically classify
the flagged words, so only genuine terms enter your spelling dictionary.

`codebook`'s own "Add to global dictionary" works one word at a time and trusts the
author. This tool bulk-harvests a whole project and runs the flagged words through
filters that know the difference between `powerdevilrc` (valid), `insta` (fragment)
and `imagesdparm` (a real typo).

The repository also hosts **`sync_spell_dictionaries.py`**, a two-way enricher between
this Codebook dictionary and the JetBrains/IntelliJ spellchecker dictionary (see below).

## Pipeline (`harvest` subcommand)

```
[0] targets → file list      files pass through; a directory yields git-tracked files
                             (`git ls-files`) when inside a git work tree, otherwise
                             a recursive walk (skipping .git/ and typically hash-ridden
                             files: *.lock, package-lock.json, go.sum, …)
[1] codebook-lsp lint        flagged words, deduplicated; every occurrence is kept
                             and each word is expanded to its full source token(s) —
                             codebook-lsp splits tokens at digit boundaries
                             (`aribb24` is flagged as `aribb`)
[2] package filter           the word OR its full token ∈ package names (pacman/dnf/
                             apt/zypper, one-shot subshell lists) OR equals a whole
                             component of an installed package's file path (paths
                             split on - / . _ space)     → packages + full tokens
[3] possessives              tokens like `workspace's`/`swapon'ed` (codebook-lsp
                             keeps the apostrophe inside words, its dictionaries
                             carry no possessive forms) validated by their stem
                             against packages/paths      → possessives (token→stem)
[4] LLM round                remainder judged "valid technical term vs spelling
                             issue" by a local LLM (ollama by default); possessive
                             tokens are judged via their stem → llm_validated
[5] codebook-lsp add -g      packages + full tokens + possessives (token AND stem)
                             + llm_validated in ONE batched call
                             (dry run unless --apply)          → remainder printed
```

Stage `[2]` errs toward inclusion; stage `[4]` errs toward exclusion: anything the LLM
fails to parse or times out on lands in the *remainder*, never in the dictionary.

### codebook-lsp tokenizer facts (probed 2026-10-09, v0.3.42)

Both quirks are why the harvest reconstructs source tokens instead of using the flagged
word as-is:

- **Digits split words**: `aribb24` is flagged — and dictionary-looked-up — as `aribb`.
  Adding the real name `aribb24` to the dictionary silences *nothing*; only the fragment
  `aribb` does. The package filter therefore matches the word *and* its full token and
  adds both (`aribb` silences, `aribb24` documents the real name).
- **Apostrophes stay inside words, possessives are not in the dictionaries**:
  `workspace's` flags although `workspace` is a perfectly good word (`don't` passes only
  because contractions ship in the word list). Silencing requires adding the exact token
  (`VM's`, `bdd's` in the global dict were added that way). The harvest classifies such
  tokens by stemming `'s`/`'d`/`'ed` and validates the stem — against packages/paths, or
  via the LLM — then adds token + stem together. Tokens with an internal apostrophe
  (string literals like the test password `ro'ot`) are left to the LLM/remainder.

## Requirements

- Python 3.10+ (stdlib only: subprocess, urllib, json, tomllib-free)
- `codebook-lsp` — on `PATH`, or auto-found in `~/.local/share/zed/extensions/work/
  codebook/codebook-lsp-v*/` (shipped by the Zed codebook extension; override with
  `--codebook-lsp`)
- One package manager for stage 2: `pacman` | `dnf` | `apt` | `zypper` (`--pm`)
- Optional: an ollama server for stage 3 (`--base-url`, default `127.0.0.1:11434`)

## Usage

```sh
# dry run on files / directories / a whole git repo
python3 codebook_harvest.py harvest ~/Projects/foo

# actually write validated words to the global dictionary (~/.config/codebook/codebook.toml)
python3 codebook_harvest.py harvest --apply ~/Projects/foo

# skip stages
python3 codebook_harvest.py harvest --skip-llm ~/Projects/foo/src
python3 codebook_harvest.py harvest --skip-pkg --model llama3 file.py

# benchmark LLM models on the labeled corpus (39 terms from archinstaller/script.py)
python3 codebook_harvest.py benchmark --models granite4.2:3b ornith-1.5:9b lfm2.5:8b
```

Key options (`harvest`): `--pm`, `--skip-pkg`, `--skip-llm`, `--provider ollama`,
`--base-url`, `--model`, `--batch-size N` (N terms per LLM call; 1 = serial),
`--think`, `--timeout` (per-call LLM deadline, default 300 s), `--apply`,
`--codebook-lsp`.

Output: the **packages set** (+ matched **full tokens**), the **possessives**
(`token -> stem`, both added), the **llm_validated set** and the **remainder**
(unclassified — candidates for manual review; a real typo stays here, so it never
silences future warnings). The remainder block prints a ready-to-paste
`codebook-lsp add -g …` line with those words (apostrophe tokens double-quoted) —
trim the invalid ones before running it.

## Caching

Everything is batched at DB-read level; per-term lookups are O(1) set membership.

| data | source | cache | TTL |
|---|---|---|---|
| package names | one subshell per list (`pacman -Slq` + `-Qq`, `apt-cache pkgnames`, `rpm -qa`, …) | `~/.cache/codebook-harvest/{pm}-names.json` | 24 h |
| installed path components | `pacman -Qlq` (~1M paths) split on `- / . _ space` | `~/.cache/codebook-harvest/{pm}-components.json` | 24 h |
| LLM dictionary state | ollama `keep_alive` | — | 30 min |

Delete the JSON files to force a refresh.

## Dictionary synchronization (`sync_spell_dictionaries.py`)

Keeps the Codebook and IntelliJ spell-checker dictionaries consistent — both files are
rewritten with the merged word set:

- Codebook global dictionary: `~/.config/codebook/codebook.toml` (`words = [...]`,
  sorted case-insensitively)
- IntelliJ cached dictionary: `~/Documents/Private/utils/pycharm/spellchecker-dictionary.xml`
  (`<application><component name="CachedDictionaryState"><words><w>…`, sorted like the
  IDE: ordinal, uppercase first, non-ASCII last)

```sh
python3 sync_spell_dictionaries.py                     # defaults, prints per-file delta
python3 sync_spell_dictionaries.py --zed-dict a.toml --intellij-dict b.xml
```

Deduplication is case-insensitive (both checkers match case-insensitively); when the
same word exists in several casings the all-lowercase record is kept. Only the
`words` array is rewritten in the TOML — any other keys (`dictionaries`, …), comments
and layout are preserved. Writes are atomic (same-dir tmp + rename) and skipped
entirely when content is identical (idempotent). Caveat: IntelliJ rewrites the XML
from its in-memory cache on exit — run the sync while the IDE is closed. The Codebook
side hot-reloads the TOML.

## LLM benchmark (2026-10-08, 39 labeled terms, ollama on an AMD APU)

Winner: **granite4.2:3b, serial, thinking off** — 82 % accuracy, ~0.4 s/call warm,
0 parse failures; it catches real typos (`imagesdparm`) at the cost of passing two
harmless artifacts (`ipv`, `xef`). Full matrix (JSON: `~/.cache/codebook-harvest/
benchmark.json`):

| model | mode | think | latency/call | accuracy | notes |
|---|---|---|---|---|---|
| granite4.2:3b | serial | off | 0.4 s | 32/39 | **default** |
| granite4.2:3b | serial | on | 129 s | 30/39 | 2 timeouts |
| granite4.2:3b | batch10 | off | 2.5 s | 6/39 | returns 5–11 bits for 10 terms |
| ornith-1.5:9b | serial | off | 8.5 s | 31/39 | inverse errors: catches fragments, misses the typo |
| ornith-1.5:9b | serial | on | 146 s | 30/39 | 6 timeouts |
| ornith-1.5:9b | batch10 | any | — | 0 | answers 1 bit for the whole batch |
| lfm2.5:8b | serial | off/on | 42/59 s | 19/15 per 39 | forced thinker (~4 tok/s), poor judgment |

Lessons encoded in the defaults:

- **Batching is unreliable for every tested model** (verdict-count errors), so the
  default is serial; strict bit-count validation makes any malformed batch degrade to
  the remainder, never into the dictionary.
- **Thinking hurts**: slightly worse accuracy at 100–300× the latency; batch+thinking
  is 100 % timeouts at the 5-minute deadline.
- `lfm2.5:8b` is a hybrid thinker: it emits `<think>` even with `think:false`; the
  client strips such blocks and needs `num_predict` headroom (512+) or answers are
  truncated into parse failures.

## Benchmark corpus

`benchmark` uses 39 terms hand-labeled from `archinstaller/script.py`: 35 valid
(pacman packages, split name-parts like `vkd`/`tpd`, KDE config names, English words,
concatenated terms like `silverlightbottompanel`) and 4 invalid:
`euo` (`set -euo` flag cluster), `xef` (hex `0xef` fragment), `ipv` (ipv4/6 fragment),
`imagesdparm` (real typo — `sdl_imagesdparm` is not a package).
