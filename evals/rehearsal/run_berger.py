"""Dress rehearsal: run the real workflow on the fictional Schreinerei Berger.

AI steps use the fixed answers in berger/scripted_answers.json (no API key yet); everything
else (ingestion, quote verification, flow, constraint tests, simulation, value model, gates,
German report) runs for real. Output: evals/rehearsal/berger/output/
    python evals/rehearsal/run_berger.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from unclog import cli
from unclog.evals.cases import load_case
from unclog.llm import LLMClient
from unclog.llm.backends import FakeBackend
from unclog.orchestrator import run_pipeline
from unclog.schemas import Opportunity
from unclog.scoring.value import CostInputs, Economics, Effect, OpportunityInput, SimSettings
from unclog.simulation import compare, standard_scenarios, to_markdown
from unclog.store import ClientStore

HERE = Path(__file__).parent / "berger"
WORK = HERE / "work"
OUT = HERE / "output"
CLIENT = "berger"


def step(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    root = str(WORK / "clients")
    answers = json.loads((HERE / "scripted_answers.json").read_text())

    step("1 ingest uploads")
    cli.main(["--clients-root", root, "ingest", CLIENT, str(HERE / "uploads")])
    store = ClientStore(root, CLIENT)
    by_title = {store.get_source(s).source.title: s for s in store.list_sources()}

    step("2 call plan for the follow-up call (German)")
    from unclog.agents import build_call_plan

    (OUT / "00-gespraechsleitfaden.md").write_text(build_call_plan("de").to_markdown())

    step("3 extract the first call (scripted model answer, real quote verification)")
    cli.make_llm = lambda budget=None, **kw: LLMClient(  # scripted, no API key
        FakeBackend([json.dumps(answers["extraction"])])
    )
    cli.main(
        [
            "--clients-root",
            root,
            "extract-call",
            CLIENT,
            by_title["erstgespraech.vtt"],
            "--lang",
            "de",
        ]
    )
    sheet = next((store.root / "reviews").glob("*-extraction.md"))
    shutil.copy(sheet, OUT / "00-auswertung-erstgespraech.md")

    step("4 measured flow from the order history")
    cli.main(
        [
            "--clients-root",
            root,
            "flow-from-log",
            CLIENT,
            by_title["auftragsverlauf.csv"],
            "--domain",
            "RACE-C",
            "--save",
        ]
    )
    from unclog.orchestrator.assemble import flow_dir

    (flow_dir(store) / "manual.json").write_text((HERE / "manual_fragment.json").read_text())

    step("5 assemble the case")
    cli.main(
        [
            "--clients-root",
            root,
            "assemble-case",
            CLIENT,
            "--title",
            "Schreinerei Holzwerk Berger GmbH",
            "--kind",
            "mixed",
        ]
    )
    case = load_case(store.root / "case")

    step("6 pipeline with scripted goal tree + opportunity design, value model")
    fake = FakeBackend([json.dumps(answers["tree"]), json.dumps(answers["analyst"])])
    econ = Economics(throughput_per_unit=6000, inventory_value_per_unit=1500, hourly_cost=55)
    placeholder = Opportunity(  # identity only; the pipeline's own record is used for gates
        id="opp-a3",
        title="Aufmaß-Vorlage",
        ai_role="assist",
        position="upstream",
        focus_step="exploit",
        constraint_id="tbd",
        constraint_link="protects",
        proven=True,
        proof_refs=["lib:constraint-prestaging"],
        process_health_ok=True,
        release_gate_required=True,
        release_gate_design="eine je Termin",
        client_owner="Büroleitung",
        assumption=True,
        confidence=0.6,
    )
    effects = [
        OpportunityInput(
            placeholder,
            (
                Effect(
                    "service",
                    "log-aufmass",
                    0.10,
                    0.15,
                    0.25,
                    note="vorbereitete Vorlage verkürzt das Aufmaß",
                ),
            ),
            CostInputs(
                build_cost=4000,
                monthly_license=40,
                inference_cost_per_item=0.10,
                items_per_week=9,
                review_h_per_week=0.75,
            ),
        )
    ]
    # The non-AI move is valued the same way: the workshop lead adds ~9 h/week of measuring
    # capacity at the constraint (he has slack: the workshop is not full).
    markus = placeholder.model_copy(
        update={
            "id": "act-a1",
            "title": "Werkstattleiter übernimmt Aufmaße",
            "ai_role": "none",
            "position": "at_constraint",
            "constraint_link": "acts_on",
            "proof_refs": ["toc:exploit"],
            "release_gate_required": False,
            "release_gate_design": None,
            "client_owner": "Inhaber",
        }
    )
    effects.append(
        OpportunityInput(
            markus,
            (
                Effect(
                    "capacity",
                    "inhaber",
                    0.30,
                    0.50,
                    0.60,
                    note="Markus übernimmt einen Teil der Aufmaße",
                ),
            ),
            CostInputs(build_cost=1500),
        )
    )
    run = run_pipeline(
        case,
        lang="de",
        llm_factory=lambda: LLMClient(fake),
        store=store,
        out_dir=OUT,
        effects=effects,
        economics=econ,
        sims=SimSettings(replications=16, horizon_weeks=24),
    )
    print(f"status: {run.status} — {run.reason}")
    for h in run.human_review:
        print(f"human review: {h}")

    step("7 what-if: Google ads (+30% enquiries) vs. relieving the Aufmaß")
    g = case.graph()
    b = run.state.report.binding
    res = compare(
        g, standard_scenarios(g, b.resource_id if b else None), replications=6, horizon_weeks=20
    )
    (OUT / "09-simulation.md").write_text("> ENTWURF\n\n" + to_markdown(res) + "\n")

    step("summary")
    print("binding:", b.id if b else None, "|", b.description if b else "")
    fails = [
        f"{r.gate}: {'; '.join(r.problems[:2])}" for r in run.gates["report"] if r.status == "fail"
    ]
    print("gate failures:", fails or "none")
    print("outputs:", ", ".join(sorted(p.name for p in OUT.iterdir())))
    return 0 if run.status == "awaiting_review" else 1


if __name__ == "__main__":
    sys.exit(main())
