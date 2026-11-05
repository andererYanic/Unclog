"""Command line: ``unclog ingest <client_id> <folder>`` and ``unclog sources <client_id>``."""

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


def cmd_eval_cases(args: argparse.Namespace) -> int:
    from .evals.runner import MAX_RACE_BACKEND_GAP, run_all

    summary = run_all(args.root)
    print(summary.to_text())
    gap = summary.race_backend_gap
    ok = all(r.passed for r in summary.results) and (gap is None or gap <= MAX_RACE_BACKEND_GAP)
    return 0 if ok else 1


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

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
