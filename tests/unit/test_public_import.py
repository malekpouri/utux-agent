"""Tests of the import of public datasets into gold v0 items (task M0-15b).

Every dataset file here is synthetic: written by hand in the shape of the
SciFact and SciClaimEval releases, with made-up claims, abstracts and
tables. No real dataset item is used.

The items are gold items of origin `public` with a provenance block
(RFC-002, section 4, option (a)); the maintainer's decisions of the review
of pull request #55 set the licences, the drop of NC and SA samples, the
steps not scored and the source groups.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from utux.errors import GoldSetError
from utux.evalkit.gold import (
    Domain,
    GoldItem,
    GoldStatus,
    NotScored,
    Origin,
    PublicDataset,
    read_gold_release,
)
from utux.evalkit.public import (
    DropReason,
    PublicImport,
    check_public_item,
    import_public,
    render_table,
    summarize,
    write_public_import,
)
from utux.schemas.claim_ledger import CheckedText, ExtractionQuality, SourceLabel
from utux.sources.passages import split_passages

# Synthetic SciFact ------------------------------------------------------------

ABSTRACT_1 = [
    "Synthetic drug A was given to 40 mice.",
    "Drug A lowered blood pressure in all of them.",
    "No side effects were seen.",
]
ABSTRACT_2 = ["Synthetic drug B was tested in 12 rats.", "Drug B raised heart rate."]
ABSTRACT_3 = ["A synthetic survey of 9 clinics.", "It reports staffing only."]


def _jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _corpus() -> list[object]:
    return [
        {"doc_id": 101, "title": "Synthetic A", "abstract": ABSTRACT_1, "structured": False},
        {"doc_id": 102, "title": "Synthetic B", "abstract": ABSTRACT_2, "structured": False},
        {"doc_id": 103, "title": "Synthetic C", "abstract": ABSTRACT_3, "structured": False},
    ]


def _support(*sentences: int) -> dict[str, object]:
    return {"sentences": list(sentences), "label": "SUPPORT"}


def _contradict(*sentences: int) -> dict[str, object]:
    return {"sentences": list(sentences), "label": "CONTRADICT"}


def _claim(
    claim_id: int, evidence: dict[str, object], cited: list[int], text: str = ""
) -> dict[str, object]:
    return {
        "id": claim_id,
        "claim": text or f"Synthetic claim {claim_id}.",
        "evidence": evidence,
        "cited_doc_ids": cited,
    }


def _scifact(tmp_path: Path, train: list[object], dev: list[object] | None = None) -> Path:
    root = tmp_path / "scifact"
    _jsonl(root / "data" / "corpus.jsonl", _corpus())
    _jsonl(root / "data" / "claims_train.jsonl", train)
    _jsonl(root / "data" / "claims_dev.jsonl", dev or [])
    # The test split has no public labels; it must never be opened.
    (root / "data" / "claims_test.jsonl").write_text("{not json\n", encoding="utf-8")
    return root


def _one(directory: Path, dataset: PublicDataset) -> tuple[GoldItem, PublicImport]:
    result = import_public(dataset, directory)
    assert len(result.items) == 1, result.dropped
    return result.items[0], result


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def test_scifact_support_is_a_public_gold_item_with_entails_and_verified(tmp_path: Path) -> None:
    root = _scifact(tmp_path, [_claim(1, {"101": [_support(1)]}, [101], "Drug A works.")])
    item, result = _one(root, PublicDataset.SCIFACT)
    text = " ".join(ABSTRACT_1)
    assert item.item_id == "G10000001"
    assert (item.gold_version, item.split, item.origin) == ("0.1", None, Origin.PUBLIC)
    assert item.domain is Domain.BIOMEDICINE
    assert item.hard_case is None
    assert item.annotation is None
    assert item.text_unit == "Drug A works."
    (claim,) = item.claims
    assert claim.claim_id == "G10000001-c1"
    assert claim.span == (0, len("Drug A works."))
    assert (claim.kind, claim.expert_would_review, claim.raw) == (None, None, {})
    assert claim.status is GoldStatus.VERIFIED
    (pair,) = claim.pairs
    assert pair.pair_id == "G10000001-c1-s1"
    assert pair.source_id == "scifact-doc-101"
    # Claims that share an abstract share its group (maintainer decision 14).
    assert pair.source_group == "scifact-doc-101"
    assert pair.text_hash == _hash(text)
    assert pair.checked_text is CheckedText.ABSTRACT
    assert pair.extraction_quality is ExtractionQuality.CLEAN
    assert pair.agreement_label is SourceLabel.ENTAILS
    assert pair.scope_flags == ()
    start = text.index(ABSTRACT_1[1])
    passage = next(p for p in split_passages(text, CheckedText.ABSTRACT) if p.offsets[0] == start)
    assert [(s.passage_id, s.offsets) for s in pair.evidence_spans] == [
        (passage.passage_id, (start, start + len(ABSTRACT_1[1])))
    ]
    provenance = item.provenance
    assert provenance is not None
    assert provenance.dataset is PublicDataset.SCIFACT
    assert (provenance.dataset_split, provenance.original_id) == ("train", "1")
    # The most restrictive statement until AllenAI clarifies (decision 1).
    assert provenance.licence == "CC BY-NC 2.0"
    assert provenance.text_redistributable is False
    assert provenance.evidence_modified is False
    assert provenance.not_scored == (NotScored.S4,)
    assert result.texts == {_hash(text): text}
    assert summarize(result)["rationale_sentences_cut"] == 0


def test_a_rationale_sentence_the_splitter_cuts_gives_one_span_per_passage(
    tmp_path: Path,
) -> None:
    # passages@1 ends a sentence after an initial ("J. Doe"), unlike SciFact.
    abstract = ["Work by J. Doe used synthetic drug C.", "It failed."]
    root = _scifact(tmp_path, [_claim(12, {"104": [_support(0)]}, [104])])
    _jsonl(
        root / "data" / "corpus.jsonl",
        [{"doc_id": 104, "title": "Synthetic D", "abstract": abstract, "structured": False}],
    )
    result = import_public(PublicDataset.SCIFACT, root)
    (pair,) = result.items[0].claims[0].pairs
    passages = split_passages(" ".join(abstract), CheckedText.ABSTRACT)
    assert [(s.passage_id, s.offsets) for s in pair.evidence_spans] == [
        (p.passage_id, p.offsets) for p in passages[:2]
    ]
    assert summarize(result)["rationale_sentences_cut"] == 1


def test_scifact_contradict_maps_to_contradicts_and_contradicted(tmp_path: Path) -> None:
    root = _scifact(tmp_path, [_claim(2, {"102": [_contradict(1)]}, [102])])
    item, _ = _one(root, PublicDataset.SCIFACT)
    assert item.claims[0].status is GoldStatus.CONTRADICTED
    assert [p.agreement_label for p in item.claims[0].pairs] == [SourceLabel.CONTRADICTS]


def test_scifact_noinfo_maps_to_neutral_and_insufficient_evidence(tmp_path: Path) -> None:
    root = _scifact(tmp_path, [_claim(3, {}, [103])])
    item, _ = _one(root, PublicDataset.SCIFACT)
    assert item.claims[0].status is GoldStatus.INSUFFICIENT_EVIDENCE
    (pair,) = item.claims[0].pairs
    assert pair.agreement_label is SourceLabel.NEUTRAL
    assert pair.evidence_spans == ()


def test_a_cited_source_without_evidence_is_a_neutral_pair_beside_the_support(
    tmp_path: Path,
) -> None:
    root = _scifact(tmp_path, [_claim(4, {"101": [_support(0, 1)]}, [101, 103])])
    item, result = _one(root, PublicDataset.SCIFACT)
    claim = item.claims[0]
    assert claim.status is GoldStatus.VERIFIED
    assert [(p.pair_id, p.source_group, p.agreement_label) for p in claim.pairs] == [
        ("G10000004-c1-s1", "scifact-doc-101", SourceLabel.ENTAILS),
        ("G10000004-c1-s2", "scifact-doc-103", SourceLabel.NEUTRAL),
    ]
    assert len(claim.pairs[0].evidence_spans) == 2
    assert len(result.texts) == 2


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        (_claim(5, {"109": [_support(0)]}, [109]), "source_not_in_corpus"),
        (_claim(6, {"101": [_support(7)]}, [101]), "rationale_sentence_missing"),
        (
            _claim(7, {"101": [_support(1)], "102": [_contradict(1)]}, [101, 102]),
            "sources_disagree",
        ),
        (_claim(8, {"101": [_support(1), _contradict(2)]}, [101]), "mixed_labels_in_source"),
        (_claim(9, {}, []), "no_cited_source"),
        (_claim(10, {"101": [{"sentences": [1], "label": "MAYBE"}]}, [101]), "unknown_label"),
        ({"id": 11, "claim": ""}, "malformed_record"),
    ],
)
def test_scifact_items_that_cannot_be_mapped_cleanly_are_dropped_by_reason(
    tmp_path: Path, claim: dict[str, object], reason: str
) -> None:
    result = import_public(PublicDataset.SCIFACT, _scifact(tmp_path, [claim]))
    assert result.items == ()
    assert result.dropped == {("train", DropReason(reason)): 1}


def test_scifact_uses_train_and_dev_and_never_opens_the_test_split(tmp_path: Path) -> None:
    root = _scifact(tmp_path, [_claim(1, {}, [103])], [_claim(2, {"101": [_support(1)]}, [101])])
    result = import_public(PublicDataset.SCIFACT, root)
    assert [(i.item_id, i.provenance and i.provenance.dataset_split) for i in result.items] == [
        ("G10000001", "train"),
        ("G10000002", "dev"),
    ]


def test_scifact_without_a_labelled_file_is_refused(tmp_path: Path) -> None:
    root = _scifact(tmp_path, [])
    (root / "data" / "claims_dev.jsonl").unlink()
    with pytest.raises(GoldSetError, match=r"claims_dev\.jsonl"):
        import_public(PublicDataset.SCIFACT, root)


# Synthetic SciClaimEval -------------------------------------------------------

TABLE = {
    "table_caption": "Table 1: Synthetic accuracy of two models.",
    "table_column_names": ["Model", "Accuracy"],
    "table_content_values": [["Alpha", "81.0"], ["Beta", "77.5"]],
}
TABLE_TEXT = (
    "Table 1: Synthetic accuracy of two models.\n\nModel | Accuracy\n\nAlpha | 81.0\n\nBeta | 77.5"
)


def _sample(claim_id: str, **changes: object) -> dict[str, object]:
    sample: dict[str, object] = {
        "claim_id": claim_id,
        "claim": "Alpha is more accurate than Beta.",
        "label": "Supported",
        "caption": "Table 1: Synthetic accuracy of two models.",
        "evi_type": "table",
        "evi_path": f"tables_png/dev/{claim_id}.png",
        "evi_path_original": f"tables/dev/{claim_id}.tex",
        "context": "We compare two synthetic models.",
        "use_context": "no",
        "operation": "Change the cell values",
        "claim_id_pair": "val_tab_9999",
        "detail_others": "",
        "domain": "nlp",
        "paper_id": "synthetic-paper-1",
        "paper_path": "papers/dev/synthetic.json",
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    }
    sample.update(changes)
    return sample


def _sciclaimeval(
    tmp_path: Path, samples: list[object], tables: dict[str, object] | None = None
) -> Path:
    root = tmp_path / "sciclaimeval"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "dev_task1_release.json").write_text(json.dumps(samples), encoding="utf-8")
    (data / "tables_json" / "dev").mkdir(parents=True)
    for name, table in (tables or {}).items():
        (data / "tables_json" / "dev" / f"{name}.json").write_text(json.dumps(table), "utf-8")
    return root


def test_a_table_is_rendered_caption_header_and_rows_as_paragraphs() -> None:
    assert render_table(TABLE) == TABLE_TEXT
    two_headers = dict(TABLE, table_column_names=[["", "Accuracy"], ["Model", "Test"]])
    assert render_table(two_headers).split("\n\n")[1:3] == [" | Accuracy", "Model | Test"]


def test_a_supported_table_claim_maps_to_entails_and_verified_with_every_passage(
    tmp_path: Path,
) -> None:
    root = _sciclaimeval(tmp_path, [_sample("val_tab_0001")], {"val_tab_0001": TABLE})
    item, result = _one(root, PublicDataset.SCICLAIMEVAL)
    assert item.item_id == "G20000001"
    assert item.domain is Domain.ML
    assert item.text_unit == "Alpha is more accurate than Beta."
    assert item.claims[0].status is GoldStatus.VERIFIED
    (pair,) = item.claims[0].pairs
    assert pair.source_id == "sciclaimeval-table-val_tab_0001"
    # The source group is the paper (maintainer decision 14).
    assert pair.source_group == "sciclaimeval-paper-synthetic-paper-1"
    assert pair.text_hash == _hash(TABLE_TEXT)
    assert pair.checked_text is CheckedText.FULL_TEXT
    assert pair.agreement_label is SourceLabel.ENTAILS
    passages = split_passages(TABLE_TEXT, CheckedText.FULL_TEXT)
    assert [(s.passage_id, s.offsets) for s in pair.evidence_spans] == [
        (p.passage_id, p.offsets) for p in passages
    ]
    provenance = item.provenance
    assert provenance is not None
    assert (provenance.dataset, provenance.dataset_split) == (PublicDataset.SCICLAIMEVAL, "dev")
    assert provenance.original_id == "val_tab_0001"
    assert provenance.licence == "CC BY 4.0"
    assert provenance.text_redistributable is True
    assert provenance.evidence_modified is False
    # Not in S2 metrics (decision 5) nor S4 (decision 4).
    assert provenance.not_scored == (NotScored.S2, NotScored.S4)
    assert result.texts == {_hash(TABLE_TEXT): TABLE_TEXT}


def test_a_refuted_table_claim_maps_to_contradicts_and_contradicted_on_modified_evidence(
    tmp_path: Path,
) -> None:
    root = _sciclaimeval(
        tmp_path,
        [_sample("val_tab_0002", label="Refuted", domain="peerj", license_name="Public Domain")],
        {"val_tab_0002": TABLE},
    )
    item, _ = _one(root, PublicDataset.SCICLAIMEVAL)
    assert item.claims[0].status is GoldStatus.CONTRADICTED
    assert item.claims[0].pairs[0].agreement_label is SourceLabel.CONTRADICTS
    assert item.provenance is not None
    assert item.provenance.evidence_modified is True
    assert item.provenance.licence == "Public Domain"
    assert item.domain is Domain.BIOMEDICINE


def test_a_claim_that_needs_its_context_carries_it_in_the_text_unit(tmp_path: Path) -> None:
    root = _sciclaimeval(
        tmp_path, [_sample("val_tab_0003", use_context="yes")], {"val_tab_0003": TABLE}
    )
    item, _ = _one(root, PublicDataset.SCICLAIMEVAL)
    claim = "Alpha is more accurate than Beta."
    assert item.text_unit == "We compare two synthetic models. " + claim
    span = item.claims[0].span
    assert item.text_unit[span[0] : span[1]] == claim


@pytest.mark.parametrize(
    ("changes", "tables", "reason"),
    [
        ({"evi_type": "figure"}, {}, "evidence_figure"),
        ({"evi_type": "video"}, {}, "unknown_evidence_type"),
        ({"use_context": "other sources"}, {"val_tab_0004": TABLE}, "needs_full_paper"),
        ({}, {}, "table_missing"),
        (
            {},
            {"val_tab_0004": dict(TABLE, table_column_names=[], table_content_values=[])},
            "table_empty",
        ),
        ({"domain": "chemistry"}, {"val_tab_0004": TABLE}, "unknown_domain"),
        ({"label": "NEI"}, {"val_tab_0004": TABLE}, "unknown_label"),
        ({"claim": ""}, {"val_tab_0004": TABLE}, "malformed_record"),
        ({"license_name": ""}, {"val_tab_0004": TABLE}, "malformed_record"),
        ({"paper_id": ""}, {"val_tab_0004": TABLE}, "malformed_record"),
        # Only CC BY 4.0 and public-domain samples are kept (maintainer decision 2).
        ({"license_name": "CC BY-NC 4.0"}, {"val_tab_0004": TABLE}, "licence_not_allowed"),
        ({"license_name": "CC BY-NC-SA 4.0"}, {"val_tab_0004": TABLE}, "licence_not_allowed"),
        ({"license_name": "CC BY-SA 4.0"}, {"val_tab_0004": TABLE}, "licence_not_allowed"),
    ],
)
def test_sciclaimeval_items_that_cannot_be_mapped_cleanly_are_dropped_by_reason(
    tmp_path: Path, changes: dict[str, object], tables: dict[str, object], reason: str
) -> None:
    root = _sciclaimeval(tmp_path, [_sample("val_tab_0004", **changes)], tables)
    result = import_public(PublicDataset.SCICLAIMEVAL, root)
    assert result.items == ()
    assert result.dropped == {("dev", DropReason(reason)): 1}


def test_a_table_file_name_is_never_taken_from_outside_the_tables_directory(
    tmp_path: Path,
) -> None:
    root = _sciclaimeval(tmp_path, [_sample("../../secret")], {})
    (tmp_path / "secret.json").write_text(json.dumps(TABLE), encoding="utf-8")
    result = import_public(PublicDataset.SCICLAIMEVAL, root)
    assert result.dropped == {("dev", DropReason.MALFORMED_RECORD): 1}


# Determinism, the summary, the checks and the output ---------------------------


def test_the_import_is_deterministic_and_summarized_by_counts(tmp_path: Path) -> None:
    root = _sciclaimeval(
        tmp_path,
        [
            _sample("val_tab_0006", label="Refuted"),
            _sample("val_tab_0005"),
            _sample("val_fig_0007", evi_type="figure"),
            _sample("val_tab_0008", license_name="CC BY-SA 4.0"),
        ],
        {"val_tab_0005": TABLE, "val_tab_0006": TABLE, "val_tab_0008": TABLE},
    )
    first = import_public(PublicDataset.SCICLAIMEVAL, root)
    second = import_public(PublicDataset.SCICLAIMEVAL, root)
    assert first == second
    assert [i.item_id for i in first.items] == ["G20000005", "G20000006"]
    summary = summarize(first)
    assert summary["items"] == 2
    assert summary["by_status"] == {"dev": {"contradicted": 1, "verified": 1}}
    assert summary["by_pair_label"] == {"dev": {"contradicts": 1, "entails": 1}}
    assert summary["dropped"] == {"dev": {"evidence_figure": 1, "licence_not_allowed": 1}}
    assert summary["by_licence"] == {"CC BY 4.0": 2}
    assert summary["by_domain"] == {"ml": 2}
    assert summary["source_groups"] == 1
    # Counts only: no claim or source text in the summary.
    assert "Alpha" not in json.dumps(summary)


def test_items_and_source_texts_are_written_and_read_back(tmp_path: Path) -> None:
    root = _sciclaimeval(tmp_path, [_sample("val_tab_0008")], {"val_tab_0008": TABLE})
    result = import_public(PublicDataset.SCICLAIMEVAL, root)
    out = tmp_path / "out" / "sciclaimeval"
    write_public_import(out, result)
    assert read_gold_release(out / "items.jsonl") == result.items
    digest = _hash(TABLE_TEXT).removeprefix("sha256:")
    assert (out / "sources" / f"{digest}.txt").read_text(encoding="utf-8") == TABLE_TEXT


def test_the_output_is_refused_inside_a_git_work_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    empty = PublicImport(PublicDataset.SCIFACT, (), {}, {})
    with pytest.raises(GoldSetError, match="git"):
        write_public_import(tmp_path / "repo" / "out", empty)
    assert not (tmp_path / "repo" / "out").exists()


def test_an_item_whose_hash_spans_or_status_do_not_fit_is_refused(tmp_path: Path) -> None:
    root = _sciclaimeval(tmp_path, [_sample("val_tab_0009")], {"val_tab_0009": TABLE})
    result = import_public(PublicDataset.SCICLAIMEVAL, root)
    (item,) = result.items
    check_public_item(item, result.texts)
    with pytest.raises(GoldSetError, match="text"):
        check_public_item(item, {})
    document = json.loads(item.to_json_line())
    document["claims"][0]["pairs"][0]["evidence_spans"][0]["offsets"] = [0, 1000]
    with pytest.raises(GoldSetError, match="passage"):
        check_public_item(GoldItem.validate_document(document, "synthetic"), result.texts)
    document = json.loads(item.to_json_line())
    document["claims"][0]["status"] = "contradicted"
    with pytest.raises(GoldSetError, match="status"):
        check_public_item(GoldItem.validate_document(document, "synthetic"), result.texts)
