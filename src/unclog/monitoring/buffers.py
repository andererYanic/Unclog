"""Buffer management (brief §2.3, later-TOC): penetration of each order into the time buffer in
front of the constraint. Green < 1/3 consumed, yellow < 2/3, red beyond; red orders are expedited
and their causes logged (the cause list is the improvement backlog, POOGI)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from ..schemas.diagnosis import Buffer


@dataclass(frozen=True)
class OrderBuffer:
    order_id: str
    due: datetime
    penetration: float  # 0 = buffer untouched, 1 = due now, >1 = late
    zone: str  # green | yellow | red | late


def penetration(buffer: Buffer, due: datetime, now: datetime) -> float:
    """Share of the buffer consumed: buffer starts ``size_h`` before the due time."""
    start = due.timestamp() - buffer.size_h * 3600
    return (now.timestamp() - start) / (buffer.size_h * 3600)


def zone(buffer: Buffer, p: float) -> str:
    if p > 1:
        return "late"
    if p * 100 >= buffer.red_pct:
        return "red"
    if p * 100 >= buffer.green_pct:
        return "yellow"
    return "green"


def status(buffer: Buffer, orders: list[tuple[str, datetime]], now: datetime) -> list[OrderBuffer]:
    out = []
    for oid, due in orders:
        p = max(0.0, penetration(buffer, due, now))
        out.append(OrderBuffer(oid, due, round(p, 3), zone(buffer, p)))
    return sorted(out, key=lambda o: -o.penetration)


def summary(items: list[OrderBuffer]) -> dict[str, int]:
    c = Counter(o.zone for o in items)
    return {z: c.get(z, 0) for z in ("green", "yellow", "red", "late")}


def to_markdown(items: list[OrderBuffer], lang: str = "en") -> str:
    s = summary(items)
    head = {"en": "Buffer status", "de": "Pufferstatus"}[lang]
    out = [
        f"**{head}:** " + ", ".join(f"{k} {v}" for k, v in s.items()),
        "",
        "| Order | Due | Penetration | Zone |",
        "|---|---|---:|---|",
    ]
    out += [
        f"| {o.order_id} | {o.due:%Y-%m-%d %H:%M} | {o.penetration:.0%} | {o.zone} |"
        for o in items
        if o.zone in ("red", "late")
    ]
    return "\n".join(out)
