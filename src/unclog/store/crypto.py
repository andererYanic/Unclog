"""Encryption at rest for raw client uploads (brief §14).

One key per client, never in the repo or in prompts. Resolution order:
1. environment variable ``UNCLOG_KEY_<CLIENT_ID>`` (upper-case, non-alphanumerics -> ``_``)
2. key file ``$UNCLOG_KEYS_DIR/<client_id>.key`` (mode 0600, outside the repository)

With ``UNCLOG_REQUIRE_ENCRYPTION=1`` a missing key is an error instead of a plaintext fallback.
Derived sources are PII-scrubbed at ingestion; raw files are the sensitive originals.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


class EncryptionRequired(RuntimeError):
    pass


def _env_name(client_id: str) -> str:
    return "UNCLOG_KEY_" + re.sub(r"[^A-Za-z0-9]", "_", client_id).upper()


def client_key(client_id: str) -> bytes | None:
    if v := os.environ.get(_env_name(client_id)):
        return v.encode()
    keys_dir = os.environ.get("UNCLOG_KEYS_DIR")
    if keys_dir:
        p = Path(keys_dir) / f"{client_id}.key"
        if p.exists():
            return p.read_bytes().strip()
    return None


def required() -> bool:
    return os.environ.get("UNCLOG_REQUIRE_ENCRYPTION", "") in ("1", "true", "yes")


def generate_key_file(client_id: str, keys_dir: str | Path) -> Path:
    """Create a new key file (0600). The key itself is never printed."""
    from cryptography.fernet import Fernet

    d = Path(keys_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{client_id}.key"
    if p.exists():
        raise FileExistsError(f"{p} exists; refusing to overwrite a client key")
    p.write_bytes(Fernet.generate_key())
    p.chmod(0o600)
    return p


def encrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(key).encrypt(data)


def decrypt(token: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(key).decrypt(token)
