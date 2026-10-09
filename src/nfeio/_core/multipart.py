"""``multipart/form-data`` encoder without dependencies (RFC 7578)."""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass

_UNSAFE_FILENAME_RE = re.compile(r'[^\x20-\x7e]|["\\]')
_FIELD_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]{1,64}")


@dataclass(frozen=True)
class FilePart:
    name: str
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


def sanitize_filename(filename: str) -> str:
    """Drop quotes, backslashes, CR/LF and any non-printable/non-ASCII character."""
    cleaned = _UNSAFE_FILENAME_RE.sub("_", filename).strip() or "file"
    return cleaned[:255]


def encode(fields: Sequence[tuple[str, str]], files: Sequence[FilePart]) -> tuple[bytes, str]:
    """Return ``(body, content_type)``. The boundary is 128 random bits."""
    for name in [n for n, _ in fields] + [f.name for f in files]:
        if not _FIELD_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid multipart field name {name!r}")
    while True:
        boundary = "nfeio-" + secrets.token_hex(16)
        marker = boundary.encode("ascii")
        if all(marker not in f.content for f in files) and all(
            boundary not in v for _, v in fields
        ):
            break
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields:
        parts += [
            b"--" + marker,
            f'Content-Disposition: form-data; name="{name}"'.encode("ascii"),
            b"",
            value.encode("utf-8"),
        ]
    for part in files:
        parts += [
            b"--" + marker,
            (
                f'Content-Disposition: form-data; name="{part.name}"; '
                f'filename="{sanitize_filename(part.filename)}"'
            ).encode("ascii"),
            f"Content-Type: {part.content_type}".encode("ascii"),
            b"",
            part.content,
        ]
    parts += [b"--" + marker + b"--", b""]
    return crlf.join(parts), f"multipart/form-data; boundary={boundary}"
