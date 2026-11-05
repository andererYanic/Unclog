import re
from pathlib import Path

import pytest

from unclog import cli
from unclog.i18n import DOMAIN_LABELS, MESSAGES, domain_label, t
from unclog.schemas.diagnosis import DomainName

CASES = Path(__file__).parent.parent / "evals" / "cases"

# English phrases produced by our own code (not client data) that must not appear in DE reports
ENGLISH_MARKERS = [
    r"\bof capacity\b",
    r"\bwait before\b",
    r"\bqueued\b",
    r"\bworse\b",
    r"\bvs benchmark\b",
    r"\bNo signal above\b",
    r"\bnot assessed\b",
    r"\bPolicy:",
    r"\bMarket:",
    r"\bthroughput\b",
    r"\bdownstream of\b",
    r"\bstatement\(s\)",
    r"\bBinding constraint\b",
    r"\bDiscovery actions\b",
    r"\bCapacity is ample\b",
    r"\bRule found\b",
    r"\bcandidate\b",
    r"\bclear\b",
]


def test_catalog_complete():
    for key, entry in MESSAGES.items():
        assert set(entry) == {"en", "de"}, key
        assert re.findall(r"{(\w+)}", entry["en"]) == re.findall(r"{(\w+)}", entry["de"]) or sorted(
            re.findall(r"{(\w+)}", entry["en"])
        ) == sorted(re.findall(r"{(\w+)}", entry["de"])), key
    assert {d.value for d in DomainName} == set(DOMAIN_LABELS)
    assert domain_label("fulfillment", "de") == "Auftragsabwicklung"
    assert t("queued", "fr", q=3) == "3 queued"  # unknown language falls back to English


@pytest.mark.parametrize(
    "case",
    [
        "backend_fulfillment_flood",
        "hidden_policy_approval",
        "market_after_elevation",
        "conflicting_testimony",
    ],
)
def test_german_reports_have_no_english_from_our_code(case, tmp_path, capsys):
    cli.main(["pipeline", "--case", str(CASES / case), "--out", str(tmp_path), "--lang", "de"])
    capsys.readouterr()
    for name in ("01-executive-summary.md", "02-constraint-report.md"):
        text = (tmp_path / name).read_text()
        hits = [m for m in ENGLISH_MARKERS if re.search(m, text)]
        assert not hits, f"{case}/{name}: {hits}"
