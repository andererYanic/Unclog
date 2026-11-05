"""Draft outbox (G13): external actions wait here until a human approves them.

Lifecycle: pending -> approved -> executed | failed, or pending -> rejected. Every transition is
written to the client's audit log. Execution requires an approval and passes the approval
reference to the connector as a non-draft WriteAction.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..connectors.base import Connector, WriteAction, WriteResult
from ..store import ClientStore

Status = Literal["pending", "approved", "rejected", "executed", "failed"]


class OutboxItem(BaseModel):
    id: str
    system_id: str
    action: WriteAction
    status: Status = "pending"
    created: str
    approver: str | None = None
    decided: str | None = None
    reason: str | None = None
    result: dict | None = None


class Outbox:
    def __init__(self, store: ClientStore) -> None:
        self.store = store
        self.dir = Path(store.root) / "outbox"
        self.dir.mkdir(exist_ok=True)

    def _path(self, item_id: str) -> Path:
        if not item_id.replace("-", "").isalnum():
            raise ValueError(f"bad outbox id {item_id!r}")
        return self.dir / f"{item_id}.json"

    def _save(self, item: OutboxItem) -> None:
        self._path(item.id).write_text(item.model_dump_json(indent=2))

    def get(self, item_id: str) -> OutboxItem:
        return OutboxItem.model_validate_json(self._path(item_id).read_text())

    def put(self, system_id: str, action: WriteAction, actor: str) -> OutboxItem:
        if not action.draft:
            raise ValueError("outbox accepts drafts only; approval happens here (G13)")
        item = OutboxItem(
            id=f"ob-{uuid.uuid4().hex[:12]}",
            system_id=system_id,
            action=action,
            created=datetime.now(UTC).isoformat(),
        )
        self._save(item)
        self.store._audit(
            "outbox_put",
            actor,
            item=item.id,
            system=system_id,
            operation=action.operation,
            summary=action.change_summary,
        )
        return item

    def list(self, status: Status | None = None) -> list[OutboxItem]:
        items = [
            OutboxItem.model_validate_json(p.read_text())
            for p in sorted(self.dir.glob("ob-*.json"))
        ]
        return [i for i in items if status is None or i.status == status]

    def _decide(
        self, item_id: str, status: Status, approver: str, reason: str | None
    ) -> OutboxItem:
        item = self.get(item_id)
        if item.status != "pending":
            raise ValueError(f"{item_id} is {item.status}, not pending")
        item = item.model_copy(
            update={
                "status": status,
                "approver": approver,
                "reason": reason,
                "decided": datetime.now(UTC).isoformat(),
            }
        )
        self._save(item)
        self.store._audit(f"outbox_{status}", approver, item=item_id, reason=reason)
        return item

    def approve(self, item_id: str, approver: str, reason: str | None = None) -> OutboxItem:
        return self._decide(item_id, "approved", approver, reason)

    def reject(self, item_id: str, approver: str, reason: str) -> OutboxItem:
        return self._decide(item_id, "rejected", approver, reason)

    def execute(self, item_id: str, connector: Connector, actor: str) -> OutboxItem:
        item = self.get(item_id)
        if item.status != "approved":
            raise PermissionError(f"{item_id} is {item.status}: only approved items run (G13)")
        live = item.action.model_copy(
            update={
                "draft": False,
                "approval_ref": f"outbox:{item.id}:{item.approver}:{item.decided}",
            }
        )
        live = WriteAction.model_validate(live.model_dump())
        try:
            res: WriteResult = connector.write(live)
            item = item.model_copy(
                update={"status": "executed", "result": json.loads(res.model_dump_json())}
            )
        except Exception as exc:  # recorded, never silently dropped
            item = item.model_copy(
                update={"status": "failed", "result": {"error": f"{type(exc).__name__}: {exc}"}}
            )
        self._save(item)
        self.store._audit("outbox_execute", actor, item=item_id, status=item.status)
        return item
