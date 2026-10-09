"""Redaction helpers for anything that may end up in logs or reprs."""

from __future__ import annotations

#: Static path segments that may appear in logs; anything else (ids, documents, dates,
#: externalId) is replaced by ``*`` because it can identify a person or a sale.
_LOGGABLE_SEGMENTS = frozenset(
    {
        "v1", "v2", "v3", "companies", "serviceinvoices", "external", "pdf", "xml",
        "cancellation-xml", "sendemail", "certificates", "webhooks", "pings", "eventtypes",
        "legalentities", "basicInfo", "stateTaxInfo", "naturalperson", "status", "addresses",
        "blob", "download",
    }
)  # fmt: skip


def log_path(path: str) -> str:
    """Path safe for logs: keep known static segments, mask everything else."""
    return "/".join(
        segment if not segment or segment in _LOGGABLE_SEGMENTS else "*"
        for segment in path.split("/")
    )
