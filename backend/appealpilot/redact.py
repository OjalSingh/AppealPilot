"""PII redaction for anything that leaves the request path: logs, traces, eval output.

Health claims carry Aadhaar, PAN, phone numbers, emails and policy numbers. We never
log raw document text; every trace entry goes through `redact` first.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("VEHICLE_NO", re.compile(r"\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)")),
    (
        "POLICY_NO",
        re.compile(r"(?i)\b(policy|member|uhid|claim)\s*(no\.?|number|id)\s*[:#]?\s*[\w/-]{5,}"),
    ),
]


def redact(value: Any) -> Any:
    """Recursively redact strings inside dicts / lists / tuples."""
    if isinstance(value, str):
        out = value
        for label, pattern in _PATTERNS:
            out = pattern.sub(f"[{label}]", out)
        return out
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(redact(v) for v in value)
    return value


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs PII from every record's message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = redact(record.args)
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    for handler in root.handlers or [logging.StreamHandler()]:
        handler.addFilter(RedactingFilter())
    if not root.handlers:
        h = logging.StreamHandler()
        h.addFilter(RedactingFilter())
        root.addHandler(h)
