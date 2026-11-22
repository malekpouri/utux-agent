"""M0-15a: annotation tooling: batches, import, merge, and the offline page.

Everything here is synthetic: the texts, sources, claims and labels were
written for these tests and are not gold-standard labels. The tooling
handles labels made by people and never writes, suggests or changes one;
these tests stand in for the people.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, GoldSetError
from utux.evalkit.annotation import (
    Adjudication,
    AnnotationBatch,
    AnnotationPool,
    ExtractionWork,
    LabellingWork,
    Passage,
    Phase,
    ReferenceClaims,
    export_batch,
    extraction_agreement,
    labelling_agreement,
    merge_extraction,
    merge_labelling,
    page_text,
    read_work,
    release_text,
    with_splits,
    write_annotation_page,
)
from utux.evalkit.gold import GoldItem, GoldSplit, check_release
from utux.schemas.claim_ledger import CheckedText
from utux.sources.passages import split_passages

TEXT = "Method A outperforms method B on dataset X [1]. Method A is fast."
SOURCE_TEXT = "We compare A and B. A beats B on dataset X. A is slow."
# The passages come from the shared splitter (M2-02, ADR-0015).
P1, P2, P3 = (p.passage_id for p in split_passages(SOURCE_TEXT, CheckedText.ABSTRACT))


def _pool(**item: Any) -> AnnotationPool:
    base: dict[str, Any] = {
        "item_id": "G0001",
        "domain": "ml",
        "origin": "natural",
        "hard_case": None,
        "text_unit": TEXT,
        "sources": [
            {
                "source_id": "doi:10.0000/synthetic",
                "source_group": "sg-0001",
                "checked_text": "abstract",
                "extraction_quality": "clean",
                "text": SOURCE_TEXT,
            }
        ],
    }
    base.update(item)
    return AnnotationPool.validate_document(
        {"schema_version": 1, "gold_version": "0.1", "items": [base]}, "pool.json"
    )


def _perturbed_pool() -> AnnotationPool:
    return _pool(
        origin="perturbed",
        hard_case="number_wrong_context",
        hidden={
            "target_error": "overgeneralisation",
            "secondary_errors": [],
            "error_class": "single_error",
            "confirmed_by": "a01",
            "source_item": "G0098",
        },
    )


CLAIM_1 = {
    "span": [0, 47],
    "text": "Method A outperforms method B on dataset X.",
    "kind": "finding",
    "citations": ["doi:10.0000/synthetic"],
}
CLAIM_2 = {"span": [48, 65], "text": "Method A is fast.", "kind": "method", "citations": []}


def _extraction_work(batch: Any, claims: list[dict[str, Any]], **item: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": "claim_extraction",
        "batch_id": batch.batch_id,
        "batch_hash": batch.batch_hash,
        "annotator": batch.annotator,
        "items": [{"item_id": "G0001", "claims": claims, "flag": None, "minutes": 9, **item}],
    }


def _references(
    pool: AnnotationPool, a: list[Any] | None = None, b: list[Any] | None = None
) -> Any:
    claims = [CLAIM_1, CLAIM_2]
    batch_a = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    batch_b = export_batch(pool, Phase.CLAIM_EXTRACTION, "a07", "b01")
    work_a = read_work(batch_a, _extraction_work(batch_a, a if a is not None else claims))
    work_b = read_work(batch_b, _extraction_work(batch_b, b if b is not None else claims))
    return merge_extraction(pool, work_a, work_b)


PAIR = {
    "source_id": "doi:10.0000/synthetic",
    "evidence_spans": [{"passage_id": P2, "offsets": [20, 43]}],
    "agreement_label": "entails",
    "scope_flags": [],
    "note": None,
}


def _labelling_work(batch: Any, **changes: Any) -> dict[str, Any]:
    claim_1 = {
        "claim_id": "G0001-c1",
        "status": changes.get("status", "verified"),
        "expert_would_review": False,
        "note": None,
        "pairs": [{**PAIR, **changes.get("pair", {})}],
    }
    claim_2 = {
        "claim_id": "G0001-c2",
        "status": "insufficient_evidence",
        "expert_would_review": False,
        "note": None,
        "pairs": [],
    }
    return {
        "schema_version": 1,
        "phase": "labelling",
        "batch_id": batch.batch_id,
        "batch_hash": batch.batch_hash,
        "annotator": batch.annotator,
        "items": [
            {"item_id": "G0001", "claims": [claim_1, claim_2], "flag": None, "minutes": None}
        ],
    }


def _labelled(
    pool: AnnotationPool, a: dict[str, Any] | None = None, b: dict[str, Any] | None = None
):
    references = _references(pool).references
    batch_a = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    batch_b = export_batch(pool, Phase.LABELLING, "a07", "b02", references=references)
    work_a = read_work(batch_a, _labelling_work(batch_a, **(a or {})))
    work_b = read_work(batch_b, _labelling_work(batch_b, **(b or {})))
    return references, work_a, work_b


def _adjudication(phase: str, **decisions: Any) -> Adjudication:
    return Adjudication.validate_document(
        {
            "schema_version": 1,
            "phase": phase,
            "adjudicator": "a01",
            "extraction": decisions.get("extraction", []),
            "claims": decisions.get("claims", []),
            "pairs": decisions.get("pairs", []),
            "ambiguous": decisions.get("ambiguous", []),
        },
        "adjudication.json",
    )


# Export


def test_a_batch_shows_the_text_and_sources_and_hides_what_annotators_must_not_see() -> None:
    batch = export_batch(_perturbed_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    document = json.loads(batch.to_json())
    (item,) = document["items"]
    assert item["text_unit"] == TEXT
    (source,) = item["sources"]
    assert source["text"] == SOURCE_TEXT
    assert source["text_hash"].startswith("sha256:")
    # Never shown to annotators: the hidden record, and what would tell them
    # how the item was made.
    for key in ("hidden", "origin", "hard_case"):
        assert key not in item
    assert "source_group" not in source
    assert item["claims"] == []
    assert document["annotator"] == "a03"


def test_the_batch_hash_binds_the_work_to_its_batch() -> None:
    pool = _pool()
    first = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    again = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    other = export_batch(pool, Phase.CLAIM_EXTRACTION, "a07", "b01")
    assert first.batch_hash == again.batch_hash
    assert first.batch_hash != other.batch_hash


def test_a_labelling_batch_holds_the_reference_claims_and_no_annotator_labels() -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    text = batch.to_json()
    (item,) = json.loads(text)["items"]
    assert [c["claim_id"] for c in item["claims"]] == ["G0001-c1", "G0001-c2"]
    assert item["claims"][0]["citations"] == ["doi:10.0000/synthetic"]
    # Neither annotator's own claim list nor any label is in the batch.
    assert "raw" not in text
    assert "a07" not in text


def test_a_labelling_batch_needs_the_reference_claims_of_every_item() -> None:
    with pytest.raises(GoldSetError, match="G0001"):
        export_batch(_pool(), Phase.LABELLING, "a03", "b02", references=None)


def test_an_annotator_id_must_be_pseudonymous() -> None:
    with pytest.raises(ContractValidationError):
        export_batch(_pool(), Phase.CLAIM_EXTRACTION, "alex", "b01")


def test_a_pools_passages_are_the_splitters() -> None:
    (source,) = _pool().items[0].sources
    assert source.passages == tuple(
        Passage(passage_id=p.passage_id, offsets=p.offsets)
        for p in split_passages(SOURCE_TEXT, CheckedText.ABSTRACT)
    )
    batch = export_batch(_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    assert [p.passage_id for p in batch.items[0].sources[0].passages] == [P1, P2, P3]


def test_a_pool_cannot_give_passages_of_its_own() -> None:
    source = {
        "source_id": "doi:10.0000/synthetic",
        "source_group": "sg-0001",
        "checked_text": "abstract",
        "extraction_quality": "clean",
        "text": SOURCE_TEXT,
        "passages": [{"passage_id": "p1", "offsets": [0, 19]}],
    }
    with pytest.raises(ContractValidationError) as raised:
        _pool(sources=[source])
    assert "unknown_key" in [p.code for p in raised.value.problems]


# Import


def _problems(batch: Any, work: dict[str, Any]) -> list[str]:
    with pytest.raises(ContractValidationError) as raised:
        read_work(batch, work)
    return [p.code for p in raised.value.problems]


def test_an_annotators_claim_list_is_read() -> None:
    batch = export_batch(_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    work = read_work(batch, _extraction_work(batch, [CLAIM_1, CLAIM_2]))
    (item,) = work.items
    assert [claim.text for claim in item.claims] == [CLAIM_1["text"], CLAIM_2["text"]]
    assert item.minutes == 9


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"annotator": "a07"}, "differs_from_batch"),
        ({"batch_hash": "sha256:" + "0" * 64}, "differs_from_batch"),
        ({"phase": "labelling"}, "differs_from_batch"),
        ({"items": []}, "missing_item"),
    ],
)
def test_work_for_another_batch_or_annotator_is_refused(change: dict[str, Any], code: str) -> None:
    batch = export_batch(_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    work = {**_extraction_work(batch, [CLAIM_1]), **change}
    assert code in _problems(batch, work)


@pytest.mark.parametrize(
    ("claim", "code"),
    [
        ({**CLAIM_1, "span": [0, 99]}, "span_out_of_range"),
        ({**CLAIM_1, "citations": ["doi:10.0000/other"]}, "unknown_source"),
        ({**CLAIM_1, "citations": ["doi:10.0000/synthetic"] * 2}, "duplicate_citation"),
        ({**CLAIM_1, "kind": "opinion"}, "enum"),
        ({**CLAIM_1, "text": ""}, "string_too_short"),
    ],
)
def test_a_listed_claim_is_checked_against_its_item(claim: dict[str, Any], code: str) -> None:
    batch = export_batch(_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    assert code in _problems(batch, _extraction_work(batch, [claim]))


def test_an_unknown_item_is_refused() -> None:
    batch = export_batch(_pool(), Phase.CLAIM_EXTRACTION, "a03", "b01")
    work = _extraction_work(batch, [CLAIM_1])
    work["items"].append({"item_id": "G0002", "claims": [], "flag": None, "minutes": None})
    assert "unknown_item" in _problems(batch, work)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"pair": {"source_id": "doi:10.0000/other"}}, "unknown_source"),
        (
            {"pair": {"evidence_spans": [{"passage_id": "p-unknown", "offsets": [0, 19]}]}},
            "unknown_passage",
        ),
        (
            {"pair": {"evidence_spans": [{"passage_id": P1, "offsets": [0, 10]}]}},
            "offsets_differ",
        ),
        ({"pair": {"agreement_label": "supports"}}, "enum"),
        ({"pair": {"scope_flags": ["overgeneralisation", "overgeneralisation"]}}, "duplicate_flag"),
        ({"status": "unverified"}, "enum"),
    ],
)
def test_labels_are_checked_against_the_batch(changes: dict[str, Any], code: str) -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    assert code in _problems(batch, _labelling_work(batch, **changes))


def test_every_reference_claim_and_pair_is_labelled() -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    work = _labelling_work(batch)
    work["items"][0]["claims"] = work["items"][0]["claims"][:1]
    assert "missing_claim" in _problems(batch, work)
    work = _labelling_work(batch)
    work["items"][0]["claims"][0]["pairs"] = []
    assert "missing_pair" in _problems(batch, work)


def test_a_claim_without_sources_must_be_insufficient_evidence() -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    work = _labelling_work(batch)
    work["items"][0]["claims"][1]["status"] = "verified"
    assert "raw_status_without_pairs" in _problems(batch, work)


def test_an_item_flagged_for_the_adjudicator_may_be_left_unlabelled() -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    work = _labelling_work(batch)
    work["items"][0].update(claims=[], flag="The source attached is the wrong paper.")
    (item,) = read_work(batch, work).items
    assert item.flag == "The source attached is the wrong paper."
    work["items"][0]["flag"] = None
    assert "missing_claim" in _problems(batch, work)


# Merge, phase 1


def test_agreeing_claim_lists_become_the_reference_claims() -> None:
    merged = _references(_pool())
    assert merged.disagreements == ()
    (item,) = merged.references.items
    assert [(c.claim_id, c.text, c.kind.value) for c in item.claims] == [
        ("G0001-c1", CLAIM_1["text"], "finding"),
        ("G0001-c2", CLAIM_2["text"], "method"),
    ]
    assert item.claim_extraction.adjudicated is False
    assert set(item.claim_extraction.raw) == {"a03", "a07"}


def test_differing_claim_lists_go_to_the_adjudicator_and_nothing_is_chosen() -> None:
    merged = _references(_pool(), b=[CLAIM_1])
    assert merged.references.items == ()
    (disagreement,) = merged.disagreements
    assert (disagreement.item_id, disagreement.level) == ("G0001", "claim_extraction")
    assert len(disagreement.values["a03"]) == 2
    assert len(disagreement.values["a07"]) == 1


def test_a_different_kind_alone_is_a_disagreement() -> None:
    merged = _references(_pool(), b=[CLAIM_1, {**CLAIM_2, "kind": "finding"}])
    (disagreement,) = merged.disagreements
    assert disagreement.level == "claim_extraction"


def test_the_adjudicators_claim_list_resolves_a_disagreement() -> None:
    pool = _pool()
    batch_a = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    batch_b = export_batch(pool, Phase.CLAIM_EXTRACTION, "a07", "b01")
    work_a = read_work(batch_a, _extraction_work(batch_a, [CLAIM_1, CLAIM_2]))
    work_b = read_work(batch_b, _extraction_work(batch_b, [CLAIM_1]))
    decision = {"item_id": "G0001", "claims": [CLAIM_1, CLAIM_2], "reason": "Synthetic reason."}
    merged = merge_extraction(
        pool, work_a, work_b, _adjudication("claim_extraction", extraction=[decision])
    )
    assert merged.disagreements == ()
    (item,) = merged.references.items
    assert item.claim_extraction.adjudicated is True
    assert item.claim_extraction.adjudication_reason == "Synthetic reason."
    assert item.adjudicator == "a01"
    assert len(item.claim_extraction.raw["a07"]) == 1


def test_a_flagged_item_goes_to_the_adjudicator() -> None:
    pool = _pool()
    batch_a = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    batch_b = export_batch(pool, Phase.CLAIM_EXTRACTION, "a07", "b01")
    work_a = read_work(batch_a, _extraction_work(batch_a, [CLAIM_1, CLAIM_2]))
    work_b = read_work(batch_b, _extraction_work(batch_b, [], flag="Unreadable source."))
    (disagreement,) = merge_extraction(pool, work_a, work_b).disagreements
    assert disagreement.level == "flagged"
    assert disagreement.values["a07"] == "Unreadable source."


def test_the_two_works_must_be_of_two_annotators_and_one_batch() -> None:
    pool = _pool()
    batch = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    work = read_work(batch, _extraction_work(batch, [CLAIM_1]))
    with pytest.raises(GoldSetError, match="two annotators"):
        merge_extraction(pool, work, work)


# Merge, phase 2


def test_agreeing_labels_become_a_valid_gold_item() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(pool)
    merged = merge_labelling(pool, references, work_a, work_b)
    assert merged.disagreements == ()
    (item,) = merged.items
    # The split is set only when the release is frozen (PR #48 review).
    assert item.split is None
    claim = item.claims[0]
    assert (claim.status.value, claim.adjudicated) == ("verified", False)
    assert set(claim.raw) == {"a03", "a07"}
    (pair,) = claim.pairs
    assert (pair.pair_id, pair.source_group, pair.agreement_label.value) == (
        "G0001-c1-s1",
        "sg-0001",
        "entails",
    )
    assert item.annotation.adjudicator is None
    assert [p.code for p in check_release(merged.items).problems] == ["split_not_set"]
    assert check_release(with_splits(merged.items, {"G0001": GoldSplit.DEV})).problems == ()


def test_a_differing_label_goes_to_the_adjudicator_and_no_item_is_made() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(
        pool, b={"status": "partially_supported", "pair": {"agreement_label": "partial"}}
    )
    merged = merge_labelling(pool, references, work_a, work_b)
    assert merged.items == ()
    levels = {(d.level, d.target) for d in merged.disagreements}
    assert levels == {("claim", "G0001-c1"), ("pair", "G0001-c1-s1")}


def test_the_adjudicators_decisions_complete_the_item() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(
        pool, b={"status": "partially_supported", "pair": {"agreement_label": "partial"}}
    )
    adjudication = _adjudication(
        "labelling",
        claims=[
            {
                "claim_id": "G0001-c1",
                "status": "partially_supported",
                "expert_would_review": True,
                "reason": "Synthetic reason.",
            }
        ],
        pairs=[
            {
                "pair_id": "G0001-c1-s1",
                "evidence_spans": [{"passage_id": P2, "offsets": [20, 43]}],
                "agreement_label": "partial",
                "scope_flags": ["overgeneralisation"],
                "reason": "Synthetic reason.",
            }
        ],
        ambiguous=["G0001-c2"],
    )
    merged = merge_labelling(pool, references, work_a, work_b, adjudication)
    assert merged.disagreements == ()
    (item,) = merged.items
    claim, other = item.claims
    assert (claim.status.value, claim.expert_would_review, claim.adjudicated) == (
        "partially_supported",
        True,
        True,
    )
    assert claim.pairs[0].scope_flags[0].value == "overgeneralisation"
    assert other.ambiguous is True
    assert item.annotation.adjudicator == "a01"
    # The raw labels are kept unchanged beside the adjudicated ones.
    assert claim.raw["a03"].status.value == "verified"


def test_the_hidden_record_and_origin_come_from_the_pool() -> None:
    pool = _perturbed_pool()
    references, work_a, work_b = _labelled(pool)
    (item,) = merge_labelling(pool, references, work_a, work_b).items
    assert item.origin.value == "perturbed"
    assert item.hard_case is not None
    assert item.hidden is not None


def test_a_merged_item_written_as_a_release_line_reads_back() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(pool)
    (item,) = merge_labelling(pool, references, work_a, work_b).items
    line = release_text([item])
    assert line.count("\n") == 1
    # A natural item has no hidden key at all, as the gold item requires.
    assert '"hidden"' not in line
    assert GoldItem.validate_document(json.loads(line), "line") == item


def test_with_splits_sets_the_split_chosen_for_each_item() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(pool)
    items = merge_labelling(pool, references, work_a, work_b).items
    (moved,) = with_splits(items, {"G0001": GoldSplit.TEST})
    assert moved.split is GoldSplit.TEST
    assert moved.claims == items[0].claims


# The offline page


def test_the_page_is_one_offline_file() -> None:
    text = page_text()
    assert text.startswith("<!doctype html>")
    # A content security policy blocks every request the page could make.
    assert "default-src 'none'" in text
    for forbidden in ("http://", "https://", "fetch(", "XMLHttpRequest", "WebSocket", "<link"):
        assert forbidden not in text, forbidden
    assert "<script src" not in text


def test_the_page_preselects_no_label() -> None:
    text = page_text()
    assert " checked" not in text
    assert " selected" not in text


def test_write_annotation_page_copies_the_page(tmp_path: Path) -> None:
    path = write_annotation_page(tmp_path)
    assert path.read_text(encoding="utf-8") == page_text()


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the page's logic is checked where it is")
    return node


def _run_page_logic(tmp_path: Path, batch: Any, fill: str) -> dict[str, Any]:
    page = write_annotation_page(tmp_path)
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(batch.to_json(), encoding="utf-8")
    script = f"""
const fs = require("fs");
const page = fs.readFileSync({json.dumps(str(page))}, "utf8");
const logic = page.split('<script id="logic">')[1].split("</script>")[0];
const UtuxAnnotation = new Function(logic + "\\nreturn UtuxAnnotation;")();
const batch = JSON.parse(fs.readFileSync({json.dumps(str(batch_file))}, "utf8"));
const work = UtuxAnnotation.newWork(batch);
const blank = JSON.parse(JSON.stringify(work));
{fill}
const result = UtuxAnnotation.exportWork(batch, work);
const shown = work.shown === undefined ? null : work.shown;
process.stdout.write(JSON.stringify({{blank: blank, result: result, shown: shown}}));
"""
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, check=False, timeout=30
    )
    assert done.returncode == 0, done.stderr
    output: dict[str, Any] = json.loads(done.stdout)
    return output


def test_the_page_starts_with_no_label_and_exports_what_import_accepts(tmp_path: Path) -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    fill = """
const item = work.items[0];
const [c1, c2] = item.claims;
c1.status = "verified"; c1.expert_would_review = false;
c1.pairs[0].agreement_label = "entails";
c1.pairs[0].evidence_spans = [{passage_id: batch.items[0].sources[0].passages[1].passage_id,
                                offsets: [20, 43]}];
c2.status = "insufficient_evidence"; c2.expert_would_review = false;
"""
    output = _run_page_logic(tmp_path, batch, fill)
    blank_claim = output["blank"]["items"][0]["claims"][0]
    assert blank_claim["status"] is None
    assert blank_claim["expert_would_review"] is None
    assert blank_claim["pairs"][0]["agreement_label"] is None
    assert output["result"]["errors"] == []
    work = read_work(batch, json.loads(output["result"]["json"]))
    assert work.items[0].claims[0].status.value == "verified"


def test_the_page_does_not_export_while_a_label_is_missing(tmp_path: Path) -> None:
    pool = _pool()
    references = _references(pool).references
    batch = export_batch(pool, Phase.LABELLING, "a03", "b02", references=references)
    output = _run_page_logic(tmp_path, batch, "work.items[0].claims[0].status = 'verified';")
    assert output["result"]["json"] is None
    assert any("G0001-c1" in error for error in output["result"]["errors"])


def test_the_page_exports_a_claim_list(tmp_path: Path) -> None:
    pool = _pool()
    batch = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    fill = f"""
work.items[0].claims.push({json.dumps(CLAIM_1)});
work.items[0].minutes = 7;
"""
    output = _run_page_logic(tmp_path, batch, fill)
    assert output["blank"]["items"][0]["claims"] == []
    work = read_work(batch, json.loads(output["result"]["json"]))
    assert work.items[0].claims[0].text == CLAIM_1["text"]


# Fixtures of the annotation contracts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONTRACTS = {
    "annotation_pool": AnnotationPool,
    "annotation_batch": AnnotationBatch,
    "extraction_work": ExtractionWork,
    "labelling_work": LabellingWork,
    "adjudication": Adjudication,
    "reference_claims": ReferenceClaims,
}


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_valid_fixtures_load_and_round_trip(name: str) -> None:
    for path in sorted((FIXTURES / name / "valid").iterdir()):
        document = json.loads(path.read_text(encoding="utf-8"))
        model = CONTRACTS[name].validate_document(document, path.name)
        assert json.loads(model.to_json()) == document, path.name


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_invalid_fixtures_are_refused(name: str) -> None:
    paths = sorted((FIXTURES / name / "invalid").iterdir())
    assert paths
    for path in paths:
        with pytest.raises(ContractValidationError):
            CONTRACTS[name].validate_document(json.loads(path.read_text("utf-8")), path.name)


def test_the_documented_adjudication_example_is_valid() -> None:
    text = (Path(__file__).resolve().parents[2] / "docs" / "annotation-tooling.md").read_text(
        encoding="utf-8"
    )
    example = text.split("### The adjudication file", 1)[1].split("```json\n", 1)[1]
    document = json.loads(example.split("```", 1)[0])
    assert (
        Adjudication.validate_document(document, "docs/annotation-tooling.md").adjudicator == "a01"
    )


def test_with_splits_needs_a_split_for_every_item() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(pool)
    with pytest.raises(GoldSetError, match="split"):
        with_splits(merge_labelling(pool, references, work_a, work_b).items, {})


# Each annotator's kind is kept (PR #48 review)


def test_each_annotators_kind_is_kept_in_the_raw_claim_lists() -> None:
    (item,) = _references(_pool()).references.items
    kinds = {claim.kind.value for claim in item.claim_extraction.raw["a03"]}
    assert kinds == {"finding", "method"}


# Agreement before adjudication (PR #48 review)


def _extraction_works(b: list[Any]) -> tuple[Any, Any]:
    pool = _pool()
    batch_a = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    batch_b = export_batch(pool, Phase.CLAIM_EXTRACTION, "a07", "b01")
    return (
        read_work(batch_a, _extraction_work(batch_a, [CLAIM_1, CLAIM_2])),
        read_work(batch_b, _extraction_work(batch_b, b)),
    )


def test_claim_extraction_agreement_is_computed_from_the_two_works() -> None:
    # a03 lists two claims, a07 one of them: 2 * 1 / (2 + 1) = 2/3.
    first, second = _extraction_works([CLAIM_1])
    agreement = extraction_agreement(first, second)
    assert (agreement.first, agreement.second, agreement.matched) == (2, 1, 1)
    assert agreement.share == pytest.approx(2 / 3)


def test_an_item_flagged_by_either_annotator_is_left_out_of_agreement() -> None:
    first, second = _extraction_works([])
    flagged = second.model_copy(
        update={"items": (second.items[0].model_copy(update={"flag": "Broken."}),)}
    )
    agreement = extraction_agreement(first, flagged)
    assert (agreement.first, agreement.second, agreement.matched) == (0, 0, 0)


def test_label_agreement_is_computed_from_the_two_works_before_adjudication() -> None:
    pool = _pool()
    references, work_a, work_b = _labelled(
        pool, b={"status": "partially_supported", "pair": {"agreement_label": "partial"}}
    )
    report = labelling_agreement(pool, references, work_a, work_b)
    # Status: G0001-c1 verified against partially_supported, G0001-c2 the same: 1 of 2.
    assert report.status.raw_agreement == pytest.approx(0.5)
    # The one pair: entails against partial.
    assert report.agreement_label.raw_agreement == pytest.approx(0.0)
    # The same passage marked by both: F1 1.
    assert report.evidence_spans is not None
    assert report.evidence_spans.mean_f1 == pytest.approx(1.0)
    # Claim extraction from the raw lists of the reference claims: both listed the same two.
    assert (report.claim_extraction.first, report.claim_extraction.matched) == (2, 2)


# Offsets are code points everywhere (M2-02, rule 16 of M2)

ASTRAL = "Let \U0001d465 be large [1]. It holds."


def test_the_page_stores_a_span_in_code_points_where_the_browser_counts_utf16(
    tmp_path: Path,
) -> None:
    pool = _pool(text_unit=ASTRAL)
    batch = export_batch(pool, Phase.CLAIM_EXTRACTION, "a03", "b01")
    # In the browser the claim "Let x be large [1]." ends at UTF-16 unit 20;
    # in code points it ends at 19.
    fill = """
const span = UtuxAnnotation.spanFromSelection(batch.items[0].text_unit, 0, 20);
work.items[0].claims.push({span: span, text: "Let x be large.", kind: "finding",
                           citations: ["doi:10.0000/synthetic"]});
"""
    output = _run_page_logic(tmp_path, batch, fill)
    assert output["result"]["errors"] == []
    work = read_work(batch, json.loads(output["result"]["json"]))
    (claim,) = work.items[0].claims
    assert claim.span == (0, 19)
    assert ASTRAL[0:19] == "Let \U0001d465 be large [1]."


def test_the_page_reads_passages_by_code_points(tmp_path: Path) -> None:
    text = "Let \U0001d465 be large. Then it holds."
    source = {**_pool().items[0].sources[0].model_dump(mode="json"), "text": text}
    batch = export_batch(_pool(sources=[source]), Phase.CLAIM_EXTRACTION, "a03", "b01")
    fill = """
const source = batch.items[0].sources[0];
work.shown = source.passages.map(function (p) {
  return UtuxAnnotation.sliceByCodePoints(source.text, p.offsets[0], p.offsets[1]);
});
"""
    output = _run_page_logic(tmp_path, batch, fill)
    assert output["shown"] == ["Let \U0001d465 be large.", "Then it holds."]
