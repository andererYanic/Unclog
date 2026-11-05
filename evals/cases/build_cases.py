"""Regenerate synthetic cases: ``python evals/cases/build_cases.py``.

Numbers are invented for testing the method. They are not benchmarks (brief preamble).
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent


def ev(i, src, type_, locator, quote=None):
    e = {"id": f"ev-{i}", "source_id": src, "type": type_, "locator": locator}
    if quote:
        e["quote"] = quote
    return e


def m(id_, dom, name, value, unit, *, src=None, measured=True, bm=None, hib=None, period="2026-10"):
    out = {
        "id": id_,
        "domain_id": dom,
        "name": name,
        "value": value,
        "unit": unit,
        "period": period,
        "measured": measured,
    }
    if src:
        out["source_id"] = src
    if bm is not None:
        out["benchmark"] = bm
        out["higher_is_better"] = hib
    return out


def write(case: dict) -> None:
    d = HERE / case["id"]
    d.mkdir(exist_ok=True)
    (d / "case.json").write_text(json.dumps(case, indent=2) + "\n")


# --------------------------------------------------------------------------------------------
# Case 1: RACE bottleneck (speed-to-lead), with a tempting but irrelevant back-end automation.
# --------------------------------------------------------------------------------------------
def race_speed_to_lead() -> dict:
    crm, fin, intv, bench = "src-crm-export", "src-finance-export", "src-intv-ceo", "src-bench"
    sources = [
        {"id": crm, "kind": "export", "title": "HubSpot deals + activity export Q3-Q4"},
        {"id": fin, "kind": "export", "title": "DATEV invoices export"},
        {"id": intv, "kind": "interview", "title": "First call with CEO"},
        {"id": bench, "kind": "web", "title": "Industry funnel benchmarks (illustrative)"},
    ]
    E = lambda i, t="log_data", loc="rows": [ev(i, crm, t, loc)]  # noqa: E731
    resources = [
        {
            "id": "sdr-team",
            "name": "2 SDRs",
            "kind": "team",
            "count": 2,
            "hours_per_period": 32,
            "evidence": E(1, "document", "org chart"),
        },
        {
            "id": "account-execs",
            "name": "3 AEs",
            "kind": "team",
            "count": 3,
            "hours_per_period": 30,
            "evidence": E(2, "document", "org chart"),
        },
        {
            "id": "consultants",
            "name": "Delivery consultants",
            "kind": "team",
            "count": 6,
            "hours_per_period": 32,
            "evidence": E(3, "document", "org chart"),
        },
        {
            "id": "bookkeeper",
            "name": "Bookkeeper",
            "kind": "person",
            "count": 1,
            "hours_per_period": 20,
            "evidence": [ev(4, fin, "document", "org chart")],
        },
    ]
    nodes = [
        {
            "id": "inbound-lead",
            "name": "Inbound lead",
            "domain_id": "RACE-R",
            "arrival": {"kind": "poisson", "params": {"rate": 455}, "unit": "month"},
            "evidence": E(5, "log_data", "contacts created Jul-Oct"),
        },
        {
            "id": "first-response",
            "name": "First response + qualification",
            "domain_id": "RACE-A",
            "resource_ids": ["sdr-team"],
            "service": {"kind": "lognormal", "params": {"mean": 0.4, "cv": 0.6}, "unit": "hour"},
            "wait_time_h": 52,
            "batch_size": 25,
            "evidence": E(6, "log_data", "first activity timestamp - create date")
            + [
                ev(
                    7,
                    intv,
                    "interview_claim",
                    "t=00:14:10",
                    "We go through the new leads in one block on Monday and Thursday.",
                )
            ],
        },
        {
            "id": "discovery-meeting",
            "name": "Discovery meeting",
            "domain_id": "RACE-C",
            "resource_ids": ["account-execs"],
            "service": {"kind": "gamma", "params": {"shape": 4, "scale": 0.5}, "unit": "hour"},
            "evidence": E(8, "log_data", "meetings booked"),
        },
        {
            "id": "proposal",
            "name": "Proposal + close",
            "domain_id": "RACE-C",
            "resource_ids": ["account-execs"],
            "service": {"kind": "gamma", "params": {"shape": 4, "scale": 1.0}, "unit": "hour"},
            "evidence": E(9, "log_data", "deals won/lost"),
        },
        {
            "id": "delivery",
            "name": "Project delivery",
            "domain_id": "fulfillment",
            "resource_ids": ["consultants"],
            "service": {"kind": "lognormal", "params": {"mean": 30, "cv": 0.4}, "unit": "hour"},
            "queue_length": 0,
            "evidence": [ev(10, fin, "log_data", "project hours")],
        },
        {
            "id": "invoice",
            "name": "Invoice + collect",
            "domain_id": "finance",
            "resource_ids": ["bookkeeper"],
            "service": {"kind": "fixed", "params": {"value": 0.75}, "unit": "hour"},
            "evidence": [ev(11, fin, "log_data", "invoice dates")],
        },
    ]
    edges = [
        {"source": "inbound-lead", "target": "first-response", "probability": 1.0},
        {
            "source": "first-response",
            "target": "discovery-meeting",
            "probability": 0.09,
            "label": "meeting booked",
        },
        {"source": "discovery-meeting", "target": "proposal", "probability": 0.7},
        {"source": "proposal", "target": "delivery", "probability": 0.31, "label": "won"},
        {"source": "delivery", "target": "invoice", "probability": 1.0},
    ]
    metrics = [
        m("reach-leads", "RACE-R", "inbound leads", 455, "leads/month", src=crm, bm=400, hib=True),
        m("acq-speed", "RACE-A", "median first response", 52, "h", src=crm, bm=1, hib=False),
        m("acq-book", "RACE-A", "lead -> meeting rate", 0.09, "ratio", src=crm, bm=0.25, hib=True),
        m("conv-close", "RACE-C", "close rate", 0.31, "ratio", src=crm, bm=0.30, hib=True),
        m("exp-churn", "RACE-E", "annual logo churn", 0.12, "ratio", src=crm, bm=0.15, hib=False),
        m(
            "ful-ontime",
            "fulfillment",
            "projects on time",
            0.92,
            "ratio",
            src=fin,
            bm=0.85,
            hib=True,
        ),
        m("fin-dso", "finance", "days sales outstanding", 34, "days", src=fin, bm=30, hib=False),
        m("sup-frt", "support", "client first response", 3, "h", src=crm, bm=4, hib=False),
        m("ops-util", "ops", "billable utilization", 0.62, "ratio", src=fin),
        m("hr-tth", "hr", "time to hire", 38, "days", src=intv, measured=False, bm=45, hib=False),
        m("proc-stock", "procurement", "stockouts", 0, "count", src=intv, measured=False),
        m(
            "prod-release",
            "product",
            "internal tooling backlog",
            4,
            "items",
            src=intv,
            measured=False,
        ),
        m(
            "it-manual",
            "it",
            "manual CRM->invoice re-keying",
            2,
            "h/week",
            src=intv,
            measured=False,
        ),
        m(
            "legal-queue",
            "legal",
            "contracts awaiting review",
            1,
            "count",
            src=intv,
            measured=False,
        ),
        m(
            "mgmt-approvals",
            "mgmt",
            "proposal approval wait",
            4,
            "h",
            src=intv,
            measured=False,
            bm=24,
            hib=False,
        ),
    ]
    return {
        "id": "race_speed_to_lead",
        "title": "B2B consultancy: leads answered in 52 h",
        "kind": "race",
        "traps": [
            "impressive back-end automation temptation (invoice OCR)",
            "batching policy causes the wait, not SDR capacity",
        ],
        "description": "455 leads/month, but SDRs work new leads in two weekly batches, so the "
        "median first response is 52 h and only 9% book a meeting. Delivery "
        "and finance have ample capacity; an invoice-automation idea is a "
        "non-constraint temptation.",
        "sources": sources,
        "resources": resources,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "expected": {
            "top_domain": "RACE-A",
            "direction": "market_limited",
            "must_rank_below_top": ["finance", "fulfillment"],
            "coverage_issues": 0,
            "binding": {"type": "policy", "domain": "RACE-A", "target_contains": "batch"},
            "work_mode": "full",
            "must_not_confirm": ["finance", "fulfillment"],
            "local_optimum_flagged": True,
        },
    }


# --------------------------------------------------------------------------------------------
# Case 2: back-end bottleneck dressed as a marketing problem (lead flood > workshop capacity).
# --------------------------------------------------------------------------------------------
def events_csv(path: Path, seed: int = 7) -> None:
    rng = random.Random(seed)
    start = datetime(2026, 8, 3, 9, 0)
    rows = []
    queue_free_at = start  # single-file production queue (constraint)
    for i in range(1, 181):  # ~22 orders/week over ~8 weeks
        t = start + timedelta(hours=i * 168 / 22 + rng.uniform(-3, 3))
        oid = f"ORD-{10000 + i}"
        rows.append((oid, "order_received", t, "shop"))
        t2 = t + timedelta(hours=rng.uniform(4, 30))
        rows.append((oid, "design_approved", t2, "designer"))
        # workshop: 152 work h/week vs 8 h/order -> 19 orders/week capacity; arrivals 22/week
        start_prod = max(t2, queue_free_at) + timedelta(hours=rng.uniform(1, 8))
        queue_free_at = start_prod + timedelta(hours=168 / 19)
        if start_prod > datetime(2026, 10, 2):
            continue  # still waiting at export time -> open case
        rows.append((oid, "production_start", start_prod, "workshop"))
        done = start_prod + timedelta(hours=rng.uniform(30, 60))
        rows.append((oid, "production_done", done, "workshop"))
        rows.append((oid, "shipped", done + timedelta(hours=rng.uniform(10, 30)), "logistics"))
    rows.sort(key=lambda r: r[2])
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "status", "changed_at", "owner"])
        for oid, act, ts, who in rows:
            w.writerow([oid, act, ts.strftime("%Y-%m-%dT%H:%M:%S"), who])


def backend_fulfillment_flood() -> dict:
    erp, ads, intv = "src-erp-orders", "src-ads-export", "src-intv-owner"
    sources = [
        {"id": erp, "kind": "event_log", "title": "Shop/ERP order status history"},
        {"id": ads, "kind": "export", "title": "Meta Ads + Shopify funnel export"},
        {"id": intv, "kind": "interview", "title": "First call with owner"},
    ]
    resources = [
        {
            "id": "workshop",
            "name": "4 carpenters",
            "kind": "team",
            "count": 4,
            "hours_per_period": 38,
            "evidence": [
                ev(1, erp, "log_data", "production timestamps"),
                ev(
                    2,
                    intv,
                    "interview_claim",
                    "t=00:21:30",
                    "The guys in the workshop are working Saturdays and still behind.",
                ),
            ],
        },
        {
            "id": "designer",
            "name": "Designer",
            "kind": "person",
            "count": 1,
            "hours_per_period": 40,
            "evidence": [ev(3, erp, "log_data", "design approvals")],
        },
        {
            "id": "marketing",
            "name": "Marketing freelancer",
            "kind": "person",
            "count": 1,
            "hours_per_period": 10,
            "evidence": [ev(4, ads, "document", "contract")],
        },
    ]
    nodes = [
        {
            "id": "visitors",
            "name": "Shop visitors",
            "domain_id": "RACE-R",
            "arrival": {"kind": "poisson", "params": {"rate": 2000}, "unit": "week"},
            "evidence": [ev(5, ads, "log_data", "sessions")],
        },
        {
            "id": "checkout",
            "name": "Configurator + checkout",
            "domain_id": "RACE-C",
            "evidence": [ev(6, ads, "log_data", "orders / sessions")],
        },
        {
            "id": "design",
            "name": "Design approval",
            "domain_id": "fulfillment",
            "resource_ids": ["designer"],
            "service": {"kind": "gamma", "params": {"shape": 3, "scale": 0.5}, "unit": "hour"},
            "evidence": [ev(7, erp, "log_data", "design_approved")],
        },
        {
            "id": "production",
            "name": "Workshop production",
            "domain_id": "fulfillment",
            "resource_ids": ["workshop"],
            "service": {"kind": "lognormal", "params": {"mean": 8, "cv": 0.35}, "unit": "hour"},
            "queue_length": 64,
            "evidence": [
                ev(8, erp, "queue_observation", "open orders without production_start"),
                ev(9, erp, "log_data", "production timestamps"),
            ],
        },
        {
            "id": "shipping",
            "name": "Shipping",
            "domain_id": "fulfillment",
            "evidence": [ev(10, erp, "log_data", "shipped")],
        },
    ]
    edges = [
        {"source": "visitors", "target": "checkout", "probability": 0.011},
        {"source": "checkout", "target": "design", "probability": 1.0},
        {"source": "design", "target": "production", "probability": 1.0},
        {"source": "production", "target": "shipping", "probability": 1.0},
    ]
    metrics = [
        m("reach-sessions", "RACE-R", "shop sessions", 2000, "sessions/week", src=ads),
        m(
            "conv-rate",
            "RACE-C",
            "visitor -> order (owner's estimate)",
            0.011,
            "ratio",
            measured=False,
            bm=0.015,
            hib=True,
        ),
        m("exp-repeat", "RACE-E", "repeat purchase rate", 0.08, "ratio", src=erp),
        m("ful-leadtime-promise", "fulfillment", "promised delivery", 3, "weeks", measured=False),
        m(
            "sup-tickets",
            "support",
            "'where is my order' emails",
            41,
            "per week",
            measured=False,
            bm=10,
            hib=False,
        ),
    ]
    return {
        "id": "backend_fulfillment_flood",
        "title": "Custom furniture shop: 'we need more sales'",
        "kind": "backend",
        "traps": [
            "back-end bottleneck dressed as a marketing problem",
            "more leads must be rejected (flooding)",
        ],
        "description": "Owner asks for better ads. Conversion is a bit below benchmark (owner's "
        "estimate), but the workshop gets ~22 orders/week against capacity for "
        "~19; 64 orders wait and 'where is my order' emails pile up in support.",
        "sources": sources,
        "resources": resources,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "raw_files": ["orders_events.csv"],
        "event_log_domains": {"orders_events.csv": "fulfillment"},
        "activity_nodes": {"production_start": "production", "design_approved": "design"},
        "expected": {
            "top_domain": "fulfillment",
            "direction": "capacity_limited",
            "must_rank_below_top": ["RACE-C", "RACE-R"],
            "eventlog_slowest_wait": "production_start",
            "binding": {"type": "physical", "domain": "fulfillment", "target_contains": "workshop"},
            "work_mode": "full",
            "next_constraint_kind": "physical",
            "must_not_confirm": ["RACE-C", "support"],
        },
    }


# --------------------------------------------------------------------------------------------
# Case 3: no tracking: only first-call estimates; first deliverable must be instrumentation.
# --------------------------------------------------------------------------------------------
def no_tracking() -> dict:
    metrics = [
        m("reach-guess", "RACE-R", "website visitors (guess)", 1000, "per month", measured=False),
        m("conv-guess", "RACE-C", "close rate (guess)", 0.2, "ratio", measured=False),
    ]
    return {
        "id": "no_tracking",
        "title": "Local services firm with no tracking",
        "kind": "mixed",
        "traps": ["client with no tracking: first deliverable is instrumentation"],
        "description": "Owner can only guess two numbers. No exports, no flow data.",
        "metrics": metrics,
        "expected": {
            "top_domain": None,
            "direction": "no_flow_data",
            "min_coverage_issues": 12,
            "binding": None,
            "work_mode": "discovery_only",
        },
    }


# --------------------------------------------------------------------------------------------
# Case 4: hidden policy constraint: owner signs quotes once a week. Quote turnaround looks like
# a sales (RACE-C) problem; nobody is overloaded.
# --------------------------------------------------------------------------------------------
def hidden_policy_approval() -> dict:
    crm, intv = "src-crm-quotes", "src-intv-sales"
    E = lambda i, t="log_data", loc="rows": [ev(i, crm, t, loc)]  # noqa: E731
    resources = [
        {
            "id": "sales-reps",
            "name": "Sales reps",
            "kind": "team",
            "count": 2,
            "hours_per_period": 35,
            "evidence": E(1, "document", "org chart"),
        },
        {
            "id": "estimators",
            "name": "Estimators",
            "kind": "team",
            "count": 3,
            "hours_per_period": 38,
            "evidence": E(2, "document", "org chart"),
        },
        {
            "id": "owner",
            "name": "Owner",
            "kind": "person",
            "count": 1,
            "hours_per_period": 6,
            "evidence": [
                ev(
                    3,
                    intv,
                    "interview_claim",
                    "t=00:08:00",
                    "I block Friday mornings for approvals.",
                )
            ],
        },
        {
            "id": "install-crew",
            "name": "Installation crews",
            "kind": "team",
            "count": 5,
            "hours_per_period": 38,
            "evidence": E(4, "document", "org chart"),
        },
    ]
    nodes = [
        {
            "id": "rfq",
            "name": "Request for quote",
            "domain_id": "RACE-A",
            "resource_ids": ["sales-reps"],
            "arrival": {"kind": "poisson", "params": {"rate": 30}, "unit": "week"},
            "service": {"kind": "fixed", "params": {"value": 0.5}, "unit": "hour"},
            "evidence": E(5),
        },
        {
            "id": "quote-prep",
            "name": "Quote preparation",
            "domain_id": "RACE-C",
            "resource_ids": ["estimators"],
            "service": {"kind": "gamma", "params": {"shape": 4, "scale": 0.5}, "unit": "hour"},
            "wait_time_h": 10,
            "evidence": E(6),
        },
        {
            "id": "owner-approval",
            "name": "Owner approval of quotes",
            "domain_id": "mgmt",
            "resource_ids": ["owner"],
            "service": {"kind": "fixed", "params": {"value": 9}, "unit": "minute"},
            "batch_size": 30,
            "wait_time_h": 96,
            "evidence": E(7, "queue_observation", "quotes in status 'awaiting approval'"),
        },
        {
            "id": "install",
            "name": "Installation",
            "domain_id": "fulfillment",
            "resource_ids": ["install-crew"],
            "service": {"kind": "lognormal", "params": {"mean": 12, "cv": 0.3}, "unit": "hour"},
            "evidence": E(8),
        },
    ]
    edges = [
        {"source": "rfq", "target": "quote-prep", "probability": 0.9},
        {"source": "quote-prep", "target": "owner-approval", "probability": 1.0},
        {"source": "owner-approval", "target": "install", "probability": 0.3, "label": "won"},
    ]
    metrics = [
        m("rfq-volume", "RACE-A", "requests for quote", 30, "per week", src=crm, bm=25, hib=True),
        m("quote-turnaround", "RACE-C", "quote turnaround", 6, "days", src=crm, bm=2, hib=False),
        m("win-rate", "RACE-C", "quote win rate", 0.3, "ratio", src=crm, bm=0.3, hib=True),
        m(
            "install-ontime",
            "fulfillment",
            "installs on time",
            0.93,
            "ratio",
            src=crm,
            bm=0.9,
            hib=True,
        ),
    ]
    return {
        "id": "hidden_policy_approval",
        "title": "Kitchen installer: quotes take 6 days",
        "kind": "backend",
        "traps": [
            "hidden policy constraint (owner sign-off batch)",
            "symptom shows up in a RACE metric",
            "estimator KPI rewards local efficiency",
        ],
        "description": "Quote turnaround is 6 days vs 2 expected. Estimators finish in hours, "
        "but every quote above 5k needs the owner's sign-off, done on Fridays. "
        "No resource is overloaded.",
        "sources": [
            {"id": crm, "kind": "export", "title": "CRM quote status export"},
            {"id": intv, "kind": "interview", "title": "Call with sales lead"},
        ],
        "resources": resources,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "raw_files": ["pricing_policy.md"],
        "expected": {
            "direction": "market_limited",
            "binding": {"type": "policy", "domain": "mgmt", "target_contains": "approval"},
            "work_mode": "full",
            "must_not_confirm": ["RACE-C"],
            "local_optimum_flagged": True,
        },
    }


POLICY_MD = """# Pricing & quoting policy v2 (2023)

Every quote above 5,000 EUR needs sign-off by the owner. The owner signs them on Fridays.

Estimators are measured on quotes prepared per week; the quarterly bonus is tied to that number.
"""


# --------------------------------------------------------------------------------------------
# Case 5: market constraint after capacity was fixed (furniture shop, six months later).
# --------------------------------------------------------------------------------------------
def market_after_elevation() -> dict:
    erp, ads = "src-erp-orders-2027", "src-ads-2027"
    resources = [
        {
            "id": "workshop",
            "name": "6 carpenters",
            "kind": "team",
            "count": 6,
            "hours_per_period": 38,
            "evidence": [ev(1, erp, "log_data", "production timestamps")],
        },
        {
            "id": "designer",
            "name": "Designers",
            "kind": "team",
            "count": 2,
            "hours_per_period": 40,
            "evidence": [ev(2, erp, "log_data", "design approvals")],
        },
    ]
    nodes = [
        {
            "id": "visitors",
            "name": "Shop visitors",
            "domain_id": "RACE-R",
            "arrival": {"kind": "poisson", "params": {"rate": 1200}, "unit": "week"},
            "evidence": [ev(3, ads, "log_data", "sessions")],
        },
        {
            "id": "checkout",
            "name": "Configurator + checkout",
            "domain_id": "RACE-C",
            "evidence": [ev(4, ads, "log_data", "orders / sessions")],
        },
        {
            "id": "design",
            "name": "Design approval",
            "domain_id": "fulfillment",
            "resource_ids": ["designer"],
            "service": {"kind": "gamma", "params": {"shape": 3, "scale": 0.5}, "unit": "hour"},
            "evidence": [ev(5, erp, "log_data", "design_approved")],
        },
        {
            "id": "production",
            "name": "Workshop production",
            "domain_id": "fulfillment",
            "resource_ids": ["workshop"],
            "service": {"kind": "lognormal", "params": {"mean": 8, "cv": 0.35}, "unit": "hour"},
            "queue_length": 0,
            "wait_time_h": 6,
            "evidence": [ev(6, erp, "log_data", "production timestamps")],
        },
    ]
    edges = [
        {"source": "visitors", "target": "checkout", "probability": 0.0183},
        {"source": "checkout", "target": "design", "probability": 1.0},
        {"source": "design", "target": "production", "probability": 1.0},
    ]
    metrics = [
        m("sessions", "RACE-R", "shop sessions", 1200, "per week", src=ads, bm=2000, hib=True),
        m("conv", "RACE-C", "visitor -> order", 0.0183, "ratio", src=ads, bm=0.015, hib=True),
        m("repeat", "RACE-E", "repeat purchase rate", 0.09, "ratio", src=erp, bm=0.08, hib=True),
        m("leadtime", "fulfillment", "order lead time", 2.5, "weeks", src=erp, bm=3, hib=False),
    ]
    return {
        "id": "market_after_elevation",
        "title": "Furniture shop after adding two carpenters",
        "kind": "race",
        "traps": ["market constraint after capacity is fixed", "inertia: still talks capacity"],
        "description": "Workshop now at ~77%, no queue, lead time beats promise. Traffic fell "
        "after an ad account change; demand is now the limit.",
        "sources": [
            {"id": erp, "kind": "event_log", "title": "ERP orders 2027"},
            {"id": ads, "kind": "export", "title": "Ads + shop analytics 2027"},
        ],
        "resources": resources,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "expected": {
            "direction": "market_limited",
            "top_domain": "RACE-R",
            "binding": {"type": "market", "domain": "RACE-R"},
            "work_mode": "full",
            "next_constraint_kind": "physical",
        },
    }


# --------------------------------------------------------------------------------------------
# Case 6: interview says "sales is the problem"; logs say support is drowning.
# --------------------------------------------------------------------------------------------
def tickets_csv(path: Path, seed: int = 11) -> None:
    rng = random.Random(seed)
    start = datetime(2026, 9, 7, 8, 0)
    rows = []
    free_at = start
    for i in range(1, 6 * 140 + 1):  # 140 tickets/week for 6 weeks; capacity ~123/week
        t = start + timedelta(hours=i * 168 / 140 + rng.uniform(-0.5, 0.5))
        tid = f"T-{50000 + i}"
        rows.append((tid, "created", t, ""))
        resp = max(t, free_at) + timedelta(minutes=rng.uniform(5, 40))
        free_at = resp + timedelta(hours=168 / 123)
        if resp > datetime(2026, 10, 19):
            continue
        agent = rng.choice(["jonas", "lea", "mehmet"])
        rows.append((tid, "first_response", resp, agent))
        rows.append((tid, "resolved", resp + timedelta(hours=rng.uniform(1, 20)), agent))
    rows.sort(key=lambda r: r[2])
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "event", "timestamp", "assignee"])
        for tid, act, ts, who in rows:
            w.writerow([tid, act, ts.strftime("%Y-%m-%dT%H:%M:%S"), who])


INTERVIEW_VTT = """WEBVTT

00:02:10.000 --> 00:02:18.000
CEO: Our real problem is sales. Closing takes forever, deals drag on for two months.

00:05:40.000 --> 00:05:52.000
CEO: Support is fine I think. Well, when Jonas from support is on vacation nothing gets answered.

00:06:03.000 --> 00:06:10.000
CEO: Customers do chase us about tickets, sometimes three times.
"""


def conflicting_testimony() -> dict:
    hd, crm, intv = "src-helpdesk", "src-crm-saas", "src-intv-ceo-saas"
    resources = [
        {
            "id": "support-team",
            "name": "Support agents",
            "kind": "team",
            "count": 3,
            "hours_per_period": 35,
            "evidence": [ev(1, hd, "log_data", "agents on tickets")],
        },
        {
            "id": "aes",
            "name": "Account executives",
            "kind": "team",
            "count": 2,
            "hours_per_period": 35,
            "evidence": [ev(2, crm, "document", "org chart")],
        },
    ]
    nodes = [
        {
            "id": "trials",
            "name": "Trial sign-ups",
            "domain_id": "RACE-A",
            "arrival": {"kind": "poisson", "params": {"rate": 60}, "unit": "week"},
            "evidence": [ev(3, crm, "log_data", "trials")],
        },
        {
            "id": "sales-call",
            "name": "Sales call + close",
            "domain_id": "RACE-C",
            "resource_ids": ["aes"],
            "service": {"kind": "gamma", "params": {"shape": 2, "scale": 1}, "unit": "hour"},
            "evidence": [ev(4, crm, "log_data", "deals")],
        },
        {
            "id": "tickets-in",
            "name": "Customer tickets",
            "domain_id": "support",
            "arrival": {"kind": "poisson", "params": {"rate": 140}, "unit": "week"},
            "evidence": [ev(5, hd, "log_data", "tickets created")],
        },
        {
            "id": "support-queue",
            "name": "First response",
            "domain_id": "support",
            "resource_ids": ["support-team"],
            "service": {"kind": "lognormal", "params": {"mean": 0.85, "cv": 0.8}, "unit": "hour"},
            "evidence": [ev(6, hd, "log_data", "first response timestamps")],
        },
    ]
    edges = [
        {"source": "trials", "target": "sales-call", "probability": 0.35},
        {"source": "tickets-in", "target": "support-queue", "probability": 1.0},
    ]
    metrics = [
        m(
            "cycle",
            "RACE-C",
            "sales cycle (CEO's estimate)",
            60,
            "days",
            src=intv,
            measured=False,
            bm=30,
            hib=False,
        ),
        m("close", "RACE-C", "trial -> paid", 0.2, "ratio", src=crm, bm=0.18, hib=True),
        m("trials-vol", "RACE-A", "trial sign-ups", 60, "per week", src=crm),
        m("churn", "RACE-E", "monthly churn", 0.031, "ratio", src=crm, bm=0.02, hib=False),
    ]
    return {
        "id": "conflicting_testimony",
        "title": "SaaS: CEO blames sales, helpdesk log disagrees",
        "kind": "backend",
        "traps": [
            "noisy/conflicting interview vs log data",
            "testimony alone must not confirm a constraint",
        ],
        "description": "CEO says sales cycles are the problem (estimate only). The helpdesk "
        "log shows 140 tickets/week against capacity for ~123; first responses "
        "drift to days and churn is above benchmark.",
        "sources": [
            {"id": hd, "kind": "event_log", "title": "Helpdesk export"},
            {"id": crm, "kind": "export", "title": "CRM export"},
            {"id": intv, "kind": "interview", "title": "Call with CEO"},
        ],
        "resources": resources,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "raw_files": ["helpdesk_events.csv", "interview_ceo.vtt"],
        "event_log_domains": {"helpdesk_events.csv": "support"},
        "activity_nodes": {"first_response": "support-queue"},
        "expected": {
            "direction": "capacity_limited",
            "top_domain": "support",
            "binding": {"type": "physical", "domain": "support", "target_contains": "support-team"},
            "work_mode": "full",
            "must_not_confirm": ["RACE-C"],
        },
    }


if __name__ == "__main__":
    write(race_speed_to_lead())
    write(backend_fulfillment_flood())
    events_csv(HERE / "backend_fulfillment_flood" / "orders_events.csv")
    write(no_tracking())
    write(hidden_policy_approval())
    (HERE / "hidden_policy_approval" / "pricing_policy.md").write_text(POLICY_MD)
    write(market_after_elevation())
    write(conflicting_testimony())
    tickets_csv(HERE / "conflicting_testimony" / "helpdesk_events.csv")
    (HERE / "conflicting_testimony" / "interview_ceo.vtt").write_text(INTERVIEW_VTT)
    print("cases written")
