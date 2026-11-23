"""Gold v0 items from public expert-annotated datasets (task M0-15b).

No human annotators are available for gold set v0, so it is built from
public datasets whose labels were made by experts
(`docs/eval/gold-v0-strategy.md`, ADR-0018, RFC-002 section 2). This module
maps their published labels into gold items of origin `public` by fixed
rules. It never creates, infers or changes a label: every label is the
dataset's own, renamed.

| Dataset label | Pair label | Claim status |
| --- | --- | --- |
| SUPPORT, Supported | `entails` | `verified` |
| CONTRADICT, Refuted | `contradicts` | `contradicted` |
| NOINFO (a cited abstract with no rationale) | `neutral` | `insufficient_evidence` |

Each item has a provenance block instead of annotators (RFC-002, section 4,
option (a)). Evidence spans are passages of `passages@1` (ADR-0015).
Anything that does not map cleanly is dropped and counted by a
`DropReason`. Only splits whose labels are published are read: SciFact's
`train` and `dev`, SciClaimEval's `dev`. SciFact's `claims_test.jsonl` is
never opened.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from utux.errors import GoldSetError
from utux.evalkit.gold import (
    Domain,
    EvidenceSpan,
    GoldClaim,
    GoldItem,
    GoldPair,
    GoldStatus,
    NotScored,
    Origin,
    Provenance,
    PublicDataset,
    read_gold_release,
)
from utux.schemas.claim_ledger import CheckedText, ExtractionQuality, SourceLabel
from utux.schemas.json_io import parse_json
from utux.sources.passages import Passage, split_passages
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_bytes

GOLD_VERSION = "0.1"
"""Imported items belong to the v0.1 release that the pilot locks (RFC-002, section 6)."""


class DropReason(StrEnum):
    """Why a dataset record did not become an item."""

    MALFORMED_RECORD = "malformed_record"
    UNKNOWN_LABEL = "unknown_label"
    NO_CITED_SOURCE = "no_cited_source"
    SOURCE_NOT_IN_CORPUS = "source_not_in_corpus"
    RATIONALE_SENTENCE_MISSING = "rationale_sentence_missing"
    MIXED_LABELS_IN_SOURCE = "mixed_labels_in_source"
    SOURCES_DISAGREE = "sources_disagree"
    EVIDENCE_FIGURE = "evidence_figure"
    UNKNOWN_EVIDENCE_TYPE = "unknown_evidence_type"
    NEEDS_FULL_PAPER = "needs_full_paper"
    UNKNOWN_DOMAIN = "unknown_domain"
    TABLE_MISSING = "table_missing"
    TABLE_EMPTY = "table_empty"
    LICENCE_NOT_ALLOWED = "licence_not_allowed"


STATUS_OF_LABEL = {
    SourceLabel.ENTAILS: GoldStatus.VERIFIED,
    SourceLabel.CONTRADICTS: GoldStatus.CONTRADICTED,
    SourceLabel.NEUTRAL: GoldStatus.INSUFFICIENT_EVIDENCE,
}
"""The claim status that follows from the labels of its pairs (see `_status`)."""


def _status(labels: Iterable[SourceLabel]) -> GoldStatus | None:
    """The claim status of its pair labels, or None when sources disagree."""
    found = set(labels)
    if not found <= set(STATUS_OF_LABEL):
        return None
    if SourceLabel.ENTAILS in found and SourceLabel.CONTRADICTS in found:
        return None
    for label in (SourceLabel.ENTAILS, SourceLabel.CONTRADICTS):
        if label in found:
            return STATUS_OF_LABEL[label]
    return GoldStatus.INSUFFICIENT_EVIDENCE


def _text_hash(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))


@dataclass(frozen=True)
class PublicImport:
    """The items made from one dataset, their source texts by hash, and the drops.

    `dropped` counts the records dropped, by dataset split and reason.
    """

    dataset: PublicDataset
    items: tuple[GoldItem, ...]
    texts: Mapping[str, str]
    dropped: Mapping[tuple[str, DropReason], int]
    rationale_sentences_cut: int = 0


class _Drop(Exception):  # noqa: N818 - an internal signal, never raised to callers
    def __init__(self, reason: DropReason) -> None:
        self.reason = reason


@dataclass(frozen=True)
class _Source:
    source_id: str
    source_group: str
    text: str
    checked_text: CheckedText


def _pair(
    claim_id: str,
    number: int,
    source: _Source,
    label: SourceLabel,
    spans: Sequence[EvidenceSpan],
) -> GoldPair:
    return GoldPair(
        pair_id=f"{claim_id}-s{number}",
        source_id=source.source_id,
        source_group=source.source_group,
        text_hash=_text_hash(source.text),
        checked_text=source.checked_text,
        extraction_quality=ExtractionQuality.CLEAN,
        evidence_spans=tuple(spans),
        agreement_label=label,
        scope_flags=(),
        raw={},
        adjudicated=False,
        adjudication_reason=None,
    )


def _item(
    item_id: str,
    domain: Domain,
    text_unit: str,
    claim: str,
    pairs: Sequence[tuple[_Source, SourceLabel, Sequence[EvidenceSpan]]],
    provenance: Provenance,
) -> GoldItem:
    status = _status(label for _, label, _ in pairs)
    if status is None:
        raise _Drop(DropReason.SOURCES_DISAGREE)
    claim_id = f"{item_id}-c1"
    start = text_unit.rindex(claim)
    return GoldItem(
        schema_version=GoldItem.SCHEMA_VERSION,
        item_id=item_id,
        gold_version=GOLD_VERSION,
        split=None,
        domain=domain,
        origin=Origin.PUBLIC,
        hard_case=None,
        text_unit=text_unit,
        claims=(
            GoldClaim(
                claim_id=claim_id,
                text=claim,
                span=(start, start + len(claim)),
                # The datasets give no kind and no review flag; none is inferred.
                kind=None,
                pairs=tuple(
                    _pair(claim_id, n, source, label, spans)
                    for n, (source, label, spans) in enumerate(pairs, start=1)
                ),
                status=status,
                expert_would_review=None,
                raw={},
                adjudicated=False,
                adjudication_reason=None,
                ambiguous=False,
            ),
        ),
        annotation=None,
        provenance=provenance,
    )


# SciFact -----------------------------------------------------------------------

SCIFACT_SPLITS = ("train", "dev")
SCIFACT_LICENCE = "CC BY-NC 2.0"
"""The most restrictive of SciFact's two licence statements, until AllenAI clarifies."""
_SCIFACT_LABELS = {"SUPPORT": SourceLabel.ENTAILS, "CONTRADICT": SourceLabel.CONTRADICTS}


def _read_jsonl(path: Path) -> list[object]:
    if not path.is_file():
        raise GoldSetError(f"{path.name} is missing from {path.parent}")
    rows: list[object] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append(None)
    return rows


def _abstract_text(sentences: Sequence[str]) -> tuple[str, list[tuple[int, int] | None]]:
    """The abstract's sentences joined by single spaces, and each one's offsets."""
    parts: list[str] = []
    offsets: list[tuple[int, int] | None] = []
    position = 0
    for sentence in sentences:
        clean = sentence.strip()
        if not clean:
            offsets.append(None)
            continue
        if parts:
            position += 1
        offsets.append((position, position + len(clean)))
        parts.append(clean)
        position += len(clean)
    return " ".join(parts), offsets


@dataclass(frozen=True)
class _Abstract:
    source: _Source
    passages: tuple[Passage, ...]
    sentences: tuple[tuple[int, int] | None, ...]


def _scifact_corpus(path: Path) -> dict[str, _Abstract]:
    corpus: dict[str, _Abstract] = {}
    for row in _read_jsonl(path):
        if not isinstance(row, dict):
            continue
        doc_id, sentences = row.get("doc_id"), row.get("abstract")
        if not isinstance(doc_id, int) or not isinstance(sentences, list):
            continue
        if not all(isinstance(sentence, str) for sentence in sentences):
            continue
        text, offsets = _abstract_text(sentences)
        if not text:
            continue
        # Claims that share an abstract share its group (RFC-002, section 6).
        source = _Source(
            f"scifact-doc-{doc_id}", f"scifact-doc-{doc_id}", text, CheckedText.ABSTRACT
        )
        corpus[str(doc_id)] = _Abstract(
            source, split_passages(text, CheckedText.ABSTRACT), tuple(offsets)
        )
    return corpus


def _spans(abstract: _Abstract, indices: Sequence[object]) -> tuple[list[EvidenceSpan], int]:
    """One span per passage that a rationale sentence overlaps; and how many were cut."""
    spans: list[EvidenceSpan] = []
    cut = 0
    for index in indices:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise _Drop(DropReason.MALFORMED_RECORD)
        bounds = abstract.sentences[index] if index < len(abstract.sentences) else None
        if bounds is None:
            raise _Drop(DropReason.RATIONALE_SENTENCE_MISSING)
        start, end = bounds
        overlapping = [p for p in abstract.passages if p.offsets[0] < end and start < p.offsets[1]]
        if len(overlapping) != 1 or overlapping[0].offsets != (start, end):
            cut += 1
        for passage in overlapping:
            low, high = max(start, passage.offsets[0]), min(end, passage.offsets[1])
            spans.append(EvidenceSpan(passage_id=passage.passage_id, offsets=(low, high)))
    return spans, cut


def _scifact_item(
    row: object, split: str, corpus: Mapping[str, _Abstract]
) -> tuple[GoldItem, list[_Source], int]:
    if not isinstance(row, dict):
        raise _Drop(DropReason.MALFORMED_RECORD)
    claim_id, claim, evidence, cited = (
        row.get("id"),
        row.get("claim"),
        row.get("evidence"),
        row.get("cited_doc_ids", []),
    )
    if (
        not isinstance(claim_id, int)
        or isinstance(claim_id, bool)
        or claim_id < 0
        or not isinstance(claim, str)
        or not claim.strip()
        or not isinstance(evidence, dict)
        or not isinstance(cited, list)
    ):
        raise _Drop(DropReason.MALFORMED_RECORD)
    claim = claim.strip()
    doc_ids = list(dict.fromkeys([str(doc) for doc in cited] + sorted(evidence)))
    if not doc_ids:
        raise _Drop(DropReason.NO_CITED_SOURCE)
    pairs: list[tuple[_Source, SourceLabel, Sequence[EvidenceSpan]]] = []
    cut = 0
    for doc_id in doc_ids:
        abstract = corpus.get(doc_id)
        if abstract is None:
            raise _Drop(DropReason.SOURCE_NOT_IN_CORPUS)
        rationales = evidence.get(doc_id, [])
        if not isinstance(rationales, list):
            raise _Drop(DropReason.MALFORMED_RECORD)
        labels: set[SourceLabel] = set()
        spans: list[EvidenceSpan] = []
        for rationale in rationales:
            if not isinstance(rationale, dict) or not isinstance(rationale.get("sentences"), list):
                raise _Drop(DropReason.MALFORMED_RECORD)
            label = _SCIFACT_LABELS.get(str(rationale.get("label")))
            if label is None:
                raise _Drop(DropReason.UNKNOWN_LABEL)
            labels.add(label)
            found, was_cut = _spans(abstract, rationale["sentences"])
            spans.extend(found)
            cut += was_cut
        if len(labels) > 1:
            raise _Drop(DropReason.MIXED_LABELS_IN_SOURCE)
        label = labels.pop() if labels else SourceLabel.NEUTRAL
        pairs.append((abstract.source, label, tuple(dict.fromkeys(spans))))
    provenance = Provenance(
        dataset=PublicDataset.SCIFACT,
        dataset_split=split,
        original_id=str(claim_id),
        licence=SCIFACT_LICENCE,
        # Abstracts are never redistributed (maintainer decision 1).
        text_redistributable=False,
        evidence_modified=False,
        not_scored=(NotScored.S4,),
    )
    item = _item(f"G1{claim_id:07d}", Domain.BIOMEDICINE, claim, claim, pairs, provenance)
    return item, [source for source, _, _ in pairs], cut


def _import_scifact(directory: Path) -> PublicImport:
    data = directory / "data"
    for split in SCIFACT_SPLITS:
        if not (data / f"claims_{split}.jsonl").is_file():
            raise GoldSetError(f"claims_{split}.jsonl is missing from {data}")
    corpus = _scifact_corpus(data / "corpus.jsonl")
    made: list[tuple[GoldItem, list[_Source]]] = []
    dropped: Counter[tuple[str, DropReason]] = Counter()
    cut = 0
    for split in SCIFACT_SPLITS:
        for row in _read_jsonl(data / f"claims_{split}.jsonl"):
            try:
                item, sources, was_cut = _scifact_item(row, split, corpus)
            except _Drop as drop:
                dropped[(split, drop.reason)] += 1
                continue
            made.append((item, sources))
            cut += was_cut
    return _result(PublicDataset.SCIFACT, made, dropped, cut)


# SciClaimEval ---------------------------------------------------------------------

SCICLAIMEVAL_FILE = "dev_task1_release.json"
SCICLAIMEVAL_LICENCES = frozenset({"CC BY 4.0", "Public Domain"})
"""The sample licences kept; NC and SA samples are dropped (maintainer decision 2)."""
_SCICLAIMEVAL_LABELS = {"Supported": SourceLabel.ENTAILS, "Refuted": SourceLabel.CONTRADICTS}
_SCICLAIMEVAL_DOMAINS = {"ml": Domain.ML, "nlp": Domain.ML, "peerj": Domain.BIOMEDICINE}
_SAMPLE_ID = re.compile(r"^val_(tab|fig)_([0-9]+)$")
_CELL = re.compile(r"\s+")


def _cell(value: object) -> str:
    return _CELL.sub(" ", str(value)).strip()


def render_table(table: Mapping[str, object]) -> str:
    """A table as text: its caption, each header row and each row, one paragraph each.

    Cells are joined by ` | `, and runs of whitespace in a cell become one
    space. Paragraphs are separated by a blank line, so `passages@1` never
    joins two rows into one passage.
    """
    paragraphs: list[str] = []
    caption = table.get("table_caption")
    if isinstance(caption, str) and caption.strip():
        paragraphs.append(_cell(caption))
    header = table.get("table_column_names")
    if isinstance(header, list) and header:
        header_rows = header if all(isinstance(row, list) for row in header) else [header]
        paragraphs.extend(" | ".join(_cell(c) for c in row) for row in header_rows)
    rows = table.get("table_content_values")
    if isinstance(rows, list):
        paragraphs.extend(
            " | ".join(_cell(c) for c in row) for row in rows if isinstance(row, list)
        )
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip(" |"))


def _text_field(sample: Mapping[str, Any], key: str) -> str:
    value = sample.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _Drop(DropReason.MALFORMED_RECORD)
    return value.strip()


def _sciclaimeval_item(sample: object, tables: Path) -> tuple[GoldItem, list[_Source]]:
    if not isinstance(sample, dict):
        raise _Drop(DropReason.MALFORMED_RECORD)
    fields = ("claim_id", "claim", "label", "evi_type", "use_context", "domain")
    claim_id, claim, label_name, evidence_type, use_context, domain_name = (
        _text_field(sample, key) for key in fields
    )
    licence = _text_field(sample, "license_name")
    paper_id = _text_field(sample, "paper_id")
    number = _SAMPLE_ID.match(claim_id)
    if number is None:
        raise _Drop(DropReason.MALFORMED_RECORD)
    label = _SCICLAIMEVAL_LABELS.get(label_name)
    if label is None:
        raise _Drop(DropReason.UNKNOWN_LABEL)
    if evidence_type == "figure":
        raise _Drop(DropReason.EVIDENCE_FIGURE)
    if evidence_type != "table":
        raise _Drop(DropReason.UNKNOWN_EVIDENCE_TYPE)
    if use_context.lower() not in ("no", "yes"):
        raise _Drop(DropReason.NEEDS_FULL_PAPER)
    domain = _SCICLAIMEVAL_DOMAINS.get(domain_name)
    if domain is None:
        raise _Drop(DropReason.UNKNOWN_DOMAIN)
    if licence not in SCICLAIMEVAL_LICENCES:
        raise _Drop(DropReason.LICENCE_NOT_ALLOWED)
    path = tables / f"{claim_id}.json"
    if not path.is_file():
        raise _Drop(DropReason.TABLE_MISSING)
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise _Drop(DropReason.MALFORMED_RECORD) from error
    if not isinstance(table, dict):
        raise _Drop(DropReason.MALFORMED_RECORD)
    if not table.get("table_content_values"):
        raise _Drop(DropReason.TABLE_EMPTY)
    text = render_table(table)
    context = sample.get("context")
    text_unit = claim
    if use_context.lower() == "yes" and isinstance(context, str) and context.strip():
        text_unit = context.strip() + " " + claim
    source = _Source(
        f"sciclaimeval-table-{claim_id}",
        # Grouped by paper (maintainer decision 14).
        f"sciclaimeval-paper-{paper_id}",
        text,
        CheckedText.FULL_TEXT,
    )
    # The dataset gives the whole table as evidence, not cells: every passage.
    spans = tuple(
        EvidenceSpan(passage_id=p.passage_id, offsets=p.offsets)
        for p in split_passages(text, CheckedText.FULL_TEXT)
    )
    provenance = Provenance(
        dataset=PublicDataset.SCICLAIMEVAL,
        dataset_split="dev",
        original_id=claim_id,
        licence=licence,
        text_redistributable=True,
        # Refuted samples pair the claim with evidence the authors modified.
        evidence_modified=label is SourceLabel.CONTRADICTS,
        # Excluded from S2 (decision 5) and S4 (decision 4).
        not_scored=(NotScored.S2, NotScored.S4),
    )
    item_id = f"G2{int(number.group(2)):07d}"
    item = _item(item_id, domain, text_unit, claim, [(source, label, spans)], provenance)
    return item, [source]


def _import_sciclaimeval(directory: Path) -> PublicImport:
    data = directory / "data"
    path = data / SCICLAIMEVAL_FILE
    if not path.is_file():
        raise GoldSetError(f"{SCICLAIMEVAL_FILE} is missing from {data}")
    samples = parse_json(path.read_text(encoding="utf-8"), SCICLAIMEVAL_FILE)
    if not isinstance(samples, list):
        raise GoldSetError(f"{SCICLAIMEVAL_FILE} is not a list of samples")
    made: list[tuple[GoldItem, list[_Source]]] = []
    dropped: Counter[tuple[str, DropReason]] = Counter()
    for sample in samples:
        try:
            made.append(_sciclaimeval_item(sample, data / "tables_json" / "dev"))
        except _Drop as drop:
            dropped[("dev", drop.reason)] += 1
    return _result(PublicDataset.SCICLAIMEVAL, made, dropped, 0)


# Shared ------------------------------------------------------------------------


def _result(
    dataset: PublicDataset,
    made: Sequence[tuple[GoldItem, list[_Source]]],
    dropped: Mapping[tuple[str, DropReason], int],
    cut: int,
) -> PublicImport:
    texts: dict[str, str] = {}
    for _, sources in made:
        for source in sources:
            texts[_text_hash(source.text)] = source.text
    items = tuple(sorted((item for item, _ in made), key=lambda item: item.item_id))
    duplicates = [i for i, n in Counter(item.item_id for item in items).items() if n > 1]
    if duplicates:
        raise GoldSetError(f"two records map to the item id {duplicates[0]}")
    for item in items:
        check_public_item(item, texts)
    return PublicImport(dataset, items, dict(sorted(texts.items())), dict(dropped), cut)


def check_public_item(item: GoldItem, texts: Mapping[str, str]) -> None:
    """Check an imported item against its source texts.

    Every pair's text is known by its hash, every evidence span lies inside
    a passage of that text, and the claim status follows from the pair
    labels by `STATUS_OF_LABEL`.

    Raises:
        GoldSetError: The item does not fit its texts or its labels.
    """
    for claim in item.claims:
        for pair in claim.pairs:
            text = texts.get(pair.text_hash)
            if text is None:
                raise GoldSetError(f"{pair.pair_id}: no stored text has the hash {pair.text_hash}")
            passages = {p.passage_id: p.offsets for p in split_passages(text, pair.checked_text)}
            for span in pair.evidence_spans:
                bounds = passages.get(span.passage_id)
                if bounds is None or not (
                    bounds[0] <= span.offsets[0] < span.offsets[1] <= bounds[1]
                ):
                    raise GoldSetError(
                        f"{pair.pair_id}: an evidence span is not inside its passage"
                    )
        if _status(pair.agreement_label for pair in claim.pairs) != claim.status:
            raise GoldSetError(f"{claim.claim_id}: the status does not follow from the labels")


def import_public(dataset: PublicDataset, directory: Path) -> PublicImport:
    """Map a downloaded public dataset into gold items, in item id order.

    `directory` holds the release as downloaded (`docs/eval/datasets.md`).

    Raises:
        GoldSetError: A file the import needs is missing.
    """
    if dataset is PublicDataset.SCIFACT:
        return _import_scifact(directory)
    return _import_sciclaimeval(directory)


def summarize(result: PublicImport) -> dict[str, object]:
    """Counts only, never a claim or a text: by split, status, pair label and drop reason."""
    by_status: dict[str, Counter[str]] = {}
    by_label: dict[str, Counter[str]] = {}
    groups: set[str] = set()
    for item in result.items:
        split = item.provenance.dataset_split if item.provenance else "unknown"
        for claim in item.claims:
            by_status.setdefault(split, Counter())[claim.status.value] += 1
            for pair in claim.pairs:
                by_label.setdefault(split, Counter())[pair.agreement_label.value] += 1
                groups.add(pair.source_group)
    dropped: dict[str, Counter[str]] = {}
    for (split, reason), count in result.dropped.items():
        dropped.setdefault(split, Counter())[reason.value] += count

    def plain(table: Mapping[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {split: dict(sorted(counts.items())) for split, counts in sorted(table.items())}

    provenances = [item.provenance for item in result.items if item.provenance]
    return {
        "dataset": result.dataset.value,
        "items": len(result.items),
        "by_status": plain(by_status),
        "by_pair_label": plain(by_label),
        "dropped": plain(dropped),
        "by_licence": dict(sorted(Counter(p.licence for p in provenances).items())),
        "by_domain": dict(sorted(Counter(item.domain.value for item in result.items).items())),
        "evidence_modified": sum(p.evidence_modified for p in provenances),
        "source_groups": len(groups),
        "source_texts": len(result.texts),
        "rationale_sentences_cut": result.rationale_sentences_cut,
    }


def _inside_git_work_tree(path: Path) -> bool:
    return any((directory / ".git").exists() for directory in path.resolve().parents)


def ensure_outside_git(path: Path) -> None:
    """Refuse a path for dataset-derived output inside any git work tree.

    Raises:
        GoldSetError: The path is inside a git work tree.
    """
    if _inside_git_work_tree(path):
        raise GoldSetError(
            f"{path} is inside a git work tree; write dataset items outside any repository"
        )


def load_imported(directories: Sequence[Path]) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    """The items and source texts of `write_public_import` directories.

    Raises:
        GoldSetError: A directory has no `items.jsonl`.
        ContractValidationError: An item is not valid.
    """
    items: list[GoldItem] = []
    texts: dict[str, str] = {}
    for directory in directories:
        path = directory / "items.jsonl"
        if not path.is_file():
            raise GoldSetError(f"{path} is missing; run utux gold import-public first")
        items += read_gold_release(path)
        for source in sorted((directory / "sources").glob("*.txt")):
            texts[f"sha256:{source.stem}"] = source.read_text(encoding="utf-8")
    return tuple(items), texts


def write_public_import(directory: Path, result: PublicImport) -> None:
    """Write `items.jsonl` and `sources/<hash>.txt` into a directory outside any git work tree.

    Dataset text must not be committed, so the directory is refused anywhere
    a `.git` sits above it. Files are written atomically.

    Raises:
        GoldSetError: The directory is inside a git work tree.
    """
    ensure_outside_git(directory)
    sources = directory / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    for text_hash, text in result.texts.items():
        atomic_write_text(sources / f"{text_hash.removeprefix('sha256:')}.txt", text)
    atomic_write_text(
        directory / "items.jsonl", "".join(item.to_json_line() for item in result.items)
    )
