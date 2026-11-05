"""Human review: approve, request changes, comment, re-run a phase, approve go-live, release
(brief §16; build plan step 15).

Approvals are bound to the content hash of what was reviewed. If a deliverable changes after
approval (edited by hand or regenerated), the approval is stale and the package cannot be
released. Everything is appended to ``clients/<id>/reviews/review.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..build.templates import TEMPLATES
from ..deploy.package import PackageSpec, check_g15
from ..evals.harness import EvalReport, gate_g14
from ..schemas.delivery import DeployedSystem, EvalCase, EvalSuite
from ..store import ClientStore

PHASE_ORDER = ("goal_factoring", "opportunities")  # checkpointed phases, in dependency order
ACTIONS = {"approve", "request_changes", "comment", "rerun", "go_live", "release"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class FileStatus:
    name: str
    state: str  # approved | stale | changes_requested | unreviewed
    comments: int
    by: str | None = None


class Review:
    def __init__(self, store: ClientStore) -> None:
        self.store = store
        self.dir = Path(store.root) / "reviews"
        self.dir.mkdir(exist_ok=True)
        self.path = self.dir / "review.jsonl"

    # ---- log --------------------------------------------------------------------------------
    def _append(
        self,
        action: str,
        reviewer: str,
        target: str,
        note: str = "",
        digest: str | None = None,
        **extra,
    ) -> dict:
        if action not in ACTIONS:
            raise ValueError(action)
        if not reviewer or reviewer.lower() in {"agent", "system", "claude"}:
            raise PermissionError("reviews must be recorded by a named human reviewer")
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "action": action,
            "reviewer": reviewer,
            "target": target,
            "note": note,
            "sha256": digest,
            **extra,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.store._audit(f"review_{action}", reviewer, target=target, sha256=digest)
        return entry

    def entries(self, target: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
        return [r for r in rows if target is None or r["target"] == target]

    # ---- deliverables -----------------------------------------------------------------------
    def approve(self, file: Path, reviewer: str, note: str = "") -> dict:
        return self._append(
            "approve", reviewer, file.name, note, sha(file), package=str(file.parent.name)
        )

    def request_changes(self, file: Path, reviewer: str, note: str) -> dict:
        if not note.strip():
            raise ValueError("say what needs to change")
        return self._append("request_changes", reviewer, file.name, note, sha(file))

    def comment(self, target: str, reviewer: str, note: str, line: int | None = None) -> dict:
        return self._append("comment", reviewer, target, note, line=line)

    def file_status(self, file: Path) -> FileStatus:
        decisions = [
            e for e in self.entries(file.name) if e["action"] in ("approve", "request_changes")
        ]
        comments = len([e for e in self.entries(file.name) if e["action"] == "comment"])
        if not decisions:
            return FileStatus(file.name, "unreviewed", comments)
        last = decisions[-1]
        if last["action"] == "request_changes":
            return FileStatus(file.name, "changes_requested", comments, last["reviewer"])
        state = "approved" if last["sha256"] == sha(file) else "stale"
        return FileStatus(file.name, state, comments, last["reviewer"])

    def status(self, package_dir: Path) -> list[FileStatus]:
        return [
            self.file_status(p)
            for p in sorted(package_dir.iterdir())
            if p.is_file() and p.name != "RELEASE.json"
        ]

    def release(self, package_dir: Path, reviewer: str) -> Path:
        """Client-delivery release: every deliverable approved at its current content."""
        not_ok = [s for s in self.status(package_dir) if s.state != "approved"]
        if not_ok:
            raise PermissionError(
                "cannot release: " + ", ".join(f"{s.name} ({s.state})" for s in not_ok)
            )
        manifest = {
            "released_by": reviewer,
            "ts": datetime.now(UTC).isoformat(),
            "files": {
                p.name: sha(p)
                for p in sorted(package_dir.iterdir())
                if p.is_file() and p.name != "RELEASE.json"
            },
        }
        out = package_dir / "RELEASE.json"
        out.write_text(json.dumps(manifest, indent=2))
        self._append(
            "release",
            reviewer,
            package_dir.name,
            digest=hashlib.sha256(
                json.dumps(manifest["files"], sort_keys=True).encode()
            ).hexdigest(),
        )
        return out

    # ---- pipeline ---------------------------------------------------------------------------
    def rerun(self, phase: str, reviewer: str, note: str = "") -> list[str]:
        """Drop the checkpoint of ``phase`` and every checkpointed phase after it."""
        if phase not in PHASE_ORDER:
            raise ValueError(f"re-runnable phases: {PHASE_ORDER}")
        cp = Path(self.store.root) / "pipeline"
        dropped = []
        for ph in PHASE_ORDER[PHASE_ORDER.index(phase) :]:
            f = cp / f"{ph}.json"
            if f.exists():
                f.unlink()
                dropped.append(ph)
        self._append("rerun", reviewer, phase, note, dropped=dropped)
        return dropped

    # ---- go-live ----------------------------------------------------------------------------
    def go_live(
        self,
        system_id: str,
        reviewer: str,
        eval_report: Path | None,
        owner_trained: bool,
        client_accounts: bool,
        allow_live_actions: bool = False,
    ) -> tuple[DeployedSystem, list[str]]:
        """Approve a packaged system to run. External actions stay drafts unless
        ``allow_live_actions`` is set explicitly (G13)."""
        base = Path(self.store.root) / "systems" / system_id
        folder = sorted(base.glob("v*"))[-1]
        routine = json.loads((folder / "routine.json").read_text())
        tpl = TEMPLATES[routine["template"]]
        sysrec = self.store.get(DeployedSystem, system_id)
        spec = PackageSpec(
            client_id=self.store.client_id,
            system_id=system_id,
            template=tpl,
            opportunity_id=sysrec.opportunity_id,
            client_owner=sysrec.client_owner,
            environment=routine["environment"],
            config=json.loads((folder / "config.json").read_text()),
            eval_report=str(eval_report) if eval_report else None,
            owner_trained=owner_trained,
            client_owned_accounts=client_accounts,
        )
        problems = check_g15(folder, spec)
        if tpl.uses_ai:
            if eval_report is None:
                problems.append("G14: eval report required")
            else:
                rep = EvalReport.from_json(Path(eval_report).read_text())
                suite = EvalSuite(
                    id=f"suite-{system_id}",
                    system_id=system_id,
                    rubric="system",
                    pass_mean=7,
                    pass_worst_case=5,
                    cases=[EvalCase(id=c, input_ref=c) for c in rep.per_case],
                )
                problems += [f"G14: {p}" for p in gate_g14(rep, suite)]
        if problems:
            return sysrec, problems
        entry = self._append(
            "go_live",
            reviewer,
            system_id,
            f"allow_live_actions={allow_live_actions}",
            digest=sha(folder / "routine.json"),
        )
        ref = f"review:{system_id}:{reviewer}:{entry['ts']}"
        live = sysrec.model_copy(
            update={"go_live_approval_ref": ref, "draft_safe": not allow_live_actions}
        )
        live = DeployedSystem.model_validate(live.model_dump())
        self.store.put(live, produced_by="deployment_agent")  # the deploy agent applies it
        (folder / "GO_LIVE.json").write_text(
            json.dumps(
                {
                    "approved_by": reviewer,
                    "ts": entry["ts"],
                    "ref": ref,
                    "allow_live_actions": allow_live_actions,
                },
                indent=2,
            )
        )
        return live, []
