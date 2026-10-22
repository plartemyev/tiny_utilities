"""Renders install_steps() + post_boot_steps() to a markdown workbook.

The workbook is the copy-paste-friendly, explained form of the install for
one-off experiments on a server: every step the installer would execute,
with its rationale and the commands in fenced blocks.
"""
from __future__ import annotations

import dataclasses
import textwrap
from dataclasses import dataclass, field
from datetime import datetime

from archinstaller.i18n import tr
from archinstaller.steps import (
    CHROOT,
    POST_BOOT,
    InstallConfig,
    Step,
    install_steps,
    post_boot_steps,
)

__all__ = ["build_workbook"]

_CAUTION = (
    "> **Caution — live credentials.** This workbook embeds real passwords"
    " ({which}). Treat the file as a secret: it was written with mode 0600 —"
    " do not commit, share or paste it. Rotate the passwords once convenient"
    " after use."
)

_CHROOT_NOTE = (
    "> Everything below runs **inside the new system**. Enter it once with"
    " `arch-chroot /mnt/new-root`, then continue with the numbered sections."
)

_POST_BOOT_NOTE = (
    "> After the install finishes, reboot, then log in over SSH as `{user}`"
    " (public-key only). Root-level commands below are prefixed with `sudo`"
    " (passwordless for `{user}`)."
)


@dataclass
class _Section:
    title: str
    rationale: str
    commands: list[str] = field(default_factory=list)
    # continuation steps that belong under the section render as their own
    # fence, after the section's main one
    extra: list[list[str]] = field(default_factory=list)


def build_workbook(cfg: InstallConfig, *, passwords_embedded: bool = False,
                   provision: str | None = None, language: str = "en") -> str:
    steps = install_steps(cfg)
    steps += post_boot_steps(cfg.username, cfg.hostname, cfg.timezone,
                             cfg.opencode, cfg.opencode_password)
    steps = [_translated(step, language) for step in steps]
    blocks: list[str] = [
        tr(language, f"# archinstaller workbook — {cfg.hostname}"),
        "",
        tr(language, _facts_line(cfg)),
        "",
    ]
    if passwords_embedded:
        blocks += [tr(language, _caution(cfg)), ""]
    if provision is not None:
        # a provisioned run has no unknown target: the VM's virt kind and
        # discard support are decided by --provision, so the target-facts
        # step is replaced by the provisioning and boot sections
        blocks += [provision, ""]
    else:
        blocks += _target_facts_section(cfg, language)

    state = _RenderState(blocks, cfg, language)
    for step in steps:
        state.add(step)
    state.flush()

    return "\n".join(blocks).rstrip("\n") + "\n"


def _translated(step: Step, language: str) -> Step:
    """Workbook-side translation of a step's prose.

    Applied here, never in steps.py: the same title doubles as the
    install script's `log` line, which stays English for every language.
    """
    if language == "en":
        return step
    return dataclasses.replace(
        step,
        title=tr(language, step.title) if step.title else None,
        rationale=tr(language, step.rationale),
    )


class _RenderState:
    """Sections steps into numbered workbook headings, in order."""

    def __init__(self, blocks: list[str], cfg: InstallConfig,
                 language: str = "en") -> None:
        self._blocks = blocks
        self._cfg = cfg
        self._language = language
        self._context: str | None = None
        self._current: _Section | None = None
        self._pending: list[str] = []  # continuation before any titled step
        self._number = 0

    def add(self, step: Step) -> None:
        if step.context != self._context:
            self.flush()
            self._pending = []
            self._context = step.context
            if self._context == CHROOT:
                self._blocks += [tr(self._language, _CHROOT_NOTE), ""]
            elif self._context == POST_BOOT:
                self._blocks += [tr(self._language,
                                    _POST_BOOT_NOTE.format(user=self._cfg.username)), ""]
        if step.title:
            self.flush()
            self._current = _Section(step.title, step.rationale)
            self._current.commands.extend(self._pending)
            self._pending = []
            self._current.commands.extend(_lines(step))
        elif step.commands:
            lines = _lines(step)
            if self._current is None:
                self._pending.extend(lines)
            else:
                self._current.extra.append(lines)

    def flush(self) -> None:
        if self._current is None:
            return
        section, self._current = self._current, None
        self._number += 1
        self._blocks += [f"## {self._number}. {section.title}", ""]
        if section.rationale:
            self._blocks += [_wrap(section.rationale), ""]
        self._blocks += [_fence(section.commands), ""]
        for extra in section.extra:
            self._blocks += [_fence(extra), ""]


def _lines(step: Step) -> list[str]:
    lines: list[str] = []
    for command in step.commands:
        # the workbook ships no helper definitions, so the install script's
        # retry wrapper (3 attempts, 5 s apart) is unwrapped here: rerun a
        # failed block manually instead
        command = command.removeprefix("retry ")
        if step.context == POST_BOOT and step.root:
            command = f"sudo {command}"
        lines.extend(command.split("\n"))
    return lines


def _facts_line(cfg: InstallConfig) -> str:
    facts = [
        f"disk={cfg.disk}",
        f"virt={cfg.virt}",
        f"discard={'on' if cfg.discard else 'off'}",
        f"graphical={'yes' if cfg.graphical else 'no'}",
        f"devel={'yes' if cfg.devel else 'no'}",
        f"locale={cfg.locale}",
        f"swap={cfg.swap_size}",
        f"username={cfg.username}",
        f"timezone={cfg.timezone}",
    ]
    if cfg.local_mirror is not None:
        facts.append(f"local mirror={cfg.local_mirror}")
    if cfg.opencode:
        facts.append("opencode=yes")
    date = datetime.now().astimezone().date().isoformat()
    return f"Rendered {date} with: {', '.join(facts)}."


def _caution(cfg: InstallConfig) -> str:
    which = "root, user"
    if cfg.opencode:
        which += ", opencode"
    return _CAUTION.format(which=which)


def _target_facts_section(cfg: InstallConfig, language: str = "en") -> list[str]:
    dev = cfg.disk.rsplit("/", 1)[-1]
    probes = [
        "test -d /sys/firmware/efi && echo 'UEFI: ok'",
        "systemd-detect-virt",
        f"cat /sys/block/{dev}/queue/rotational /sys/block/{dev}/queue/discard_max_bytes",
        "timeout 15 getent hosts archlinux.org >/dev/null && echo 'DNS: ok'",
    ]
    if cfg.local_mirror is not None:
        probes.append(f"curl -fsS --max-time 8 {cfg.local_mirror}/healthz"
                      " && echo 'mirror: ok'")
    return [
        tr(language, "## 0. Target facts"),
        "",
        _wrap(tr(language, "The blocks below were rendered for the facts listed in the"
                      " header. Verify them on the target first.")),
        "",
        _fence(probes),
        "",
        _wrap(tr(language, "If systemd-detect-virt or discard_max_bytes disagree with the"
                      " rendered values, re-render the workbook with matching"
                      " `--virt` / `--discard` flags.")),
        "",
    ]


def _fence(commands: list[str]) -> str:
    return "```bash\n" + "\n".join(commands) + "\n```"


def _wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=78))
