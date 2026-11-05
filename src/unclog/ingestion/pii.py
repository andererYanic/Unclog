"""PII/secret scrubbing at ingestion (brief §14).

Regex-based and conservative: it redacts what it can recognize and counts redactions. Patterns
are tuned not to eat business identifiers (order/ticket/case ids), which flow analysis needs.
This is a first line of defense, not a guarantee; regulated engagements need a reviewed policy.
"""

from __future__ import annotations

import re

_NOT_IN_ID = r"(?<![\w\-./#])"
_END = r"(?![\w\-])"

_SIMPLE: list[tuple[str, re.Pattern[str]]] = [
    ("SECRET", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b")),
    ("SECRET", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SECRET", re.compile(r"(?i)\b(?:password|passwort|api[_-]?key|secret|token)\s*[:=]\s*\S+")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    # Phones must start with +country or a trunk 0 (DE/EU style) or be (xxx) xxx-xxxx (US).
    (
        "PHONE",
        re.compile(
            _NOT_IN_ID + r"(?:\+\d{1,3}|0)[\s\-/]?\(?\d{1,5}\)?(?:[\s\-/]?\d{2,}){1,4}" + _END
        ),
    ),
    ("PHONE", re.compile(_NOT_IN_ID + r"\(\d{3}\)\s?\d{3}-\d{4}" + _END)),
]

_CARD = re.compile(_NOT_IN_ID + r"(?:\d[ \-]?){12,18}\d" + _END)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def scrub(text: str) -> tuple[str, int]:
    """Return (scrubbed_text, number_of_redactions)."""
    count = 0

    def card(m: re.Match[str]) -> str:
        nonlocal count
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            count += 1
            return "[CARD]"
        return m.group()

    text = _CARD.sub(card, text)
    for label, pattern in _SIMPLE:
        text, n = pattern.subn(f"[{label}]", text)
        count += n
    return text, count


def scrub_cell(value: object) -> tuple[object, int]:
    if isinstance(value, str):
        return scrub(value)
    return value, 0
