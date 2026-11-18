"""M0-14: the protocol restates RFC-002's thresholds without changing them."""

import re
from pathlib import Path

from utux.evalkit.intervals import exact_binomial_interval

ROOT = Path(__file__).resolve().parents[2]


def _threshold_rows(path: Path, heading: str) -> list[tuple[str, ...]]:
    text = path.read_text(encoding="utf-8")
    section = text[text.index(heading) :]
    table = re.search(r"^\| Metric \|.*?\n\| --- .*?\n((?:\|.*\n)+)", section, re.MULTILINE)
    assert table is not None
    return [
        tuple(cell.strip().lower() for cell in row.strip().strip("|").split("|"))
        for row in table.group(1).splitlines()
    ]


def test_h3_thresholds_equal_those_of_rfc_002() -> None:
    rfc = _threshold_rows(ROOT / "docs/rfc/RFC-002.md", "### Proposed thresholds for hypothesis H3")
    protocol = _threshold_rows(ROOT / "docs/eval/protocol.md", "### 4.1 Hypothesis H3")
    assert protocol == rfc
    assert len(rfc) == 5


def _section(path: Path, start: str, end: str) -> str:
    text = path.read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end)]


def _percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def test_rfc_002_section_3_states_the_two_sided_bounds_correctly() -> None:
    sizing = _section(
        ROOT / "docs/rfc/RFC-002.md",
        "### Why the statuses are not equal in size",
        "### Hard cases",
    )
    # False-verified rate: 10 of 200 and 6 of 120 wrong (5%).
    upper_200 = exact_binomial_interval(10, 200).upper
    upper_120 = exact_binomial_interval(6, 120).upper
    assert _percent(upper_200) == "9.0%"
    assert upper_120 > 0.10
    assert "9.0%" in sizing
    # Critical miss rate on 150 items: no misses gives 1 - 0.025 ** (1/150).
    assert _percent(exact_binomial_interval(0, 150).upper) == "2.4%"
    assert "2.4%" in sizing
    # Up to 2 misses meet both conditions (point at most 2%, upper end at
    # most 5%); 3 misses do not.
    two, three = exact_binomial_interval(2, 150), exact_binomial_interval(3, 150)
    assert 2 / 150 <= 0.02
    assert two.upper <= 0.05
    assert 3 / 150 <= 0.02
    assert three.upper > 0.05
    assert _percent(two.upper) == "4.7%"
    assert _percent(three.upper) == "5.7%"
    for stated in ("4.7%", "5.7%", "two-sided"):
        assert stated in sizing
    assert "roughly 3 divided by" not in sizing


def test_critical_miss_threshold_has_an_interval_condition() -> None:
    rows = _threshold_rows(
        ROOT / "docs/rfc/RFC-002.md", "### Proposed thresholds for hypothesis H3"
    )
    critical = next(row for row in rows if row[0] == "critical miss rate")
    assert critical[2] == "at most 2%, with the upper end of the 95% interval at most 5%"
