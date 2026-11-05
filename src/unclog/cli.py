"""Command line for the Unclog pipeline. Run ``unclog --help`` for commands."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .connectors import FileDropConnector, pull
from .store import ClientStore


def _root(args: argparse.Namespace) -> str:
    return args.clients_root or os.environ.get("UNCLOG_CLIENTS_ROOT", "clients")


def cmd_ingest(args: argparse.Namespace) -> int:
    store = ClientStore(_root(args), args.client_id)
    report = pull(
        FileDropConnector(args.folder, scrub_pii=not args.no_scrub), store, actor=args.actor
    )
    print(json.dumps(report.model_dump(), indent=2))
    return 1 if report.failed else 0


def cmd_sources(args: argparse.Namespace) -> int:
    store = ClientStore(_root(args), args.client_id)
    for sid in store.list_sources():
        r = store.get_source(sid)
        print(
            f"{sid}  {r.source.kind:<10} {r.source.title}  tables={len(r.tables)} "
            f"chunks={len(r.chunks)} event_logs={len(r.event_logs)} pii={r.pii_redactions}"
        )
    return 0


def make_llm(budget_usd: float | None = None):
    """Default model client: Anthropic backend, disk cache, per-run budget. Patched in tests."""
    from .llm import CostTracker, LLMClient
    from .llm.backends import AnthropicBackend
    from .llm.cache import DiskCache

    return LLMClient(
        AnthropicBackend(),
        cost=CostTracker(budget_usd=budget_usd),
        cache=DiskCache(os.environ.get("UNCLOG_LLM_CACHE", ".unclog-cache")),
    )


def cmd_call_plan(args: argparse.Namespace) -> int:
    from .agents import build_call_plan

    heat = report = None
    if args.case:
        from .evals.cases import load_case
        from .evals.runner import run_case

        res = run_case(load_case(args.case))
        heat, report = res.heat, res.report
    print(build_call_plan(args.lang, heat, report).to_markdown())
    return 0


def cmd_extract_call(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .agents.transcript_extractor import extract_call, review_markdown

    store = ClientStore(_root(args), args.client_id)
    src = store.get_source(args.source_id)
    llm = make_llm(args.budget)
    run = extract_call(llm, src.chunks, src.source.id, lang=args.lang)
    v = run.result
    for m in v.metrics:
        store.put(m, produced_by="transcript_extractor")
    for p in v.policies:
        store.put(p, produced_by="transcript_extractor")
    out = Path(store.root) / "reviews"
    out.mkdir(exist_ok=True)
    sheet = out / f"{src.source.id}-extraction.md"
    sheet.write_text(review_markdown(v, args.lang))
    (out / f"{src.source.id}-extraction.json").write_text(v.extraction.model_dump_json(indent=2))
    print(
        f"{len(v.metrics)} numbers, {len(v.steps)} steps, {len(v.policies)} rules, "
        f"{len(v.rejected)} rejected, {len(v.number_flags)} to check; prompt "
        f"v{run.prompt_version}, {run.attempts} attempt(s), ${run.cost_usd:.4f}"
    )
    print(f"review sheet: {sheet}")
    return 0


def cmd_flow_from_log(args: argparse.Namespace) -> int:
    from .flow.from_eventlog import flow_from_event_log

    store = ClientStore(_root(args), args.client_id)
    src = store.get_source(args.source_id)
    if not src.event_logs:
        print(f"{args.source_id}: no event log detected")
        return 1
    nodes, edges = flow_from_event_log(src.event_logs[0], args.domain, src.source.id)
    p = {(e.source, e.target): e.probability for e in edges}
    for i, n in enumerate(nodes):
        nxt = nodes[i + 1].id if i + 1 < len(nodes) else None
        wait = f"wait {n.wait_time_h:.0f} h" if n.wait_time_h is not None else ""
        queue = f"queue {n.queue_length:g}" if n.queue_length else ""
        share = f"-> {p[(n.id, nxt)]:.0%}" if nxt else ""
        print(f"{n.id:<36} {wait:<14} {queue:<10} {share}")
    return 0


def cmd_eval_cases(args: argparse.Namespace) -> int:
    from .evals.runner import MAX_RACE_BACKEND_GAP, run_all

    summary = run_all(args.root)
    print(summary.to_text())
    gap = summary.race_backend_gap
    ok = all(r.passed for r in summary.results) and (gap is None or gap <= MAX_RACE_BACKEND_GAP)
    return 0 if ok else 1


def cmd_simulate(args: argparse.Namespace) -> int:
    from .evals.cases import load_case
    from .simulation import compare, standard_scenarios, to_markdown

    case = load_case(args.case_dir)
    graph = case.graph()
    if graph is None:
        print(f"{case.id}: no flow graph to simulate")
        return 1
    constraint = args.constraint or (b.resource_id if (b := graph.bottleneck()) else None)
    scenarios = standard_scenarios(
        graph,
        constraint_resource=constraint,
        gate_node=args.gate,
        batch_node=args.batch_node,
        demand_factor=args.demand,
    )
    print(
        to_markdown(
            compare(
                graph,
                scenarios,
                replications=args.replications,
                horizon_weeks=args.weeks,
                seed=args.seed,
            )
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="unclog")
    p.add_argument("--clients-root", help="default: $UNCLOG_CLIENTS_ROOT or ./clients")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="ingest a folder of client uploads")
    pi.add_argument("client_id")
    pi.add_argument("folder")
    pi.add_argument("--actor", default=os.environ.get("USER", "cli"))
    pi.add_argument("--no-scrub", action="store_true", help="disable PII scrubbing (not advised)")
    pi.set_defaults(fn=cmd_ingest)

    ps = sub.add_parser("sources", help="list ingested sources for a client")
    ps.add_argument("client_id")
    ps.set_defaults(fn=cmd_sources)

    pe = sub.add_parser("eval-cases", help="run synthetic cases and score diagnosis accuracy")
    pe.add_argument("root", nargs="?", default="evals/cases")
    pe.set_defaults(fn=cmd_eval_cases)

    pc = sub.add_parser("call-plan", help="bilingual first-call plan for the consultant")
    pc.add_argument("--lang", choices=["de", "en"], default="de")
    pc.add_argument("--case", help="synthetic case dir to tailor follow-ups (else full script)")
    pc.set_defaults(fn=cmd_call_plan)

    px = sub.add_parser("extract-call", help="extract verified facts from an ingested transcript")
    px.add_argument("client_id")
    px.add_argument("source_id")
    px.add_argument("--lang", choices=["de", "en"], default="de")
    px.add_argument("--budget", type=float, default=2.0, help="max USD for this run")
    px.set_defaults(fn=cmd_extract_call)

    pf = sub.add_parser("flow-from-log", help="measured flow fragment from an ingested event log")
    pf.add_argument("client_id")
    pf.add_argument("source_id")
    pf.add_argument("--domain", required=True)
    pf.set_defaults(fn=cmd_flow_from_log)

    pm = sub.add_parser("simulate", help="run the standard what-if scenarios on a case")
    pm.add_argument("case_dir")
    pm.add_argument("--constraint", help="resource to elevate (default: busiest)")
    pm.add_argument("--gate", help="node for the rope / release gate")
    pm.add_argument("--batch-node", help="node whose batching to remove (exploit)")
    pm.add_argument("--demand", type=float, default=1.3, help="demand factor for what-ifs")
    pm.add_argument("--replications", type=int, default=10)
    pm.add_argument("--weeks", type=float, default=26)
    pm.add_argument("--seed", type=int, default=42)
    pm.set_defaults(fn=cmd_simulate)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
