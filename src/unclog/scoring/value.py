"""T/I/OE value model with realization rules (brief §8.6; gates G7, G9, G17).

ΔProfit/month = ΔT − ΔOE_realized − Δ(carrying cost of I) − run cost − amortized build

- ΔT comes only from simulation: baseline vs. effect, same seed (common random numbers), so a
  throughput claim is always ``validated_by=simulation`` with a SimRun id (G9). It counts only
  where the constraint actually moves; a non-constraint speed-up simulates to ~0 (NCX-10).
- ΔOE counts only with a realization path. Claimed savings without one go to the mirage ledger
  at zero (G7).
- ΔI is valued at carrying cost from simulated WIP change.
- Costs: inference per item, licences, review labour (conservative: always costed), build
  amortized over N months.
- Effects are explicit inputs with low/base/high levels and a basis (assumption / pilot /
  measured). Several opportunities on one constraint are also simulated together (portfolio)
  because their gains do not add up (de-duplication).
- Adoption ramp and expected lag are reported with each line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..flow.graph import FlowGraph
from ..schemas.design import (
    DeltaI,
    DeltaOE,
    DeltaT,
    MirageEntry,
    Opportunity,
    RealizationPath,
    ValueLine,
    ValueModel,
    ValueScenario,
)
from ..schemas.diagnosis import Distribution
from ..simulation import Scenario, SimResult, simulate

WEEKS_PER_MONTH = 52 / 12
LEVELS = (ValueScenario.low, ValueScenario.base, ValueScenario.high)

EffectKind = Literal["capacity", "conversion", "demand", "batch", "service"]


@dataclass(frozen=True)
class Effect:
    """What the opportunity changes in the flow, at three confidence levels.

    capacity:   resource capacity × (1 + level)      target = resource id
    service:    node service time × (1 − level)       target = node id
    conversion: edge probability × (1 + level)        target = "source->target"
    demand:     external arrivals × (1 + level)       target = entry node id or "*"
    batch:      node batch size = level               target = node id
    """

    kind: EffectKind
    target: str
    low: float
    base: float
    high: float
    basis: Literal["assumption", "pilot", "measured"] = "assumption"
    note: str = ""

    def level(self, s: ValueScenario) -> float:
        return {
            ValueScenario.low: self.low,
            ValueScenario.base: self.base,
            ValueScenario.high: self.high,
        }[s]


@dataclass(frozen=True)
class Economics:
    currency: str = "EUR"
    throughput_per_unit: float = 0.0  # price − truly variable cost per unit of throughput
    inventory_value_per_unit: float = 0.0  # money tied up per unit of WIP
    carrying_rate_annual: float = 0.10
    hourly_cost: float = 50.0  # loaded cost of review labour
    amortization_months: int = 12
    horizon_months: int = 12


@dataclass(frozen=True)
class CostInputs:
    build_cost: float = 0.0
    monthly_license: float = 0.0
    inference_cost_per_item: float = 0.0
    items_per_week: float = 0.0
    review_h_per_week: float = 0.0
    adoption_months: int = 2  # linear ramp to full effect
    expected_lag: str = "leading indicators in 2–4 weeks; money in 1–3 months"


@dataclass(frozen=True)
class OpportunityInput:
    opportunity: Opportunity
    effects: tuple[Effect, ...] = ()
    costs: CostInputs = CostInputs()
    claimed_oe_saving: float = 0.0  # per month (negative = saving), e.g. "saves 2 FTE"
    capacity_released_h: float = 0.0  # per week, if claimed
    realization_path: RealizationPath | None = None


@dataclass
class SimSettings:
    replications: int = 8
    horizon_weeks: float = 20
    warmup_weeks: float = 3
    seed: int = 42


@dataclass
class OpportunityValue:
    opportunity_id: str
    lines: list[ValueLine]
    delta: dict[ValueScenario, tuple[DeltaT, DeltaI, DeltaOE]]
    sim_runs: dict[str, SimResult]
    first_year: dict[ValueScenario, float]
    notes: list[str] = field(default_factory=list)


@dataclass
class ValueReport:
    model: ValueModel
    per_opportunity: list[OpportunityValue]
    portfolio: dict[ValueScenario, float]  # ΔT/month with all effects together (base costs)
    portfolio_sum_of_parts: dict[ValueScenario, float]
    baseline: SimResult


# ---- applying effects -------------------------------------------------------------------
def apply_effects(
    graph: FlowGraph, effects: tuple[Effect, ...], level: ValueScenario
) -> tuple[FlowGraph, dict[str, float]]:
    """Returns the modified graph and batch overrides for the simulator."""
    g = graph
    batch: dict[str, float] = {}
    for e in effects:
        x = e.level(level)
        if e.kind == "capacity":
            g = g.with_capacity_scale(e.target, 1 + x)
        elif e.kind == "demand":
            g = g.with_arrival_scale(1 + x, None if e.target == "*" else [e.target])
        elif e.kind == "batch":
            batch[e.target] = max(1.0, x)
        elif e.kind == "conversion":
            src, dst = e.target.split("->")
            edges = [
                ed.model_copy(update={"probability": min(1.0, ed.probability * (1 + x))})
                if (ed.source, ed.target) == (src, dst)
                else ed
                for ed in g.edges
            ]
            if edges == g.edges:
                raise ValueError(f"conversion effect: no edge {e.target}")
            g = FlowGraph(g.nodes, edges, g.resources, g.tasks, dict(g.arrival_scale))
        elif e.kind == "service":
            nodes = []
            for n in g.nodes:
                if n.id == e.target:
                    if n.service is None:
                        raise ValueError(f"service effect: node {n.id} has no service time")
                    n = n.model_copy(update={"service": _scale_service(n.service, 1 - x)})
                nodes.append(n)
            g = FlowGraph(nodes, g.edges, g.resources, g.tasks, dict(g.arrival_scale))
    return g, batch


def _scale_service(d: Distribution, f: float) -> Distribution:
    p = dict(d.params)
    for k in ("mean", "value", "scale", "low", "mode", "high"):
        if k in p:
            p[k] = p[k] * f
    if "rate" in p and d.kind in ("exponential", "gamma"):
        p["rate"] = p["rate"] / f
    if "mu" in p:  # lognormal(mu, sigma): scaling multiplies by f
        import math

        p["mu"] = p["mu"] + math.log(f)
    samples = [s * f for s in d.samples] if d.samples else None
    return d.model_copy(update={"params": p, "samples": samples})


def _sim(graph: FlowGraph, batch: dict[str, float], name: str, s: SimSettings) -> SimResult:
    return simulate(
        graph,
        Scenario(name, batch=batch),
        replications=s.replications,
        horizon_weeks=s.horizon_weeks,
        warmup_weeks=s.warmup_weeks,
        seed=s.seed,
    )


# ---- valuation ---------------------------------------------------------------------------
def value_opportunity(
    graph: FlowGraph,
    item: OpportunityInput,
    econ: Economics,
    baseline: SimResult,
    sims: SimSettings,
) -> OpportunityValue:
    opp = item.opportunity
    c = item.costs
    lines, deltas, runs, first_year = [], {}, {}, {}
    notes: list[str] = []
    base_wip = baseline.wip_total.mean or 0.0
    base_thr = baseline.throughput.mean or 0.0
    for lvl in LEVELS:
        if item.effects:
            g2, batch = apply_effects(graph, item.effects, lvl)
            run_id = f"sim-{opp.id}-{lvl.value}"
            res = _sim(g2, batch, f"{opp.id} ({lvl.value})", sims)
            runs[run_id] = res
            d_units = (res.throughput.mean or 0.0) - base_thr
            d_wip = (res.wip_total.mean or 0.0) - base_wip
            if not significant(baseline, res):
                if abs(d_units) > 0:
                    notes.append(
                        f"{lvl.value}: simulated ΔT {d_units:+.2f} units/week is within "
                        "noise (< 2 SE): counted as 0"
                    )
                d_units = 0.0
            dt = DeltaT(
                amount=round(d_units * WEEKS_PER_MONTH * econ.throughput_per_unit, 2),
                validated_by="simulation",
                sim_run_id=run_id,
                demand_can_absorb=None,
                lag=c.expected_lag,
            )
        else:
            d_units = d_wip = 0.0
            dt = DeltaT(amount=0.0, validated_by="none", lag=c.expected_lag)
        di = DeltaI(
            amount=round(d_wip * econ.inventory_value_per_unit, 2),
            carrying_cost_rate=econ.carrying_rate_annual,
            measurement_method="simulated time-average WIP × inventory value per unit",
        )
        doe = DeltaOE(
            amount=item.claimed_oe_saving,
            capacity_released_h=item.capacity_released_h,
            realization_path=item.realization_path,
            lag=c.expected_lag,
        )
        realized_oe = doe.realized_amount * (
            doe.realization_path.probability if doe.realization_path else 0.0
        )
        carrying = di.amount * econ.carrying_rate_annual / 12
        run_cost = (
            c.monthly_license
            + c.inference_cost_per_item * c.items_per_week * WEEKS_PER_MONTH
            + c.review_h_per_week * econ.hourly_cost * WEEKS_PER_MONTH
        )
        amort = c.build_cost / max(1, econ.amortization_months)
        # ΔOE negative = saving -> adds to profit
        profit = dt.amount - realized_oe - carrying - run_cost - amort
        lines.append(
            ValueLine(
                opportunity_id=opp.id,
                scenario=lvl,
                delta_t=dt.amount,
                delta_oe_realized=round(realized_oe, 2),
                delta_i_carrying=round(carrying, 2),
                run_cost=round(run_cost, 2),
                amortized_build=round(amort, 2),
                delta_profit=round(profit, 2),
            )
        )
        deltas[lvl] = (dt, di, doe)
        first_year[lvl] = round(_ramped(profit, amort, c.adoption_months, econ.horizon_months), 2)
    if item.effects and all(abs(ln.delta_t) < 1e-9 for ln in lines):
        notes.append(
            "simulated ΔT is zero: the effect does not move the constraint "
            "(value comes only from ΔI/ΔOE, if any)"
        )
    dts = [next(ln.delta_t for ln in lines if ln.scenario is lv) for lv in LEVELS]
    if item.effects and not (dts[0] <= dts[1] <= dts[2]):
        notes.append(
            "low/base/high ΔT not in order: simulation noise is larger than the "
            "difference between levels; use more replications before quoting a range"
        )
    if any(e.basis == "assumption" for e in item.effects):
        notes.append(
            "effects are assumptions: replace with pilot measurements before promising results"
        )
    return OpportunityValue(opp.id, lines, deltas, runs, first_year, notes)


def significant(a: SimResult, b: SimResult, z: float = 2.0) -> bool:
    """Throughput difference larger than z standard errors (replication-level variance)."""
    import statistics

    xa = [r.throughput_per_week for r in a.reps]
    xb = [r.throughput_per_week for r in b.reps]
    if len(xa) < 2 or len(xb) < 2:
        return True
    se = (statistics.variance(xa) / len(xa) + statistics.variance(xb) / len(xb)) ** 0.5
    diff = abs(statistics.fmean(xb) - statistics.fmean(xa))
    return diff > z * se if se > 0 else diff > 1e-9


def _ramped(monthly_profit: float, amort: float, ramp: int, horizon: int) -> float:
    """First-horizon value with a linear adoption ramp on the benefit side."""
    benefit = monthly_profit + amort  # amortization runs from month 1 regardless of ramp
    total = 0.0
    for m in range(1, horizon + 1):
        share = min(1.0, m / ramp) if ramp > 0 else 1.0
        total += benefit * share - amort
    return total


def mirage_ledger(items: list[OpportunityInput]) -> list[MirageEntry]:
    out = []
    for it in items:
        if it.realization_path is None and (
            it.claimed_oe_saving != 0 or it.capacity_released_h > 0
        ):
            out.append(
                MirageEntry(
                    opportunity_id=it.opportunity.id,
                    capacity_released_h=it.capacity_released_h,
                    claimed_amount=it.claimed_oe_saving,
                    reason="no realization path (attrition, contractor/overtime cut, licence "
                    "termination or redeployment to the constraint): valued at 0",
                )
            )
    return out


def value_portfolio(
    graph: FlowGraph,
    items: list[OpportunityInput],
    econ: Economics,
    sims: SimSettings | None = None,
    model_id: str = "value-model",
) -> ValueReport:
    sims = sims or SimSettings()
    baseline = _sim(graph, {}, "baseline", sims)
    per = [value_opportunity(graph, it, econ, baseline, sims) for it in items]
    portfolio, parts = {}, {}
    all_effects = tuple(e for it in items for e in it.effects)
    for lvl in LEVELS:
        parts[lvl] = round(sum(ln.delta_t for p in per for ln in p.lines if ln.scenario is lvl), 2)
        if all_effects:
            g2, batch = apply_effects(graph, all_effects, lvl)
            res = _sim(g2, batch, f"portfolio ({lvl.value})", sims)
            d = (res.throughput.mean or 0) - (baseline.throughput.mean or 0)
            if not significant(baseline, res):
                d = 0.0
            portfolio[lvl] = round(d * WEEKS_PER_MONTH * econ.throughput_per_unit, 2)
        else:
            portfolio[lvl] = 0.0
    dedup = []
    if len(items) > 1 and abs(portfolio[ValueScenario.base] - parts[ValueScenario.base]) > 0.01:
        dedup.append(
            f"base ΔT together {portfolio[ValueScenario.base]:,.0f} vs sum of parts "
            f"{parts[ValueScenario.base]:,.0f} {econ.currency}/month: gains overlap on "
            "shared constraint capacity; report the joint figure"
        )
    lags = {it.costs.expected_lag for it in items}
    model = ValueModel(
        id=model_id,
        lines=[ln for p in per for ln in p.lines],
        mirage_ledger=mirage_ledger(items),
        dedup_notes=dedup,
        expected_lag="; ".join(sorted(lags)) or None,
        assumption=True,
        confidence=0.5,
    )
    return ValueReport(model, per, portfolio, parts, baseline)


_NOTES_DE = (
    (
        "effects are assumptions",
        "Effekte sind Annahmen: vor jeder Zusage durch Pilot-Messungen ersetzen",
    ),
    (
        "low/base/high ΔT not in order",
        "niedrig/Basis/hoch nicht in Reihenfolge: das Rauschen "
        "der Simulation ist größer als der Abstand der Stufen; "
        "mehr Läufe, bevor eine Spanne genannt wird",
    ),
    (
        "simulated ΔT is zero",
        "simulierter Durchsatzgewinn ist null: der Effekt bewegt den "
        "Engpass nicht (Wert höchstens über ΔI/ΔOE)",
    ),
)


def _note_de(text: str) -> str:
    for en, de in _NOTES_DE:
        if text.startswith(en):
            return de
    if ": simulated ΔT" in text and "within noise" in text:
        lvl = text.split(":")[0]
        return f"{lvl}: simulierter ΔT liegt im Rauschen (< 2 Standardfehler): mit 0 bewertet"
    if text.startswith("base ΔT together"):
        nums = [x for x in text.replace(",", "").split() if x.replace(".", "").isdigit()]
        if len(nums) >= 2:
            return (
                f"gemeinsamer Basis-ΔT {float(nums[0]):,.0f} gegen Summe der Einzelwerte "
                f"{float(nums[1]):,.0f} pro Monat: die Gewinne überlappen am selben Engpass; "
                "der gemeinsame Wert gilt"
            )
    return text


def to_markdown(r: ValueReport, econ: Economics, lang: str = "en") -> str:
    cur = econ.currency
    h = {
        "en": (
            "Opportunity",
            "Scenario",
            "ΔT",
            "ΔOE real.",
            "ΔI carrying (−=saving)",
            "Run cost",
            "Build/mo",
            "ΔProfit/mo",
            "First year",
            "Mirage ledger",
            "Portfolio ΔT/mo",
            "Notes",
        ),
        "de": (
            "Chance",
            "Szenario",
            "ΔT",
            "ΔOE realisiert",
            "ΔI Kapitalkosten (−=Ersparnis)",
            "Laufkosten",
            "Aufbau/Mo",
            "ΔGewinn/Mo",
            "Erstes Jahr",
            "Schein-Einsparungen",
            "Portfolio ΔT/Mo",
            "Hinweise",
        ),
    }[lang]
    out = [f"| {' | '.join(h[:9])} |", "|" + "---|" * 9]
    for p in r.per_opportunity:
        for ln in p.lines:
            out.append(
                f"| {p.opportunity_id} | {ln.scenario.value} | {ln.delta_t:,.0f} | "
                f"{ln.delta_oe_realized:,.0f} | {ln.delta_i_carrying:,.0f} | "
                f"{ln.run_cost:,.0f} | {ln.amortized_build:,.0f} | "
                f"**{ln.delta_profit:,.0f}** | {p.first_year[ln.scenario]:,.0f} |"
            )
    out += [
        "",
        f"{h[10]} ({cur}): " + ", ".join(f"{k.value} {v:,.0f}" for k, v in r.portfolio.items()),
    ]
    tr = _note_de if lang == "de" else (lambda x: x)
    out += [f"- {tr(d)}" for d in r.model.dedup_notes]
    if r.model.mirage_ledger:
        out += ["", f"**{h[9]}:**"]
        out += [
            f"- {m.opportunity_id}: {m.capacity_released_h:g} h/week, claimed "
            f"{m.claimed_amount:,.0f} {cur}/month → 0 ({m.reason})"
            for m in r.model.mirage_ledger
        ]
    notes = [f"{p.opportunity_id}: {tr(n)}" for p in r.per_opportunity for n in p.notes]
    if notes:
        out += ["", f"**{h[11]}:**", *[f"- {n}" for n in notes]]
    if r.model.expected_lag:
        lag = r.model.expected_lag
        if lang == "de":
            lag = lag.replace(
                "leading indicators in 2–4 weeks; money in 1–3 months",
                "Frühindikatoren nach 2–4 Wochen; Geld nach 1–3 Monaten",
            )
        out += ["", f"{'Verzögerung' if lang == 'de' else 'Lag'}: {lag}"]
    return "\n".join(out)
