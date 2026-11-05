"""Secret scan for the repository and client packages (brief §14: secrets never in repos)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PATTERNS = {
    "anthropic/openai-style key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential assignment": re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+]{12,}"
    ),
    "fernet key": re.compile(r"\b[A-Za-z0-9_\-]{43}=(?=\s|$)"),
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "clients",
    ".unclog-cache",
    "node_modules",
}
SKIP_SUFFIX = {".pyc", ".xlsx", ".pdf", ".docx", ".png", ".jpg", ".enc"}
ALLOW = re.compile(r"secret-scan: allow")  # explicit, reviewable exception marker


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str


def scan(root: str | Path) -> list[SecretFinding]:
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if (
            not p.is_file()
            or p.suffix in SKIP_SUFFIX
            or any(part in SKIP_DIRS for part in p.relative_to(root).parts)
        ):
            continue
        if p.name in (".env",) or p.name.startswith(".env."):
            out.append(SecretFinding(str(p.relative_to(root)), 0, "env file in tree"))
            continue
        try:
            lines = p.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            if ALLOW.search(line):
                continue
            for kind, rx in PATTERNS.items():
                if rx.search(line):
                    out.append(SecretFinding(str(p.relative_to(root)), i, kind))
    return out
