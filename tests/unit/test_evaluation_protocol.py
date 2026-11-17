"""M0-14: the protocol restates RFC-002's thresholds without changing them."""

import re
from pathlib import Path

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
