"""Gold v0 items from public expert-annotated datasets (task M0-15b).

No human annotators are available for gold set v0, so it is proposed from
public datasets whose labels were made by experts
(`docs/eval/gold-v0-strategy.md`, ADR-0018, both Proposed). This module maps
their published labels into items by fixed rules. It never creates, infers
or changes a label: every label of an item is the dataset's own, renamed.

| Dataset label | Pair label | Claim status |
| --- | --- | --- |
| SUPPORT, Supported | `entails` | `verified` |
| CONTRADICT, Refuted | `contradicts` | `contradicted` |
| NOINFO (a cited abstract with no rationale) | `neutral` | `insufficient_evidence` |

Evidence spans are passages of `passages@1` (ADR-0015). Anything that does
not map cleanly is dropped and counted by a `DropReason`. Only splits whose
labels are published are read: SciFact's `train` and `dev`, SciClaimEval's
`dev`. SciFact's `claims_test.jsonl` is never opened.

The items are a schema of their own, `PublicItem`, not RFC-002 gold items:
they have no utux annotators. How RFC-002 would take them in is left to the
maintainer (`docs/eval/gold-v0-strategy.md`).
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, model_validator
from pydantic_core import PydanticCustomError

from utux.errors import GoldSetError
from utux.evalkit.gold import Domain, GoldStatus
from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.claim_ledger import CheckedText, SourceLabel
from utux.schemas.common import Count, NonEmptyText, Sha256Hash
from utux.schemas.json_io import parse_json
from utux.sources.passages import SPLITTER_VERSION, Passage, split_passages
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_bytes

PublicItemId = Annotated[
    str, Field(pattern=r"^(scifact|sciclaimeval)-(train|dev)-[A-Za-z0-9_]+$", strict=True)
]
"""The id of an imported item: dataset, split and the dataset's own id."""


class PublicDataset(StrEnum):
    """The public datasets that can be imported."""

    SCIFACT = "scifact"
    SCICLAIMEVAL = "sciclaimeval"


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


STATUS_OF_LABEL = {
    SourceLabel.ENTAILS: GoldStatus.VERIFIED,
    SourceLabel.CONTRADICTS: GoldStatus.CONTRADICTED,
    SourceLabel.NEUTRAL: GoldStatus.INSUFFICIENT_EVIDENCE,
}
"""The claim status that follows from the labels of its pairs (see `_status`)."""


class PublicSpan(ContractPart):
    """Evidence: a passage of the source text and the offsets inside it."""

    passage_id: NonEmptyText
    offsets: tuple[Count, Count]


class PublicPair(ContractPart):
    """A claim-source pair with the dataset's label."""

    source_id: NonEmptyText
    agreement_label: SourceLabel
    evidence_spans: tuple[PublicSpan, ...]


class PublicClaim(ContractPart):
    """The item's one claim, its span in the text unit, its status and pairs."""

    text: NonEmptyText
    span: tuple[Count, Count]
    status: GoldStatus
    pairs: tuple[PublicPair, ...] = Field(min_length=1)


class PublicSource(ContractPart):
    """The stored text a claim is checked against, with its licence."""

    source_id: NonEmptyText
    text: NonEmptyText
    text_hash: Sha256Hash
    checked_text: CheckedText
    licence: NonEmptyText


def _status(labels: Iterable[SourceLabel]) -> GoldStatus | None:
    """The claim status of its pair labels, or None when sources disagree."""
    found = set(labels)
    if SourceLabel.ENTAILS in found and SourceLabel.CONTRADICTS in found:
        return None
    for label in (SourceLabel.ENTAILS, SourceLabel.CONTRADICTS):
        if label in found:
            return STATUS_OF_LABEL[label]
    return GoldStatus.INSUFFICIENT_EVIDENCE


def _text_hash(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))


class PublicItem(ContractDocument):
    """One claim from a public dataset, with its sources and the dataset's labels.

    `evidence_modified` is true when the dataset's authors changed the
    evidence to make the label, as for SciClaimEval's `Refuted` samples.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    item_id: PublicItemId
    dataset: PublicDataset
    dataset_split: Annotated[str, Field(pattern=r"^(train|dev)$", strict=True)]
    original_id: NonEmptyText
    domain: Domain
    licence: NonEmptyText
    splitter_version: Annotated[str, Field(pattern=r"^passages@1$", strict=True)]
    text_unit: NonEmptyText
    claim: PublicClaim
    sources: tuple[PublicSource, ...] = Field(min_length=1)
    evidence_modified: StrictBool

    @model_validator(mode="after")
    def _fits_its_texts(self) -> Self:
        start, end = self.claim.span
        if not 0 <= start < end <= len(self.text_unit) or (
            self.text_unit[start:end] != self.claim.text
        ):
            raise PydanticCustomError("claim_span", "claim.span does not give claim.text")
        sources = {source.source_id: source for source in self.sources}
        for source in self.sources:
            if _text_hash(source.text) != source.text_hash:
                raise PydanticCustomError(
                    "text_hash_mismatch", "a source's text_hash does not match its text"
                )
        for pair in self.claim.pairs:
            if pair.agreement_label not in STATUS_OF_LABEL:
                raise PydanticCustomError(
                    "label_not_mapped", "a pair label must be entails, contradicts or neutral"
                )
            if pair.source_id not in sources:
                raise PydanticCustomError("unknown_source", "a pair names no listed source")
            source = sources[pair.source_id]
            passages = {
                p.passage_id: p.offsets for p in split_passages(source.text, source.checked_text)
            }
            for span in pair.evidence_spans:
                bounds = passages.get(span.passage_id)
                inside = bounds is not None and (
                    bounds[0] <= span.offsets[0] < span.offsets[1] <= bounds[1]
                )
                if not inside:
                    raise PydanticCustomError(
                        "span_outside_passage",
                        "an evidence span is not inside its passage of the source text",
                    )
        if _status(pair.agreement_label for pair in self.claim.pairs) != self.claim.status:
            raise PydanticCustomError(
                "status_mismatch", "claim.status does not follow from the pair labels"
            )
        return self

    def to_json_line(self) -> str:
        """The item as one line of JSON that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class PublicImport:
    """The items made from one dataset, and the records dropped, by split and reason."""

    dataset: PublicDataset
    items: tuple[PublicItem, ...]
    dropped: Mapping[tuple[str, DropReason], int]
    rationale_sentences_cut: int = 0


class _Drop(Exception):  # noqa: N818 - an internal signal, never raised to callers
    def __init__(self, reason: DropReason) -> None:
        self.reason = reason


def _claim(text_unit: str, claim: str, status: GoldStatus, pairs: list[PublicPair]) -> PublicClaim:
    start = text_unit.rindex(claim)
    return PublicClaim(
        text=claim, span=(start, start + len(claim)), status=status, pairs=tuple(pairs)
    )


# SciFact -----------------------------------------------------------------------

SCIFACT_SPLITS = ("train", "dev")
SCIFACT_CLAIMS_LICENCE = "CC BY 4.0"
SCIFACT_CORPUS_LICENCE = "ODC-By 1.0"
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


@dataclass
class _Abstract:
    source: PublicSource
    passages: tuple[Passage, ...]
    sentences: list[tuple[int, int] | None]


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
        source = PublicSource(
            source_id=f"scifact-doc-{doc_id}",
            text=text,
            text_hash=_text_hash(text),
            checked_text=CheckedText.ABSTRACT,
            licence=SCIFACT_CORPUS_LICENCE,
        )
        corpus[str(doc_id)] = _Abstract(source, split_passages(text, CheckedText.ABSTRACT), offsets)
    return corpus


def _spans(abstract: _Abstract, indices: Sequence[object]) -> tuple[list[PublicSpan], int]:
    """One span per passage that a rationale sentence overlaps; and how many were cut."""
    spans: list[PublicSpan] = []
    cut = 0
    for index in indices:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise _Drop(DropReason.MALFORMED_RECORD)
        if index >= len(abstract.sentences) or abstract.sentences[index] is None:
            raise _Drop(DropReason.RATIONALE_SENTENCE_MISSING)
        start, end = abstract.sentences[index] or (0, 0)
        overlapping = [p for p in abstract.passages if p.offsets[0] < end and start < p.offsets[1]]
        if len(overlapping) != 1 or overlapping[0].offsets != (start, end):
            cut += 1
        for passage in overlapping:
            low, high = max(start, passage.offsets[0]), min(end, passage.offsets[1])
            spans.append(PublicSpan(passage_id=passage.passage_id, offsets=(low, high)))
    return spans, cut


def _scifact_item(
    row: object, split: str, corpus: Mapping[str, _Abstract]
) -> tuple[PublicItem, int]:
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
    pairs: list[PublicPair] = []
    sources: list[PublicSource] = []
    cut = 0
    for doc_id in doc_ids:
        abstract = corpus.get(doc_id)
        if abstract is None:
            raise _Drop(DropReason.SOURCE_NOT_IN_CORPUS)
        rationales = evidence.get(doc_id, [])
        if not isinstance(rationales, list):
            raise _Drop(DropReason.MALFORMED_RECORD)
        labels: set[SourceLabel] = set()
        spans: list[PublicSpan] = []
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
        unique = tuple(dict.fromkeys(spans))
        pairs.append(
            PublicPair(
                source_id=abstract.source.source_id,
                agreement_label=labels.pop() if labels else SourceLabel.NEUTRAL,
                evidence_spans=unique,
            )
        )
        sources.append(abstract.source)
    status = _status(pair.agreement_label for pair in pairs)
    if status is None:
        raise _Drop(DropReason.SOURCES_DISAGREE)
    item = PublicItem(
        schema_version=PublicItem.SCHEMA_VERSION,
        item_id=f"scifact-{split}-{claim_id}",
        dataset=PublicDataset.SCIFACT,
        dataset_split=split,
        original_id=str(claim_id),
        domain=Domain.BIOMEDICINE,
        licence=SCIFACT_CLAIMS_LICENCE,
        splitter_version=SPLITTER_VERSION,
        text_unit=claim,
        claim=_claim(claim, claim, status, pairs),
        sources=tuple(sources),
        evidence_modified=False,
    )
    return item, cut


def _import_scifact(directory: Path) -> PublicImport:
    data = directory / "data"
    for split in SCIFACT_SPLITS:
        if not (data / f"claims_{split}.jsonl").is_file():
            raise GoldSetError(f"claims_{split}.jsonl is missing from {data}")
    corpus = _scifact_corpus(data / "corpus.jsonl")
    items: list[PublicItem] = []
    dropped: Counter[tuple[str, DropReason]] = Counter()
    cut = 0
    for split in SCIFACT_SPLITS:
        for row in _read_jsonl(data / f"claims_{split}.jsonl"):
            try:
                item, was_cut = _scifact_item(row, split, corpus)
            except _Drop as drop:
                dropped[(split, drop.reason)] += 1
                continue
            items.append(item)
            cut += was_cut
    return PublicImport(PublicDataset.SCIFACT, _ordered(items), dict(dropped), cut)


# SciClaimEval ---------------------------------------------------------------------

SCICLAIMEVAL_FILE = "dev_task1_release.json"
_SCICLAIMEVAL_LABELS = {"Supported": SourceLabel.ENTAILS, "Refuted": SourceLabel.CONTRADICTS}
_SCICLAIMEVAL_DOMAINS = {"ml": Domain.ML, "nlp": Domain.ML, "peerj": Domain.BIOMEDICINE}
_SAMPLE_ID = re.compile(r"^val_(tab|fig)_[0-9]+$")
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


def _sciclaimeval_item(sample: object, tables: Path) -> PublicItem:
    if not isinstance(sample, dict):
        raise _Drop(DropReason.MALFORMED_RECORD)
    texts = {
        key: sample.get(key)
        for key in ("claim_id", "claim", "label", "evi_type", "use_context", "domain")
    }
    licence = sample.get("license_name")
    if (
        not all(isinstance(value, str) for value in texts.values())
        or not isinstance(licence, str)
        or not licence.strip()
        or not str(texts["claim"]).strip()
        or not _SAMPLE_ID.match(str(texts["claim_id"]))
    ):
        raise _Drop(DropReason.MALFORMED_RECORD)
    claim_id, claim = str(texts["claim_id"]), str(texts["claim"]).strip()
    label = _SCICLAIMEVAL_LABELS.get(str(texts["label"]))
    if label is None:
        raise _Drop(DropReason.UNKNOWN_LABEL)
    if texts["evi_type"] == "figure":
        raise _Drop(DropReason.EVIDENCE_FIGURE)
    if texts["evi_type"] != "table":
        raise _Drop(DropReason.UNKNOWN_EVIDENCE_TYPE)
    use_context = str(texts["use_context"]).lower()
    if use_context not in ("no", "yes"):
        raise _Drop(DropReason.NEEDS_FULL_PAPER)
    domain = _SCICLAIMEVAL_DOMAINS.get(str(texts["domain"]))
    if domain is None:
        raise _Drop(DropReason.UNKNOWN_DOMAIN)
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
    if use_context == "yes" and isinstance(context, str) and context.strip():
        text_unit = context.strip() + " " + claim
    source = PublicSource(
        source_id=f"sciclaimeval-table-{claim_id}",
        text=text,
        text_hash=_text_hash(text),
        checked_text=CheckedText.FULL_TEXT,
        licence=licence.strip(),
    )
    # The dataset gives the whole table as evidence, not cells: every passage.
    spans = tuple(
        PublicSpan(passage_id=p.passage_id, offsets=p.offsets)
        for p in split_passages(text, CheckedText.FULL_TEXT)
    )
    pair = PublicPair(source_id=source.source_id, agreement_label=label, evidence_spans=spans)
    return PublicItem(
        schema_version=PublicItem.SCHEMA_VERSION,
        item_id=f"sciclaimeval-dev-{claim_id}",
        dataset=PublicDataset.SCICLAIMEVAL,
        dataset_split="dev",
        original_id=claim_id,
        domain=domain,
        licence=licence.strip(),
        splitter_version=SPLITTER_VERSION,
        text_unit=text_unit,
        claim=_claim(text_unit, claim, STATUS_OF_LABEL[label], [pair]),
        sources=(source,),
        # Refuted samples pair the claim with evidence the authors modified.
        evidence_modified=label is SourceLabel.CONTRADICTS,
    )


def _import_sciclaimeval(directory: Path) -> PublicImport:
    data = directory / "data"
    path = data / SCICLAIMEVAL_FILE
    if not path.is_file():
        raise GoldSetError(f"{SCICLAIMEVAL_FILE} is missing from {data}")
    samples = parse_json(path.read_text(encoding="utf-8"), SCICLAIMEVAL_FILE)
    if not isinstance(samples, list):
        raise GoldSetError(f"{SCICLAIMEVAL_FILE} is not a list of samples")
    items: list[PublicItem] = []
    dropped: Counter[tuple[str, DropReason]] = Counter()
    for sample in samples:
        try:
            items.append(_sciclaimeval_item(sample, data / "tables_json" / "dev"))
        except _Drop as drop:
            dropped[("dev", drop.reason)] += 1
    return PublicImport(PublicDataset.SCICLAIMEVAL, _ordered(items), dict(dropped))


# Shared ------------------------------------------------------------------------


def _ordered(items: list[PublicItem]) -> tuple[PublicItem, ...]:
    def key(item: PublicItem) -> tuple[str, int, str]:
        number = int(item.original_id) if item.original_id.isdigit() else -1
        return (item.dataset_split, number, item.original_id)

    return tuple(sorted(items, key=key))


def import_public(dataset: PublicDataset, directory: Path) -> PublicImport:
    """Map a downloaded public dataset into items, in a fixed order.

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
    for item in result.items:
        split = item.dataset_split
        by_status.setdefault(split, Counter())[item.claim.status.value] += 1
        for pair in item.claim.pairs:
            by_label.setdefault(split, Counter())[pair.agreement_label.value] += 1
    dropped: dict[str, Counter[str]] = {}
    for (split, reason), count in result.dropped.items():
        dropped.setdefault(split, Counter())[reason.value] += count

    def plain(table: Mapping[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {split: dict(sorted(counts.items())) for split, counts in sorted(table.items())}

    return {
        "dataset": result.dataset.value,
        "items": len(result.items),
        "by_status": plain(by_status),
        "by_pair_label": plain(by_label),
        "dropped": plain(dropped),
        "by_licence": dict(sorted(Counter(item.licence for item in result.items).items())),
        "by_domain": dict(sorted(Counter(item.domain.value for item in result.items).items())),
        "evidence_modified": sum(item.evidence_modified for item in result.items),
        "rationale_sentences_cut": result.rationale_sentences_cut,
    }


def _inside_git_work_tree(path: Path) -> bool:
    return any((directory / ".git").exists() for directory in path.resolve().parents)


def write_public_items(path: Path, items: Sequence[PublicItem]) -> None:
    """Write items as JSON Lines, atomically, never inside a git work tree.

    Dataset text must not be committed, so the output is refused anywhere a
    `.git` sits above it.

    Raises:
        GoldSetError: The path is inside a git work tree.
    """
    if _inside_git_work_tree(path):
        raise GoldSetError(
            f"{path} is inside a git work tree; write dataset items outside any repository"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, "".join(item.to_json_line() for item in items))


def read_public_items(path: Path) -> tuple[PublicItem, ...]:
    """Read and validate the items of a JSON Lines file.

    Raises:
        ContractValidationError: A line is not a valid item.
    """
    items: list[PublicItem] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            items.append(PublicItem.from_json(line, f"{path.name}, line {number}"))
    return tuple(items)
