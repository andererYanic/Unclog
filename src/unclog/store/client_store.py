from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..ingestion.models import IngestResult
from ..schemas import ENTITIES
from ..schemas.common import UnclogModel

M = TypeVar("M", bound=UnclogModel)

_SAFE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


class OwnershipError(PermissionError):
    """An agent tried to overwrite another agent's artifact."""


def _safe(name: str, what: str) -> str:
    if not _SAFE.match(name) or name in {".", ".."} or ".." in name:
        raise ValueError(f"unsafe {what}: {name!r}")
    return name.replace(":", "_")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ArtifactEnvelope(BaseModel):
    entity: str
    id: str
    version: int
    produced_by: str
    created: str
    data: dict[str, Any]


class ClientStore:
    def __init__(self, root: str | Path, client_id: str) -> None:
        self.client_id = _safe(client_id, "client id")
        self.root = Path(root).resolve() / self.client_id
        for sub in ("raw", "sources", "artifacts"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---- audit -----------------------------------------------------------------------------
    def _audit(self, action: str, actor: str, **detail: Any) -> None:
        rec = {"ts": _now(), "client": self.client_id, "actor": actor, "action": action, **detail}
        with (self.root / "audit.jsonl").open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def audit_log(self) -> list[dict[str, Any]]:
        p = self.root / "audit.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    # ---- raw uploads -----------------------------------------------------------------------
    def put_raw(self, data: bytes, sha256: str, filename: str, actor: str) -> Path:
        """Store the original upload, encrypted when a client key exists (brief §14)."""
        from .crypto import EncryptionRequired, client_key, encrypt, required

        ext = Path(filename).suffix.lower()
        key = client_key(self.client_id)
        if key is None and required():
            raise EncryptionRequired(f"no encryption key for client {self.client_id}")
        name = f"{_safe(sha256, 'hash')}{ext}" + (".enc" if key else "")
        path = self.root / "raw" / name
        if not path.exists():
            path.write_bytes(encrypt(data, key) if key else data)
            path.chmod(0o440)
        self._audit(
            "put_raw", actor, sha256=sha256, filename=Path(filename).name, encrypted=key is not None
        )
        return path

    def get_raw(self, sha256: str, ext: str, actor: str) -> bytes:
        from .crypto import client_key, decrypt

        base = self.root / "raw" / f"{_safe(sha256, 'hash')}{ext.lower()}"
        enc = base.with_name(base.name + ".enc")
        self._audit("read_raw", actor, sha256=sha256)
        if enc.exists():
            key = client_key(self.client_id)
            if key is None:
                raise PermissionError(f"raw file is encrypted; key for {self.client_id} missing")
            return decrypt(enc.read_bytes(), key)
        return base.read_bytes()

    # ---- sources ---------------------------------------------------------------------------
    def put_source(self, result: IngestResult, actor: str) -> bool:
        """Store an ingest result. Returns False if the same content was already ingested."""
        path = self.root / "sources" / f"{_safe(result.source.id, 'source id')}.json"
        existed = path.exists()
        if not existed:
            path.write_text(result.model_dump_json(indent=2))
        self._audit("put_source", actor, source_id=result.source.id, duplicate=existed)
        return not existed

    def get_source(self, source_id: str, actor: str = "system") -> IngestResult:
        path = self.root / "sources" / f"{_safe(source_id, 'source id')}.json"
        self._audit("read_source", actor, source_id=source_id)  # data access is audited (§14)
        return IngestResult.model_validate_json(path.read_text())

    def list_sources(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "sources").glob("*.json"))

    # ---- artifacts -------------------------------------------------------------------------
    def _dir(self, entity: str, artifact_id: str) -> Path:
        return self.root / "artifacts" / _safe(entity, "entity") / _safe(artifact_id, "id")

    def put(self, model: UnclogModel, produced_by: str, artifact_id: str | None = None) -> int:
        """Validate and store a new version. Returns the version number."""
        entity = type(model).__name__
        if entity not in ENTITIES:
            raise TypeError(f"{entity} is not a registered core entity")
        model = type(model).model_validate(model.model_dump())  # re-validate (G1)
        aid = artifact_id or getattr(model, "id", None)
        if not aid:
            raise ValueError(f"{entity} has no id; pass artifact_id")
        d = self._dir(entity, aid)
        d.mkdir(parents=True, exist_ok=True)
        versions = sorted(d.glob("v*.json"))
        if versions:
            first = ArtifactEnvelope.model_validate_json(versions[0].read_text())
            if first.produced_by != produced_by:
                raise OwnershipError(
                    f"{entity}/{aid} is owned by {first.produced_by!r}; {produced_by!r} must "
                    "produce its own artifact instead of overwriting"
                )
        version = len(versions) + 1
        env = ArtifactEnvelope(
            entity=entity,
            id=aid,
            version=version,
            produced_by=produced_by,
            created=_now(),
            data=model.model_dump(mode="json"),
        )
        (d / f"v{version:04d}.json").write_text(env.model_dump_json(indent=2))
        self._audit("put", produced_by, entity=entity, id=aid, version=version)
        return version

    def get(self, model_type: type[M], artifact_id: str, version: int | None = None) -> M:
        d = self._dir(model_type.__name__, artifact_id)
        versions = sorted(d.glob("v*.json"))
        if not versions:
            raise KeyError(f"{model_type.__name__}/{artifact_id} not found")
        path = versions[-1] if version is None else d / f"v{version:04d}.json"
        env = ArtifactEnvelope.model_validate_json(path.read_text())
        return model_type.model_validate(env.data)

    def history(self, model_type: type[UnclogModel], artifact_id: str) -> list[ArtifactEnvelope]:
        d = self._dir(model_type.__name__, artifact_id)
        return [
            ArtifactEnvelope.model_validate_json(p.read_text()) for p in sorted(d.glob("v*.json"))
        ]

    def list(self, model_type: type[M]) -> list[M]:
        base = self.root / "artifacts" / model_type.__name__
        if not base.exists():
            return []
        return [self.get(model_type, d.name) for d in sorted(base.iterdir()) if d.is_dir()]


def delete_client(root: str | Path, client_id: str, actor: str) -> None:
    """Remove every raw upload, derived artifact and index for a client (brief §14).

    A tombstone line goes to ``<root>/deletions.jsonl`` so the deletion itself is auditable
    without keeping any client content.
    """
    cid = _safe(client_id, "client id")
    target = Path(root).resolve() / cid
    if target.exists():
        for p in target.rglob("*"):
            if p.is_file():
                p.chmod(0o640)
        shutil.rmtree(target)
    with (Path(root) / "deletions.jsonl").open("a") as f:
        f.write(json.dumps({"ts": _now(), "client": cid, "actor": actor}) + "\n")
