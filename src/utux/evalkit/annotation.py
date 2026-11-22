"""Tooling for the annotators and the adjudicator of the gold set (M0-15a).

The tooling handles labels made by people and never writes, suggests or
changes one (`AGENTS.md`, section 8; RFC-002, section 5). It moves them
between files, checks them, and puts the two annotators' work side by side.

The files, in the order of the work (`docs/annotation-tooling.md`):

1. **Pool** (`AnnotationPool`), written by the maintainer: the items to
   annotate, with their sources, the passages of each source's text, and,
   for a perturbed or system-generated item, its hidden record.
2. **Batch** (`AnnotationBatch`), one per annotator and phase, written by
   `export_batch`. It holds what the annotator may see: the text unit and the
   sources, and in phase 2 the reference claims. It holds neither the other
   annotator's work nor the hidden record, origin or hard case of an item.
3. **Work** (`ExtractionWork`, `LabellingWork`), written by the offline page
   (`annotation_page.html`) and read back with `read_work`, which checks it
   against its batch.
4. **Merge.** `merge_extraction` puts the two claim lists side by side and
   gives the reference claims of every item where they agree or the
   adjudicator decided (`ReferenceClaims`). `merge_labelling` does the same
   for the labels and gives gold items. Everything else is a
   `Disagreement` for the adjudicator, whose decisions are an `Adjudication`
   file. Where the annotators agree and the adjudicator decided nothing, the
   reference value is theirs (`docs/gold-set.md`); nothing else is filled in.

Batches of the future `test` split, the works and the merged items hold
labels that the agents and the developers who tune prompts must not read
(RFC-002, section 6): keep them with the adjudicator, outside the repository.
"""

import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, field_validator, model_validator
from pydantic_core import InitErrorDetails

from utux.errors import ContractValidationError, GoldSetError, Problem
from utux.evalkit.gold import (
    Annotation,
    AnnotatorId,
    ClaimExtraction,
    ClaimRaw,
    Domain,
    EvidenceSpan,
    ExtractedClaim,
    GenerationRecord,
    GoldClaim,
    GoldClaimId,
    GoldItem,
    GoldPair,
    GoldSplit,
    GoldStatus,
    GoldVersion,
    HardCase,
    ItemId,
    Note,
    Origin,
    PairId,
    PairRaw,
    PerturbationRecord,
)
from utux.schemas.base import ContractDocument, ContractPart, field_problem, raise_field_problems
from utux.schemas.claim_ledger import (
    CheckedText,
    ClaimKind,
    ExtractionQuality,
    ScopeFlag,
    SourceLabel,
)
from utux.schemas.common import Count, Identifier, NonEmptyText, Sha256Hash
from utux.schemas.json_io import read_json
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_bytes

PAGE_FILE = "annotation_page.html"
"""The offline annotation page, a single HTML file."""


class Phase(StrEnum):
    """The two phases of annotation (RFC-002, section 5)."""

    CLAIM_EXTRACTION = "claim_extraction"
    LABELLING = "labelling"


def _increasing(value: tuple[int, int]) -> tuple[int, int]:
    if value[1] <= value[0]:
        raise ValueError(f"the end ({value[1]}) must be greater than the start ({value[0]})")
    return value


# The pool


class Passage(ContractPart):
    """A passage of a source's text: the unit an annotator marks as evidence.

    `offsets` are character offsets into the source's text, start and end.
    """

    passage_id: NonEmptyText
    offsets: tuple[Count, Count]

    @field_validator("offsets")
    @classmethod
    def _offsets_increase(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value)


def _passage_problems(text: str, passages: Sequence[Passage]) -> list[InitErrorDetails]:
    problems: list[InitErrorDetails] = []
    seen: set[str] = set()
    for index, passage in enumerate(passages):
        if passage.passage_id in seen:
            problems.append(
                field_problem("duplicate_passage", "a passage id is used once", "passages", index)
            )
        seen.add(passage.passage_id)
        if passage.offsets[1] > len(text):
            problems.append(
                field_problem(
                    "span_out_of_range",
                    f"the end ({passage.offsets[1]}) is beyond the text ({len(text)})",
                    "passages",
                    index,
                    "offsets",
                )
            )
    ordered = sorted(enumerate(passages), key=lambda entry: entry[1].offsets)
    for (_, first), (index, second) in itertools.pairwise(ordered):
        if second.offsets[0] < first.offsets[1]:
            problems.append(
                field_problem(
                    "passages_overlap",
                    f"{second.passage_id} overlaps {first.passage_id}",
                    "passages",
                    index,
                    "offsets",
                )
            )
    return problems


class PoolSource(ContractPart):
    """A source of a pool item, with its stored text and its passages."""

    source_id: NonEmptyText
    source_group: NonEmptyText
    checked_text: CheckedText
    extraction_quality: ExtractionQuality
    text: NonEmptyText
    passages: Annotated[tuple[Passage, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _passages_fit(self) -> Self:
        raise_field_problems("PoolSource", _passage_problems(self.text, self.passages))
        return self

    @property
    def text_hash(self) -> str:
        """The hash of the stored text, which the gold item records."""
        return hash_bytes(self.text.encode("utf-8"))


class PoolItem(ContractPart):
    """An item to annotate: its text unit, sources and, if any, hidden record."""

    item_id: ItemId
    domain: Domain
    origin: Origin
    hard_case: HardCase | None
    text_unit: NonEmptyText
    sources: tuple[PoolSource, ...]
    hidden: PerturbationRecord | GenerationRecord | None = None

    @model_validator(mode="after")
    def _sources_are_distinct(self) -> Self:
        ids = [source.source_id for source in self.sources]
        raise_field_problems(
            "PoolItem",
            [
                field_problem("duplicate_source", "a source is listed once", "sources", index)
                for index, source_id in enumerate(ids)
                if source_id in ids[:index]
            ],
        )
        return self


class AnnotationPool(ContractDocument):
    """The items of one round of annotation, written by the maintainer.

    Attributes:
        gold_version: The release the items are made for.
        items: The items, each with a distinct id.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    gold_version: GoldVersion
    items: tuple[PoolItem, ...]

    @model_validator(mode="after")
    def _items_are_distinct(self) -> Self:
        ids = [item.item_id for item in self.items]
        raise_field_problems(
            "AnnotationPool",
            [
                field_problem("duplicate_item_id", "an item is listed once", "items", index)
                for index, item_id in enumerate(ids)
                if item_id in ids[:index]
            ],
        )
        return self

    def item(self, item_id: str) -> PoolItem:
        """The item with this id.

        Raises:
            GoldSetError: The pool has no such item.
        """
        for item in self.items:
            if item.item_id == item_id:
                return item
        raise GoldSetError(f"the pool has no item {item_id}")


def load_pool(path: Path) -> AnnotationPool:
    """Read and validate a pool file.

    Raises:
        ContractValidationError: The file cannot be read or is not a valid pool.
    """
    return AnnotationPool.validate_document(read_json(path), str(path))


# Batches


class BatchSource(ContractPart):
    """A source as the annotator sees it: no source group."""

    source_id: NonEmptyText
    checked_text: CheckedText
    extraction_quality: ExtractionQuality
    text_hash: Sha256Hash
    text: NonEmptyText
    passages: tuple[Passage, ...]


class ReferenceClaim(ContractPart):
    """A reference claim, fixed after claim extraction, with its citations."""

    claim_id: GoldClaimId
    span: tuple[Count, Count]
    text: NonEmptyText
    kind: ClaimKind
    citations: tuple[NonEmptyText, ...]


class BatchItem(ContractPart):
    """An item as the annotator sees it: no origin, hard case or hidden record.

    `claims` holds the reference claims in phase 2 and is empty in phase 1.
    """

    item_id: ItemId
    domain: Domain
    text_unit: NonEmptyText
    sources: tuple[BatchSource, ...]
    claims: tuple[ReferenceClaim, ...]


class AnnotationBatch(ContractDocument):
    """What one annotator receives for one phase.

    Attributes:
        phase: `claim_extraction` or `labelling`.
        batch_id: The batch; both annotators of a batch get the same items.
        annotator: The annotator's pseudonymous id, such as `a03`.
        batch_hash: The hash of the rest of the batch. The work names it, so
            that work is read only against the batch it was made from.
        items: The items.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    phase: Phase
    batch_id: Identifier
    annotator: AnnotatorId
    batch_hash: Sha256Hash
    items: tuple[BatchItem, ...]


def _batch_hash(phase: Phase, batch_id: str, annotator: str, items: Sequence[BatchItem]) -> str:
    content = {
        "phase": phase.value,
        "batch_id": batch_id,
        "annotator": annotator,
        "items": [item.model_dump(mode="json") for item in items],
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_bytes(canonical.encode("utf-8"))


def export_batch(
    pool: AnnotationPool,
    phase: Phase,
    annotator: str,
    batch_id: str,
    *,
    references: "ReferenceClaims | None" = None,
) -> AnnotationBatch:
    """The batch of one annotator for one phase.

    Each annotator gets the same items, and nothing of the other annotator's
    work. A phase-2 batch holds the reference claims of `references`.

    Raises:
        ContractValidationError: The annotator id or the batch id is not valid.
        GoldSetError: A phase-2 batch lacks the reference claims of an item.
    """
    items: list[BatchItem] = []
    for item in pool.items:
        claims: tuple[ReferenceClaim, ...] = ()
        if phase is Phase.LABELLING:
            if references is None:
                raise GoldSetError(
                    f"a labelling batch needs the reference claims of {item.item_id}; merge "
                    "the claim lists first"
                )
            claims = references.item(item.item_id).claims
        items.append(
            BatchItem(
                item_id=item.item_id,
                domain=item.domain,
                text_unit=item.text_unit,
                sources=tuple(
                    BatchSource(
                        source_id=source.source_id,
                        checked_text=source.checked_text,
                        extraction_quality=source.extraction_quality,
                        text_hash=source.text_hash,
                        text=source.text,
                        passages=source.passages,
                    )
                    for source in item.sources
                ),
                claims=claims,
            )
        )
    document = {
        "schema_version": AnnotationBatch.SCHEMA_VERSION,
        "phase": phase.value,
        "batch_id": batch_id,
        "annotator": annotator,
        "batch_hash": "sha256:" + "0" * 64,
        "items": [item.model_dump(mode="json") for item in items],
    }
    # Validated first, so that a bad id is reported before it is hashed.
    checked = AnnotationBatch.validate_document(document, "batch")
    return checked.model_copy(
        update={"batch_hash": _batch_hash(phase, batch_id, annotator, checked.items)}
    )


def load_batch(path: Path) -> AnnotationBatch:
    """Read and validate a batch file.

    Raises:
        ContractValidationError: The file cannot be read or is not a valid batch.
    """
    return AnnotationBatch.validate_document(read_json(path), str(path))


# Work


Flag = NonEmptyText | None
"""Why the annotator marked the item for the adjudicator instead of labelling it."""

Minutes = Count | None


class ListedClaim(ContractPart):
    """A claim as an annotator lists it in phase 1 (guideline section 4)."""

    span: tuple[Count, Count]
    text: NonEmptyText
    kind: ClaimKind
    citations: tuple[NonEmptyText, ...]

    @field_validator("span")
    @classmethod
    def _span_increases(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value)

    def key(self) -> tuple[object, ...]:
        """What is compared between two lists: span, text, kind and citations."""
        return (self.span, self.text, self.kind, frozenset(self.citations))


class ExtractionWorkItem(ContractPart):
    """One annotator's claims of one item."""

    item_id: ItemId
    claims: tuple[ListedClaim, ...]
    flag: Flag
    minutes: Minutes


class PairWork(ContractPart):
    """One annotator's labels of one claim-source pair (guideline section 5)."""

    source_id: NonEmptyText
    evidence_spans: tuple[EvidenceSpan, ...]
    agreement_label: SourceLabel
    scope_flags: tuple[ScopeFlag, ...]
    note: Note


class ClaimWork(ContractPart):
    """One annotator's labels of one reference claim and its pairs."""

    claim_id: GoldClaimId
    status: GoldStatus
    expert_would_review: StrictBool
    note: Note
    pairs: tuple[PairWork, ...]


class LabellingWorkItem(ContractPart):
    """One annotator's labels of one item."""

    item_id: ItemId
    claims: tuple[ClaimWork, ...]
    flag: Flag
    minutes: Minutes


class ExtractionWork(ContractDocument):
    """One annotator's phase-1 work on a batch, as the page exports it."""

    SCHEMA_VERSION: ClassVar[int] = 1

    phase: Phase
    batch_id: Identifier
    batch_hash: Sha256Hash
    annotator: AnnotatorId
    items: tuple[ExtractionWorkItem, ...]


class LabellingWork(ContractDocument):
    """One annotator's phase-2 work on a batch, as the page exports it."""

    SCHEMA_VERSION: ClassVar[int] = 1

    phase: Phase
    batch_id: Identifier
    batch_hash: Sha256Hash
    annotator: AnnotatorId
    items: tuple[LabellingWorkItem, ...]


Work = ExtractionWork | LabellingWork


def _header_problems(batch: AnnotationBatch, work: Work) -> list[Problem]:
    return [
        Problem(
            name,
            f"{getattr(work, name)} is not the batch's {getattr(batch, name)}",
            "differs_from_batch",
        )
        for name in ("phase", "batch_id", "batch_hash", "annotator")
        if getattr(work, name) != getattr(batch, name)
    ]


def _item_problems(batch: AnnotationBatch, work_ids: Sequence[str]) -> list[Problem]:
    known = [item.item_id for item in batch.items]
    problems = [
        Problem(f"items.{index}.item_id", f"{item_id} is not an item of the batch", "unknown_item")
        for index, item_id in enumerate(work_ids)
        if item_id not in known
    ]
    problems += [
        Problem(f"items.{index}.item_id", f"{item_id} is given twice", "duplicate_item")
        for index, item_id in enumerate(work_ids)
        if item_id in work_ids[:index]
    ]
    problems += [
        Problem("items", f"{item_id} of the batch has no work", "missing_item")
        for item_id in known
        if item_id not in work_ids
    ]
    return problems


def _extraction_problems(batch: AnnotationBatch, work: ExtractionWork) -> list[Problem]:
    problems: list[Problem] = []
    by_id = {item.item_id: item for item in batch.items}
    for index, item in enumerate(work.items):
        shown = by_id.get(item.item_id)
        if shown is None:
            continue
        sources = {source.source_id for source in shown.sources}
        for number, claim in enumerate(item.claims):
            at = f"items.{index}.claims.{number}"
            if claim.span[1] > len(shown.text_unit):
                problems.append(
                    Problem(
                        f"{at}.span",
                        f"the end ({claim.span[1]}) is beyond the text unit "
                        f"({len(shown.text_unit)})",
                        "span_out_of_range",
                    )
                )
            if len(set(claim.citations)) != len(claim.citations):
                problems.append(
                    Problem(f"{at}.citations", "a source is cited once", "duplicate_citation")
                )
            problems += [
                Problem(f"{at}.citations", f"{cited} is not a source of the item", "unknown_source")
                for cited in claim.citations
                if cited not in sources
            ]
    return problems


def _labelling_problems(batch: AnnotationBatch, work: LabellingWork) -> list[Problem]:
    problems: list[Problem] = []
    by_id = {item.item_id: item for item in batch.items}
    for index, item in enumerate(work.items):
        shown = by_id.get(item.item_id)
        if shown is None:
            continue
        if item.flag is not None and not item.claims:
            continue
        passages = {
            source.source_id: {p.passage_id: p.offsets for p in source.passages}
            for source in shown.sources
        }
        labelled = {claim.claim_id: (number, claim) for number, claim in enumerate(item.claims)}
        problems += [
            Problem(f"items.{index}.claims", f"{claim.claim_id} has no labels", "missing_claim")
            for claim in shown.claims
            if claim.claim_id not in labelled
        ]
        reference = {claim.claim_id: claim for claim in shown.claims}
        for claim_id, (number, claim) in labelled.items():
            at = f"items.{index}.claims.{number}"
            known = reference.get(claim_id)
            if known is None:
                problems.append(
                    Problem(
                        f"{at}.claim_id", f"{claim_id} is not a reference claim", "unknown_claim"
                    )
                )
                continue
            if not known.citations and claim.status is not GoldStatus.INSUFFICIENT_EVIDENCE:
                problems.append(
                    Problem(
                        f"{at}.status",
                        "a claim that cites no source has the status insufficient_evidence",
                        "raw_status_without_pairs",
                    )
                )
            given = [pair.source_id for pair in claim.pairs]
            problems += [
                Problem(f"{at}.pairs", f"the pair with {cited} has no labels", "missing_pair")
                for cited in known.citations
                if cited not in given
            ]
            for place, pair in enumerate(claim.pairs):
                where = f"{at}.pairs.{place}"
                if pair.source_id not in known.citations:
                    problems.append(
                        Problem(
                            f"{where}.source_id",
                            f"{pair.source_id} is not cited by {claim_id}",
                            "unknown_source",
                        )
                    )
                    continue
                if len(set(pair.scope_flags)) != len(pair.scope_flags):
                    problems.append(
                        Problem(f"{where}.scope_flags", "a flag is given once", "duplicate_flag")
                    )
                for span_index, span in enumerate(pair.evidence_spans):
                    offsets = passages[pair.source_id].get(span.passage_id)
                    spot = f"{where}.evidence_spans.{span_index}"
                    if offsets is None:
                        problems.append(
                            Problem(
                                f"{spot}.passage_id",
                                f"{span.passage_id} is not a passage of {pair.source_id}",
                                "unknown_passage",
                            )
                        )
                    elif span.offsets != offsets:
                        problems.append(
                            Problem(
                                f"{spot}.offsets",
                                f"{span.passage_id} has the offsets {list(offsets)}",
                                "offsets_differ",
                            )
                        )
    return problems


def read_work(
    batch: AnnotationBatch, data: Mapping[str, object] | Path, source: str = "work.json"
) -> Work:
    """Read one annotator's work and check it against the batch it was made from.

    The work must name the batch, its hash and its annotator, cover each
    item of the batch once, and give, in phase 1, spans within the text unit
    and citations among the item's sources; in phase 2, labels for every
    reference claim and every pair, with evidence among the passages of the
    pair's source. An item flagged for the adjudicator may be left without
    labels.

    Raises:
        ContractValidationError: Every problem, each on its field.
    """
    if isinstance(data, Path):
        source = str(data)
        data = read_json(data)  # type: ignore[assignment]
    model: type[ExtractionWork] | type[LabellingWork] = (
        ExtractionWork if batch.phase is Phase.CLAIM_EXTRACTION else LabellingWork
    )
    phase = data.get("phase") if isinstance(data, Mapping) else None
    if phase != batch.phase.value:
        raise ContractValidationError(
            source,
            (
                Problem(
                    "phase", f"{phase} is not the batch's {batch.phase.value}", "differs_from_batch"
                ),
            ),
        )
    work = model.validate_document(data, source)
    problems = _header_problems(batch, work)
    problems += _item_problems(batch, [item.item_id for item in work.items])
    if isinstance(work, ExtractionWork):
        problems += _extraction_problems(batch, work)
    else:
        problems += _labelling_problems(batch, work)
        problems += [
            Problem(f"items.{index}.claims", f"{item.item_id} has no labels", "missing_claim")
            for index, item in enumerate(work.items)
            if not item.claims and item.flag is None and _has_claims(batch, item.item_id)
        ]
    if problems:
        raise ContractValidationError(source, tuple(problems))
    return work


def _has_claims(batch: AnnotationBatch, item_id: str) -> bool:
    return any(item.item_id == item_id and item.claims for item in batch.items)


# Adjudication


class ExtractionDecision(ContractPart):
    """The adjudicator's reference claims of one item."""

    item_id: ItemId
    claims: tuple[ListedClaim, ...]
    reason: NonEmptyText


class ClaimDecision(ContractPart):
    """The adjudicator's status and review flag of one claim."""

    claim_id: GoldClaimId
    status: GoldStatus
    expert_would_review: StrictBool
    reason: NonEmptyText


class PairDecision(ContractPart):
    """The adjudicator's labels of one pair."""

    pair_id: PairId
    evidence_spans: tuple[EvidenceSpan, ...]
    agreement_label: SourceLabel
    scope_flags: tuple[ScopeFlag, ...]
    reason: NonEmptyText


class Adjudication(ContractDocument):
    """The adjudicator's decisions for one phase, each with a written reason.

    Attributes:
        phase: The phase decided.
        adjudicator: The adjudicator's pseudonymous id.
        extraction: Phase 1: reference claims of items.
        claims: Phase 2: claim decisions.
        pairs: Phase 2: pair decisions.
        ambiguous: Phase 2: claims that stayed disputed after joint
            discussion (RFC-002, section 5).
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    phase: Phase
    adjudicator: AnnotatorId
    extraction: tuple[ExtractionDecision, ...] = ()
    claims: tuple[ClaimDecision, ...] = ()
    pairs: tuple[PairDecision, ...] = ()
    ambiguous: tuple[GoldClaimId, ...] = ()


def load_adjudication(path: Path) -> Adjudication:
    """Read and validate an adjudication file.

    Raises:
        ContractValidationError: The file cannot be read or is not valid.
    """
    return Adjudication.validate_document(read_json(path), str(path))


# Merging


@dataclass(frozen=True)
class Disagreement:
    """Where the adjudicator must decide.

    Attributes:
        item_id: The item.
        level: `claim_extraction`, `claim`, `pair` or `flagged`.
        target: The item, claim or pair id.
        values: Each annotator's value at that level, as JSON values.
    """

    item_id: str
    level: str
    target: str
    values: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        """The disagreement as one JSON object."""
        return {
            "item_id": self.item_id,
            "level": self.level,
            "target": self.target,
            "values": dict(self.values),
        }


def disagreements_json(disagreements: Sequence[Disagreement]) -> str:
    """The disagreements as a JSON document for the adjudicator."""
    return json.dumps([d.to_json() for d in disagreements], indent=2, ensure_ascii=False) + "\n"


class ReferenceItem(ContractPart):
    """The fixed reference claims of one item, and how they were fixed."""

    item_id: ItemId
    annotators: tuple[AnnotatorId, AnnotatorId]
    adjudicator: AnnotatorId | None
    claims: tuple[ReferenceClaim, ...]
    claim_extraction: ClaimExtraction


class ReferenceClaims(ContractDocument):
    """The reference claims of the items whose claim lists are settled."""

    SCHEMA_VERSION: ClassVar[int] = 1

    items: tuple[ReferenceItem, ...]

    def item(self, item_id: str) -> ReferenceItem:
        """The reference claims of an item.

        Raises:
            GoldSetError: The item's claim list is not settled.
        """
        for item in self.items:
            if item.item_id == item_id:
                return item
        raise GoldSetError(f"{item_id} has no reference claims; its claim lists are not settled")


@dataclass(frozen=True)
class ExtractionMerge:
    """What `merge_extraction` gives: settled items, and what is left to decide."""

    references: ReferenceClaims
    disagreements: tuple[Disagreement, ...]


@dataclass(frozen=True)
class LabellingMerge:
    """What `merge_labelling` gives: complete gold items, and what is left to decide."""

    items: tuple[GoldItem, ...]
    disagreements: tuple[Disagreement, ...]


def _pair_of_works[W: (ExtractionWork, LabellingWork)](first: W, second: W) -> None:
    if first.annotator == second.annotator:
        raise GoldSetError("a merge takes the work of two annotators, not one twice")
    if first.batch_id != second.batch_id:
        raise GoldSetError(
            f"the two works are of the batches {first.batch_id} and {second.batch_id}, not one"
        )


def _listed_json(claims: Sequence[ListedClaim]) -> list[object]:
    return [claim.model_dump(mode="json") for claim in claims]


def _reference_claims(item_id: str, claims: Sequence[ListedClaim]) -> tuple[ReferenceClaim, ...]:
    ordered = sorted(claims, key=lambda claim: (claim.span, claim.text))
    return tuple(
        ReferenceClaim(
            claim_id=f"{item_id}-c{number}",
            span=claim.span,
            text=claim.text,
            kind=claim.kind,
            citations=tuple(sorted(claim.citations)),
        )
        for number, claim in enumerate(ordered, start=1)
    )


def _extracted(claims: Sequence[ListedClaim]) -> tuple[ExtractedClaim, ...]:
    return tuple(
        ExtractedClaim(span=claim.span, text=claim.text, citations=claim.citations)
        for claim in claims
    )


def merge_extraction(
    pool: AnnotationPool,
    first: ExtractionWork,
    second: ExtractionWork,
    adjudication: Adjudication | None = None,
) -> ExtractionMerge:
    """Put two annotators' claim lists side by side and fix what is settled.

    An item is settled when the adjudicator gave its reference claims, or
    when neither annotator flagged it and their lists are the same: the same
    span, text, kind and citations, in any order. The reference claims are
    then numbered in the order of their spans. Every other item is a
    disagreement, and no list is chosen for it.

    Raises:
        GoldSetError: The works are of one annotator or of two batches, or
            the adjudication is of the other phase.
    """
    _pair_of_works(first, second)
    if adjudication is not None and adjudication.phase is not Phase.CLAIM_EXTRACTION:
        raise GoldSetError("the adjudication is of the labelling phase, not of claim extraction")
    decided = {d.item_id: d for d in (adjudication.extraction if adjudication else ())}
    works = {first.annotator: first, second.annotator: second}
    settled: list[ReferenceItem] = []
    disagreements: list[Disagreement] = []
    for pool_item in pool.items:
        item_id = pool_item.item_id
        entries = {
            name: next(item for item in work.items if item.item_id == item_id)
            for name, work in works.items()
        }
        raw = {name: _extracted(entry.claims) for name, entry in entries.items()}
        decision = decided.get(item_id)
        if decision is not None:
            assert adjudication is not None
            claims: Sequence[ListedClaim] = decision.claims
            extraction = ClaimExtraction(
                raw=raw, adjudicated=True, adjudication_reason=decision.reason
            )
            adjudicator: str | None = adjudication.adjudicator
        else:
            flagged = {name: entry.flag for name, entry in entries.items() if entry.flag}
            if flagged:
                disagreements.append(Disagreement(item_id, "flagged", item_id, flagged))
                continue
            keys = [frozenset(c.key() for c in entry.claims) for entry in entries.values()]
            lists = list(entries.values())
            if keys[0] != keys[1] or len(lists[0].claims) != len(lists[1].claims):
                disagreements.append(
                    Disagreement(
                        item_id,
                        "claim_extraction",
                        item_id,
                        {name: _listed_json(entry.claims) for name, entry in entries.items()},
                    )
                )
                continue
            claims = lists[0].claims
            extraction = ClaimExtraction(raw=raw, adjudicated=False, adjudication_reason=None)
            adjudicator = None
        settled.append(
            ReferenceItem(
                item_id=item_id,
                annotators=(first.annotator, second.annotator),
                adjudicator=adjudicator,
                claims=_reference_claims(item_id, claims),
                claim_extraction=extraction,
            )
        )
    references = ReferenceClaims.validate_document(
        {
            "schema_version": ReferenceClaims.SCHEMA_VERSION,
            "items": [item.model_dump(mode="json") for item in settled],
        },
        "reference claims",
    )
    return ExtractionMerge(references, tuple(disagreements))


def _pair_values(pair: PairWork) -> tuple[object, ...]:
    return (
        frozenset((span.passage_id, span.offsets) for span in pair.evidence_spans),
        pair.agreement_label,
        frozenset(pair.scope_flags),
    )


def _merge_item(
    pool_item: PoolItem,
    reference: ReferenceItem,
    entries: Mapping[str, LabellingWorkItem],
    adjudication: Adjudication | None,
    split: GoldSplit,
    gold_version: str,
) -> tuple[GoldItem | None, list[Disagreement]]:
    item_id = pool_item.item_id
    flagged = {name: entry.flag for name, entry in entries.items() if entry.flag}
    if flagged:
        return None, [Disagreement(item_id, "flagged", item_id, flagged)]
    claim_decisions = {d.claim_id: d for d in (adjudication.claims if adjudication else ())}
    pair_decisions = {d.pair_id: d for d in (adjudication.pairs if adjudication else ())}
    ambiguous = set(adjudication.ambiguous if adjudication else ())
    sources = {source.source_id: source for source in pool_item.sources}
    disagreements: list[Disagreement] = []
    claims: list[GoldClaim] = []
    for reference_claim in reference.claims:
        labels = {
            name: next(c for c in entry.claims if c.claim_id == reference_claim.claim_id)
            for name, entry in entries.items()
        }
        pairs: list[GoldPair] = []
        for number, source_id in enumerate(reference_claim.citations, start=1):
            pair_id = f"{reference_claim.claim_id}-s{number}"
            given = {
                name: next(p for p in claim.pairs if p.source_id == source_id)
                for name, claim in labels.items()
            }
            raw = {
                name: PairRaw(
                    evidence_spans=pair.evidence_spans,
                    agreement_label=pair.agreement_label,
                    scope_flags=pair.scope_flags,
                    note=pair.note,
                )
                for name, pair in given.items()
            }
            pair_decision = pair_decisions.get(pair_id)
            if pair_decision is not None:
                spans, label, flags = (
                    pair_decision.evidence_spans,
                    pair_decision.agreement_label,
                    pair_decision.scope_flags,
                )
                reason: str | None = pair_decision.reason
            elif len({_pair_values(pair) for pair in given.values()}) == 1:
                agreed = next(iter(given.values()))
                spans, label, flags = (
                    agreed.evidence_spans,
                    agreed.agreement_label,
                    agreed.scope_flags,
                )
                reason = None
            else:
                disagreements.append(
                    Disagreement(
                        item_id,
                        "pair",
                        pair_id,
                        {name: pair.model_dump(mode="json") for name, pair in given.items()},
                    )
                )
                continue
            source = sources[source_id]
            pairs.append(
                GoldPair(
                    pair_id=pair_id,
                    source_id=source_id,
                    source_group=source.source_group,
                    text_hash=source.text_hash,
                    checked_text=source.checked_text,
                    extraction_quality=source.extraction_quality,
                    evidence_spans=spans,
                    agreement_label=label,
                    scope_flags=flags,
                    raw=raw,
                    adjudicated=reason is not None,
                    adjudication_reason=reason,
                )
            )
        claim_decision = claim_decisions.get(reference_claim.claim_id)
        claim_raw = {
            name: ClaimRaw(
                status=claim.status, expert_would_review=claim.expert_would_review, note=claim.note
            )
            for name, claim in labels.items()
        }
        if claim_decision is not None:
            status, review = claim_decision.status, claim_decision.expert_would_review
            claim_reason: str | None = claim_decision.reason
        elif len({(c.status, c.expert_would_review) for c in labels.values()}) == 1:
            agreed_claim = next(iter(labels.values()))
            status, review = agreed_claim.status, agreed_claim.expert_would_review
            claim_reason = None
        else:
            disagreements.append(
                Disagreement(
                    item_id,
                    "claim",
                    reference_claim.claim_id,
                    {
                        name: {
                            "status": claim.status.value,
                            "expert_would_review": claim.expert_would_review,
                            "note": claim.note,
                        }
                        for name, claim in labels.items()
                    },
                )
            )
            continue
        claims.append(
            GoldClaim(
                claim_id=reference_claim.claim_id,
                text=reference_claim.text,
                span=reference_claim.span,
                kind=reference_claim.kind,
                pairs=tuple(pairs),
                status=status,
                expert_would_review=review,
                raw=claim_raw,
                adjudicated=claim_reason is not None,
                adjudication_reason=claim_reason,
                ambiguous=reference_claim.claim_id in ambiguous,
            )
        )
    if disagreements:
        return None, disagreements
    adjudicator = reference.adjudicator
    if adjudication is not None:
        if adjudicator is not None and adjudicator != adjudication.adjudicator:
            raise GoldSetError(
                f"{item_id} was adjudicated by {adjudicator} in phase 1 and by "
                f"{adjudication.adjudicator} in phase 2; an item has one adjudicator"
            )
        if any(c.adjudicated or any(p.adjudicated for p in c.pairs) for c in claims):
            adjudicator = adjudication.adjudicator
    document: dict[str, object] = {
        "schema_version": GoldItem.SCHEMA_VERSION,
        "item_id": item_id,
        "gold_version": gold_version,
        "split": split.value,
        "domain": pool_item.domain.value,
        "origin": pool_item.origin.value,
        "hard_case": None if pool_item.hard_case is None else pool_item.hard_case.value,
        "text_unit": pool_item.text_unit,
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "annotation": Annotation(
            annotators=reference.annotators,
            adjudicator=adjudicator,
            claim_extraction=reference.claim_extraction,
        ).model_dump(mode="json"),
    }
    if pool_item.hidden is not None:
        document["hidden"] = pool_item.hidden.model_dump(mode="json")
    return GoldItem.validate_document(document, item_id), []


def merge_labelling(
    pool: AnnotationPool,
    references: ReferenceClaims,
    first: LabellingWork,
    second: LabellingWork,
    splits: Mapping[str, GoldSplit],
    adjudication: Adjudication | None = None,
) -> LabellingMerge:
    """Put two annotators' labels side by side and make the gold items that are settled.

    At each claim and pair, the reference value is the adjudicator's when
    the adjudication gives one, else the annotators' when they agree. Where
    neither holds, the level is a disagreement and its item is not made.
    Both annotators' labels are kept as the raw entries. `splits` gives each
    item's split: the split is chosen once the items exist (`assign_splits`
    and `split_report`), and set with `with_splits`.

    Raises:
        GoldSetError: The works are of one annotator or of two batches, are
            not the annotators of the claim lists, a split is missing, or
            the adjudication is of the other phase.
        ContractValidationError: A made item is not a valid gold item.
    """
    _pair_of_works(first, second)
    if adjudication is not None and adjudication.phase is not Phase.LABELLING:
        raise GoldSetError("the adjudication is of claim extraction, not of the labelling phase")
    items: list[GoldItem] = []
    disagreements: list[Disagreement] = []
    for pool_item in pool.items:
        item_id = pool_item.item_id
        reference = references.item(item_id)
        if {first.annotator, second.annotator} != set(reference.annotators):
            raise GoldSetError(
                f"{item_id} was listed by {', '.join(reference.annotators)} and labelled by "
                f"{first.annotator} and {second.annotator}; an item has two annotators"
            )
        split = splits.get(item_id)
        if split is None:
            raise GoldSetError(f"no split is given for {item_id}")
        entries = {
            work.annotator: next(item for item in work.items if item.item_id == item_id)
            for work in (first, second)
        }
        made, found = _merge_item(
            pool_item, reference, entries, adjudication, split, pool.gold_version
        )
        disagreements += found
        if made is not None:
            items.append(made)
    return LabellingMerge(tuple(items), tuple(disagreements))


def with_splits(items: Sequence[GoldItem], splits: Mapping[str, GoldSplit]) -> tuple[GoldItem, ...]:
    """The items with the split chosen for each, for example by `assign_splits`.

    Raises:
        GoldSetError: An item has no split in `splits`.
    """
    missing = [item.item_id for item in items if item.item_id not in splits]
    if missing:
        raise GoldSetError(f"no split is given for {', '.join(missing)}")
    return tuple(item.model_copy(update={"split": splits[item.item_id]}) for item in items)


# The offline page


def page_text() -> str:
    """The offline annotation page: one HTML file, with no network access."""
    return files("utux.evalkit").joinpath(PAGE_FILE).read_text(encoding="utf-8")


def write_annotation_page(directory: Path) -> Path:
    """Write the annotation page into a directory and return its path."""
    path = directory / PAGE_FILE
    atomic_write_text(path, page_text())
    return path
