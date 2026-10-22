"""Renders install_steps() to the bash install script uploaded to the target."""
from __future__ import annotations

from archinstaller.steps import (
    CHROOT,
    InstallConfig,
    POST_CHROOT,
    Step,
    install_steps,
    shell_lines,
)

__all__ = ["InstallConfig", "build_install_script"]

_BASH_HEADER = shell_lines("bash-header.sh")
_CHROOT_PREAMBLE = shell_lines("chroot-preamble.sh")


def build_install_script(cfg: InstallConfig) -> str:
    lines = list(_BASH_HEADER)
    for step in install_steps(cfg):
        if step.context in (CHROOT, POST_CHROOT):
            continue
        _append_spaced(lines, step)
    lines.append("")  # blank between the live section and the chroot block
    lines.extend(_CHROOT_PREAMBLE)
    for step in install_steps(cfg):
        if step.context != CHROOT:
            continue
        _append_spaced(lines, step)
    lines.append("CHROOT")
    for step in install_steps(cfg):
        if step.context != POST_CHROOT:
            continue
        _append_spaced(lines, step)
    return "\n".join(lines) + "\n"


def _append_spaced(lines: list[str], step: Step) -> None:
    if not step.title and not step.commands:
        return  # empty placeholder step (e.g. the absent mirror write)
    if step.spaced:
        lines.append("")
    _append(lines, step)


def _append(lines: list[str], step: Step) -> None:
    if step.title:
        lines.append(f"log '{step.title}'")
    for command in step.commands:
        lines.extend(command.split("\n"))
