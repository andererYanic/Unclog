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
        "expected": {
            "top_domain": "fulfillment",
            "direction": "capacity_limited",
            "must_rank_below_top": ["RACE-C", "RACE-R"],
            "eventlog_slowest_wait": "production_start",
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
        "expected": {"top_domain": None, "direction": "no_flow_data", "min_coverage_issues": 12},
    }


if __name__ == "__main__":
    write(race_speed_to_lead())
    write(backend_fulfillment_flood())
    events_csv(HERE / "backend_fulfillment_flood" / "orders_events.csv")
    write(no_tracking())
    print("cases written")
