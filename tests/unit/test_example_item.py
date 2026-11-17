"""M0-13c: the worked example in docs/eval/example-item.md.

The example is synthetic. Its JSON block must validate as a gold item, and
its text_hash must be the SHA-256 of the source text quoted in it, so the
document cannot drift from the schema.
"""

import hashlib
import json
import re
from pathlib import Path

from utux.evalkit.gold import GoldItem

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "eval" / "example-item.md"


def _text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def _item() -> GoldItem:
    (block,) = re.findall(r"^```json\n(.*?)^```", _text(), re.MULTILINE | re.DOTALL)
    return GoldItem.validate_document(json.loads(block), str(EXAMPLE))


def _source_text() -> str:
    """The quoted line after the "**Source [1]**" heading, without the "> "."""
    lines = _text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("**Source [1]**"))
    (quote,) = [line for line in lines[start + 1 : start + 4] if line.startswith("> ")]
    return quote[2:]


def test_the_json_block_validates() -> None:
    item = _item()
    assert item.item_id == "G9100"
    assert [claim.claim_id for claim in item.claims] == ["G9100-c1", "G9100-c2"]


def test_text_hash_matches_the_quoted_source_text() -> None:
    expected = "sha256:" + hashlib.sha256(_source_text().encode("utf-8")).hexdigest()
    for claim in _item().claims:
        for pair in claim.pairs:
            assert pair.text_hash == expected


def test_evidence_offsets_point_at_the_quoted_sentences() -> None:
    source = _source_text()
    c1, c2 = _item().claims
    (span1,) = c1.pairs[0].evidence_spans
    (span2,) = c2.pairs[0].evidence_spans
    assert source[span1.offsets[0] : span1.offsets[1]].startswith("On the SynthImg benchmark")
    assert source[span2.offsets[0] : span2.offsets[1]] == (
        "Inference is 1.4 times faster than Method Beta on the same hardware."
    )


def test_claim_spans_point_into_the_text_unit() -> None:
    item = _item()
    c1, c2 = item.claims
    assert item.text_unit[c1.span[0] : c1.span[1]] == c1.text[:-1]
    assert item.text_unit[c2.span[0] : c2.span[1]] == "and it is twice as fast at inference"
