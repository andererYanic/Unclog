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


def make_llm(budget_usd: float | None = None, cache: bool = True, model: str | None = None):
    """Default model client: Anthropic backend, disk cache, per-run budget. Patched in tests.

    ``cache=False`` for evals (replicates must be independent samples).
    """
    from .llm import CostTracker, LLMClient
    from .llm.backends import AnthropicBackend
    from .llm.cache import DiskCache

    client = LLMClient(
        AnthropicBackend(),
        cost=CostTracker(budget_usd=budget_usd),
        cache=DiskCache(os.environ.get("UNCLOG_LLM_CACHE", ".unclog-cache")) if cache else None,
    )
    if model:
        client.default_model = model
    return client


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


def cmd_goal_tree(args: argparse.Namespace) -> int:
    from .agents.goal_factoring import factor_goal
    from .evals.cases import load_case
    from .evals.runner import run_case

    case = load_case(args.case)
    res = run_case(case)
    if res.report.binding is None:
        print("No confirmed constraint: only discovery actions are allowed (G4).")
        for a in res.report.discovery_actions:
            print(f"- {a}")
        return 1
    run = factor_goal(
        make_llm(args.budget),
        res.report.binding,
        case.graph(),
        case.metrics,
        res.report.policy_audit.policies,
        lang=args.lang,
    )
    print(run.result.to_markdown(args.lang))
    if args.mermaid:
        print("\n```mermaid\n" + run.result.to_mermaid() + "\n```")
    print(f"\nprompt v{run.prompt_version}, {run.attempts} attempt(s), ${run.cost_usd:.4f}")
    return 0


def cmd_opportunities(args: argparse.Namespace) -> int:
    from .agents.goal_factoring import factor_goal
    from .agents.opportunity_analyst import analyse_opportunities, to_markdown
    from .evals.cases import load_case
    from .evals.runner import run_case

    case = load_case(args.case)
    res = run_case(case)
    b = res.report.binding
    if b is None:
        print("No confirmed constraint: only discovery actions are allowed (G4).")
        return 1
    llm = make_llm(args.budget)
    pols = res.report.policy_audit.policies
    tree = factor_goal(llm, b, case.graph(), case.metrics, pols, lang=args.lang).result
    seeds = tree.opportunity_seeds()
    print(tree.to_markdown(args.lang))
    if not seeds:
        print("\nNo AI-doable actions on the constraint: the plan is non-AI fixes only.")
        return 0
    run = analyse_opportunities(llm, seeds, b, case.graph(), pols, lang=args.lang)
    print("\n" + to_markdown(run.result, args.lang))
    print(f"\ntotal model cost ${llm.cost.total_usd:.4f}")
    return 0


def cmd_eval_agent(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .evals.agents import RUBRICS, SYSTEMS
    from .evals.harness import gate_g14, llm_judge, load_cases, run_eval, suite_for

    factory, graders = SYSTEMS[args.agent]
    cases = load_cases(Path(args.root) / args.agent)
    llm = make_llm(args.budget, cache=False, model=args.model)
    if args.agent == "goal_factoring":
        system = factory(lambda: llm, Path(args.cases_root))
    else:
        system = factory(lambda: llm)
    graders = list(graders)
    if args.judge:
        graders.append(llm_judge(llm, RUBRICS[args.agent], system.render))
    report = run_eval(
        system,
        cases,
        graders,
        n=args.n,
        suite_id=args.agent,
        model=args.model or "default",
        harness_version=args.harness_version,
    )
    out = Path(args.out) / args.agent
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report.run.id}.json"
    path.write_text(report.to_json())
    print(report.to_markdown())
    problems = gate_g14(report, suite_for(args.agent, cases, RUBRICS[args.agent]))
    print("\nG14: " + ("pass" if not problems else "FAIL — " + "; ".join(problems)))
    print(f"report: {path}")
    return 0 if not problems else 1


def cmd_eval_compare(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .evals.harness import EvalReport, compare, log_decision

    base = EvalReport.from_json(Path(args.baseline).read_text())
    cand = EvalReport.from_json(Path(args.candidate).read_text())
    d = compare(base, cand, args.min_gain)
    print(("ACCEPT" if d.accept else "REJECT") + "\n" + "\n".join(f"- {r}" for r in d.reasons))
    if args.log:
        log_decision(Path(args.log), base, cand, d, args.change or "")
    return 0 if d.accept else 1


def cmd_eval_rate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .evals.harness import EvalReport, collect_ratings

    path = Path(args.report)
    rep = collect_ratings(EvalReport.from_json(path.read_text()), limit=args.limit)
    path.write_text(rep.to_json())
    print(rep.to_markdown())
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    from .build.templates import TEMPLATES
    from .deploy import PackageSpec, package

    store = ClientStore(_root(args), args.client_id)
    spec = PackageSpec(
        client_id=args.client_id,
        system_id=args.system_id,
        template=TEMPLATES[args.template],
        opportunity_id=args.opportunity,
        client_owner=args.owner,
        environment=args.environment,
        schedule=args.schedule,
        trigger=args.trigger,
        connectors=args.connector or [],
        credential_env=args.credential_env or [],
        config=json.loads(open(args.config).read()) if args.config else {},
        version=args.version,
        lang=args.lang,
        eval_report=args.eval_report,
        owner_trained=args.owner_trained,
        client_owned_accounts=args.client_accounts,
    )
    system, folder, issues = package(spec, store, actor=args.actor)
    print(f"packaged {system.id} v{system.version} -> {folder}")
    status = "go-live ready" if not issues else "not_live"
    print(f"status: {status}" + "".join(f"\n- {i}" for i in issues))
    return 0


def cmd_run_system(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime
    from pathlib import Path

    from .build.templates import TEMPLATES
    from .deploy import Outbox

    store = ClientStore(_root(args), args.client_id)
    base = Path(store.root) / "systems" / args.system_id
    folder = sorted(base.glob("v*"))[-1]
    routine = json.loads((folder / "routine.json").read_text())
    config = json.loads((folder / "config.json").read_text())
    tpl = TEMPLATES[routine["template"]]
    record = json.loads(Path(args.input).read_text())
    llm = make_llm(args.budget) if tpl.uses_ai else None
    out = tpl.run(record, config, llm=llm, lang=args.lang)
    run_dir = folder / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    run_dir.mkdir(parents=True)
    for name, text in out.artifacts.items():
        (run_dir / Path(name).name).write_text(text)
    box = Outbox(store)
    for a in out.actions:
        item = box.put(args.system_id, a, actor=f"system:{args.system_id}")
        print(f"draft in outbox: {item.id} ({a.operation}) — {a.change_summary}")
    print(f"{out.change_summary}\nartifacts: {run_dir}")
    return 0


def cmd_outbox(args: argparse.Namespace) -> int:
    from .deploy import Outbox

    box = Outbox(ClientStore(_root(args), args.client_id))
    if args.action == "list":
        for i in box.list(args.status):
            print(
                f"{i.id}  {i.status:<9} {i.system_id:<24} {i.action.operation:<12} "
                f"{i.action.change_summary}"
            )
        return 0
    if not args.item:
        print("item id required")
        return 2
    if args.action == "show":
        print(box.get(args.item).model_dump_json(indent=2))
    elif args.action == "approve":
        print(box.approve(args.item, args.actor, args.reason).status)
    elif args.action == "reject":
        print(box.reject(args.item, args.actor, args.reason or "rejected").status)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .evals.cases import load_case
    from .evals.runner import run_case
    from .reporting import Bundle, plan, write
    from .simulation import compare, standard_scenarios

    case = load_case(args.case)
    base = run_case(case, lang=args.lang)  # ingests raw files: event logs, transcripts, docs
    graph = case.graph()
    heat, report = base.heat, base.report
    b = Bundle(
        case.title,
        args.lang,
        heat,
        report,
        graph,
        list(case.metrics),
        open_decisions=["§20 open questions: see docs/decisions/000-open-questions.md"],
    )
    if report.binding is not None:
        if args.with_agents:
            from .agents.goal_factoring import factor_goal
            from .agents.opportunity_analyst import analyse_opportunities

            llm = make_llm(args.budget)
            pols = report.policy_audit.policies
            b.tree = factor_goal(
                llm, report.binding, graph, case.metrics, pols, lang=args.lang
            ).result
            seeds = b.tree.opportunity_seeds()
            if seeds:
                b.opportunities = analyse_opportunities(
                    llm, seeds, report.binding, graph, pols, lang=args.lang
                ).result
        b.roadmap = plan(report, b.tree, b.opportunities, graph, case.metrics, lang=args.lang)
        if graph is not None and args.replications > 0:
            b.sims = compare(
                graph,
                standard_scenarios(graph, report.binding.resource_id),
                replications=args.replications,
                horizon_weeks=16,
            )
    paths = write(b, args.out)
    for p in paths:
        print(p)
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    from .evals.cases import load_case
    from .orchestrator import run_pipeline
    from .qa import to_markdown as gates_md

    case = load_case(args.case)
    store = ClientStore(_root(args), args.client_id) if args.client_id else None
    factory = (lambda: make_llm(args.budget)) if args.with_agents else None
    run = run_pipeline(case, lang=args.lang, llm_factory=factory, store=store, out_dir=args.out)
    print(f"status: {run.status}\nreason: {run.reason}")
    for h in run.human_review:
        print(f"human review: {h}")
    print("\n" + gates_md(run.gates["report"]))
    for line in run.state.log:
        print(f"log: {line}")
    return 0 if run.status == "awaiting_review" else 1


def cmd_review(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .orchestrator.review import Review

    rv = Review(ClientStore(_root(args), args.client_id))
    who = args.reviewer
    if args.action == "status":
        for st in rv.status(Path(args.target)):
            by = f" by {st.by}" if st.by else ""
            print(f"{st.state:<18} {st.name}{by}  comments={st.comments}")
        return 0
    if args.action == "approve":
        rv.approve(Path(args.target), who, args.note or "")
    elif args.action == "request-changes":
        rv.request_changes(Path(args.target), who, args.note or "")
    elif args.action == "comment":
        rv.comment(args.target, who, args.note or "", args.line)
    elif args.action == "rerun":
        print(
            "dropped checkpoints:", ", ".join(rv.rerun(args.target, who, args.note or "")) or "none"
        )
    elif args.action == "release":
        try:
            print(rv.release(Path(args.target), who))
        except PermissionError as exc:
            print(exc)
            return 1
    elif args.action == "go-live":
        rec, problems = rv.go_live(
            args.target,
            who,
            Path(args.eval_report) if args.eval_report else None,
            args.owner_trained,
            args.client_accounts,
            args.allow_live,
        )
        if problems:
            print("go-live refused:\n" + "\n".join(f"- {p}" for p in problems))
            return 1
        print(
            f"{rec.id} live; approval {rec.go_live_approval_ref}; "
            f"external actions {'LIVE' if not rec.draft_safe else 'stay drafts'}"
        )
    print("ok")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    from datetime import date

    from .monitoring import Ledger

    led = Ledger(ClientStore(_root(args), args.client_id))
    if args.action == "add":
        led.record(
            args.metric,
            args.baseline,
            args.current,
            date.fromisoformat(args.baseline_date),
            date.fromisoformat(args.date),
            leading=not args.lagging,
            actor=args.actor,
            lag_note=args.lag_note,
            lang=args.lang,
        )
    print(led.to_markdown(args.lang))
    return 0


def cmd_buffers(args: argparse.Namespace) -> int:
    import csv
    from datetime import datetime

    from .monitoring import status
    from .monitoring.buffers import to_markdown as buffers_md
    from .schemas.diagnosis import Buffer

    with open(args.orders, newline="") as f:
        rows = [(r["order_id"], datetime.fromisoformat(r["due"])) for r in csv.DictReader(f)]
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    print(
        buffers_md(
            status(Buffer(id="b", protects="constraint", size_h=args.buffer_h), rows, now),
            args.lang,
        )
    )
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    from .monitoring import WeekSnapshot, evaluate

    weeks = [WeekSnapshot(**w) for w in json.loads(open(args.weeks).read())]
    alerts = evaluate(weeks, args.constraint, args.baseline_demand, args.next)
    for a in alerts:
        print(f"[{a.severity}] {a.kind}: {a.message}")
    if not alerts:
        print("no alerts")
    return 1 if any(a.severity == "action" for a in alerts) else 0


def cmd_sync(args: argparse.Namespace) -> int:
    import csv
    from datetime import date
    from pathlib import Path

    from .sync import LogEntry, Outcome, SyncPolicy, run_sync

    store = ClientStore(_root(args), args.client_id)
    logs = [
        LogEntry(**json.loads(x)) for x in Path(args.logs).read_text().splitlines() if x.strip()
    ]
    with open(args.outcomes, newline="") as f:
        outcomes = [Outcome(r["person"], r["task"], float(r["score"])) for r in csv.DictReader(f)]
    skills = {}
    for spec in args.skill:
        task, rest = spec.split("=", 1)
        version, path = rest.split(":", 1)
        skills[task] = (version, Path(path).read_text())
    salt = os.environ.get(args.salt_env, "")
    policy = SyncPolicy(
        consent_ref=args.consent, salt=salt, share_individual_ranking=args.share_ranking
    )
    res = run_sync(
        make_llm(args.budget),
        args.pod,
        logs,
        outcomes,
        skills,
        policy,
        date.today(),
        lang=args.lang,
    )
    out = Path(store.root) / "sync" / res.session.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(res.pod_report)
    for u in res.updates:
        (out / f"{u.task}-v{u.new_version}.SKILL.md").write_text(u.new_skill)
        (out / f"{u.task}.diff").write_text(u.diff)
    store.put(res.session, produced_by="skill_sync")
    print(res.pod_report)
    print(f"\nproposals (approve before pushing to the team): {out}")
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

    pg = sub.add_parser("goal-tree", help="goal-factor the confirmed constraint of a case")
    pg.add_argument("--case", required=True)
    pg.add_argument("--lang", choices=["de", "en"], default="de")
    pg.add_argument("--mermaid", action="store_true")
    pg.add_argument("--budget", type=float, default=2.0)
    pg.set_defaults(fn=cmd_goal_tree)

    po = sub.add_parser("opportunities", help="goal tree + opportunity map for a case")
    po.add_argument("--case", required=True)
    po.add_argument("--lang", choices=["de", "en"], default="de")
    po.add_argument("--budget", type=float, default=3.0)
    po.set_defaults(fn=cmd_opportunities)

    pa = sub.add_parser("eval-agent", help="N-run eval of an agent (needs API access)")
    pa.add_argument("agent", choices=["transcript_extractor", "goal_factoring"])
    pa.add_argument("--n", type=int, default=10)
    pa.add_argument("--model")
    pa.add_argument("--judge", action="store_true", help="add the LLM-judge rubric grader")
    pa.add_argument("--root", default="evals/agents")
    pa.add_argument("--cases-root", default="evals/cases")
    pa.add_argument("--out", default="evals/results")
    pa.add_argument("--harness-version", default="1")
    pa.add_argument("--budget", type=float, default=10.0)
    pa.set_defaults(fn=cmd_eval_agent)

    pcmp = sub.add_parser("eval-compare", help="hill-climb decision: baseline vs candidate")
    pcmp.add_argument("baseline")
    pcmp.add_argument("candidate")
    pcmp.add_argument("--min-gain", type=float, default=0.0)
    pcmp.add_argument("--log", default="evals/results/hillclimb.jsonl")
    pcmp.add_argument("--change", help="what changed (prompt v2, new model, ...)")
    pcmp.set_defaults(fn=cmd_eval_compare)

    prt = sub.add_parser("eval-rate", help="rate eval outputs 1-10 as a human")
    prt.add_argument("report")
    prt.add_argument("--limit", type=int)
    prt.set_defaults(fn=cmd_eval_rate)

    pk = sub.add_parser("package", help="package a system for the client (skill, routine, runbook)")
    pk.add_argument("client_id")
    pk.add_argument("system_id")
    pk.add_argument(
        "--template",
        required=True,
        choices=["decision-brief", "speed-to-lead-responder", "release-gate-wip-limit"],
    )
    pk.add_argument("--opportunity", required=True)
    pk.add_argument("--owner", required=True)
    pk.add_argument("--environment", default="client AI workspace")
    pk.add_argument("--schedule")
    pk.add_argument("--trigger")
    pk.add_argument("--connector", action="append")
    pk.add_argument("--credential-env", action="append", help="env var NAME in client vault")
    pk.add_argument("--config", help="JSON file with template config")
    pk.add_argument("--version", default="1.0.0")
    pk.add_argument("--lang", choices=["de", "en"], default="de")
    pk.add_argument("--eval-report")
    pk.add_argument("--owner-trained", action="store_true")
    pk.add_argument("--client-accounts", action="store_true")
    pk.add_argument("--actor", default="deployment_agent")
    pk.set_defaults(fn=cmd_package)

    pr = sub.add_parser("run-system", help="run a packaged system once on an input record")
    pr.add_argument("client_id")
    pr.add_argument("system_id")
    pr.add_argument("--input", required=True)
    pr.add_argument("--lang", choices=["de", "en"], default="de")
    pr.add_argument("--budget", type=float, default=1.0)
    pr.set_defaults(fn=cmd_run_system)

    pb = sub.add_parser("outbox", help="review drafts: list/show/approve/reject")
    pb.add_argument("client_id")
    pb.add_argument("action", choices=["list", "show", "approve", "reject"])
    pb.add_argument("item", nargs="?")
    pb.add_argument("--status", choices=["pending", "approved", "rejected", "executed", "failed"])
    pb.add_argument("--reason")
    pb.add_argument("--actor", default=os.environ.get("USER", "reviewer"))
    pb.set_defaults(fn=cmd_outbox)

    pw = sub.add_parser("report", help="write the deliverables package for a case")
    pw.add_argument("--case", required=True)
    pw.add_argument("--out", required=True)
    pw.add_argument("--lang", choices=["de", "en"], default="de")
    pw.add_argument("--with-agents", action="store_true", help="goal tree + opportunities (API)")
    pw.add_argument("--replications", type=int, default=5, help="0 = skip simulation")
    pw.add_argument("--budget", type=float, default=3.0)
    pw.set_defaults(fn=cmd_report)

    pp = sub.add_parser("pipeline", help="run the gated engagement pipeline on a case")
    pp.add_argument("--case", required=True)
    pp.add_argument("--out", required=True)
    pp.add_argument("--client-id", help="enables checkpoints in clients/<id>/pipeline")
    pp.add_argument("--lang", choices=["de", "en"], default="de")
    pp.add_argument("--with-agents", action="store_true")
    pp.add_argument("--budget", type=float, default=5.0)
    pp.set_defaults(fn=cmd_pipeline)

    pv = sub.add_parser(
        "review", help="human review: status/approve/request-changes/comment/rerun/go-live/release"
    )
    pv.add_argument("client_id")
    pv.add_argument(
        "action",
        choices=["status", "approve", "request-changes", "comment", "rerun", "go-live", "release"],
    )
    pv.add_argument("target", help="deliverable file, package dir, phase or system id")
    pv.add_argument("--reviewer", default=os.environ.get("USER", ""))
    pv.add_argument("--note")
    pv.add_argument("--line", type=int)
    pv.add_argument("--eval-report")
    pv.add_argument("--owner-trained", action="store_true")
    pv.add_argument("--client-accounts", action="store_true")
    pv.add_argument(
        "--allow-live",
        action="store_true",
        help="let approved systems execute external actions without drafts",
    )
    pv.set_defaults(fn=cmd_review)

    pl = sub.add_parser("ledger", help="results ledger: show or add a measurement")
    pl.add_argument("client_id")
    pl.add_argument("action", choices=["show", "add"])
    pl.add_argument("--metric")
    pl.add_argument("--baseline", type=float)
    pl.add_argument("--current", type=float)
    pl.add_argument("--baseline-date")
    pl.add_argument("--date")
    pl.add_argument("--lagging", action="store_true")
    pl.add_argument("--lag-note")
    pl.add_argument("--lang", choices=["de", "en"], default="de")
    pl.add_argument("--actor", default="monitoring")
    pl.set_defaults(fn=cmd_ledger)

    pbf = sub.add_parser("buffers", help="buffer penetration for open orders (csv order_id,due)")
    pbf.add_argument("--orders", required=True)
    pbf.add_argument("--buffer-h", type=float, default=168)
    pbf.add_argument("--now")
    pbf.add_argument("--lang", choices=["de", "en"], default="de")
    pbf.set_defaults(fn=cmd_buffers)

    pmo = sub.add_parser("monitor", help="constraint-shift alerts from weekly snapshots (json)")
    pmo.add_argument("--weeks", required=True)
    pmo.add_argument("--constraint", required=True)
    pmo.add_argument("--next")
    pmo.add_argument("--baseline-demand", type=float)
    pmo.set_defaults(fn=cmd_monitor)

    psy = sub.add_parser("sync", help="weekly team sync: skill update proposals (privacy-gated)")
    psy.add_argument("client_id")
    psy.add_argument("--pod", required=True)
    psy.add_argument("--logs", required=True, help="jsonl: person,pod,role,task,text")
    psy.add_argument("--outcomes", required=True, help="csv: person,task,score")
    psy.add_argument(
        "--skill", action="append", required=True, help="task=version:path/to/SKILL.md"
    )
    psy.add_argument("--consent", help="consent / works-agreement reference (required)")
    psy.add_argument("--salt-env", default="UNCLOG_SYNC_SALT")
    psy.add_argument("--share-ranking", action="store_true")
    psy.add_argument("--lang", choices=["de", "en"], default="de")
    psy.add_argument("--budget", type=float, default=2.0)
    psy.set_defaults(fn=cmd_sync)

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
