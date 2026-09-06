from __future__ import annotations

import base64
import binascii
import os

KEY_TYPES = (
    "ssh-ed25519",
    "sk-ssh-ed25519@openssh.com",
    "ssh-rsa",
    "ssh-dss",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)


def resolve_public_key(value: str) -> str:
    """Return a normalized ssh public key from a literal key string or a file path."""
    value = value.strip()
    if _is_key_line(value):
        return _validated(value)
    path = os.path.expanduser(value)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if _is_key_line(line):
                    return _validated(line)
        raise ValueError(f"no valid ssh public key found in {value}")
    raise ValueError(f"{value!r} is neither an ssh public key nor an existing file")


def _is_key_line(line: str) -> bool:
    fields = line.split()
    return len(fields) >= 2 and fields[0] in KEY_TYPES


def _validated(line: str) -> str:
    fields = line.split()
    try:
        base64.b64decode(fields[1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"malformed ssh public key: {exc}") from exc
    return " ".join(fields)
