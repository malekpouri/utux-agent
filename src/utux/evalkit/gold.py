"""The gold item schema of RFC-002, section 4, and the checks across a release.

One gold item is one text unit with its reference claims, the claim-source
pairs and the reference labels. Annotation has two phases (RFC-002, section
5): each annotator first lists the claims, and then both label the same
reference claims. Each annotator's own entries are kept at every level: the
claim list, each claim and each pair. A perturbed or system-generated item
also has a hidden record. A release is a JSON Lines file with one item per
line.

This module reads and checks items. It never creates, infers or changes a
label: reference labels are made by people (RFC-002, section 5).
"""

import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, ValidationInfo, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem
from utux.schemas.base import ContractDocument, ContractPart, field_problem, raise_field_problems
from utux.schemas.claim_ledger import (
    FLAG_SEVERITY,
    CheckedText,
    ClaimKind,
    ExtractionQuality,
    ScopeFlag,
    Severity,
    SourceLabel,
)
from utux.schemas.common import Count, Identifier, NonEmptyText, Sha256Hash
from utux.schemas.json_io import parse_json, read_json
from utux.schemas.text_io import read_contract_text

ItemId = Annotated[str, Field(pattern=r"^G[0-9]{4,}$", strict=True)]
"""The id of a gold item, for example `G0412`."""

GoldClaimId = Annotated[str, Field(pattern=r"^G[0-9]{4,}-c[0-9]+$", strict=True)]
"""The id of a reference claim: the item id and `-c<n>`, for example `G0412-c1`."""

PairId = Annotated[str, Field(pattern=r"^G[0-9]{4,}-c[0-9]+-s[0-9]+$", strict=True)]
"""The id of a claim-source pair: the claim id and `-s<n>`."""

AnnotatorId = Annotated[str, Field(pattern=r"^a[0-9]{2,}$", strict=True)]
"""A pseudonymous annotator id, for example `a03`. Never a name."""

GoldVersion = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", strict=True)]
"""A release version, `major.minor` (RFC-002, section 6)."""

SystemCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$", strict=True)]
"""A code for a system and its configuration, for example `utux-0.1.0-default`."""


class GoldSplit(StrEnum):
    """The split an item belongs to (RFC-002, section 6)."""

    DEV = "dev"
    TEST = "test"


class Domain(StrEnum):
    """The two v1 domains (RFC-002, section 2)."""

    ML = "ml"
    BIOMEDICINE = "biomedicine"


class Origin(StrEnum):
    """How an item was made (RFC-002, section 2)."""

    NATURAL = "natural"
    PERTURBED = "perturbed"
    SYSTEM_GENERATED = "system_generated"


class HardCase(StrEnum):
    """The seven hard-case groups of RFC-002, section 3."""

    ABSTRACT_VS_FULL_TEXT = "abstract_vs_full_text"
    NUMBER_WRONG_CONTEXT = "number_wrong_context"
    CONFLICT_WITHIN_SOURCE = "conflict_within_source"
    TRUE_BUT_NOT_IN_SOURCE = "true_but_not_in_source"
    ATTRIBUTED_PRIOR_WORK = "attributed_prior_work"
    HEAVY_PARAPHRASE = "heavy_paraphrase"
    NEGATION_OR_HEDGE = "negation_or_hedge"


class GoldStatus(StrEnum):
    """The four scientific statuses a reference label may take.

    `unverified` is an operational state of the system and never a reference
    label (RFC-002, section 3).
    """

    VERIFIED = "verified"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ErrorClass(StrEnum):
    """Whether a perturbed item was confirmed to hold only its target error."""

    SINGLE_ERROR = "single_error"
    MULTI_ERROR = "multi_error"


def _increasing(value: tuple[int, int], code: str) -> tuple[int, int]:
    if value[1] <= value[0]:
        raise PydanticCustomError(
            code,
            "the end ({end}) must be greater than the start ({start})",
            {"end": value[1], "start": value[0]},
        )
    return value


def _length(value: tuple[object, ...], low: int, high: int | None = None) -> None:
    # Checked after the elements, so an invalid element is not also reported
    # as a wrong length.
    if len(value) < low:
        raise PydanticCustomError(
            "too_short", "must have at least {low} entries, not {n}", {"low": low, "n": len(value)}
        )
    if high is not None and len(value) > high:
        raise PydanticCustomError(
            "too_long", "must have at most {high} entries, not {n}", {"high": high, "n": len(value)}
        )


Note = NonEmptyText | None
"""An annotator's free-text note, or null."""


def _reason_problems(adjudicated: bool, reason: str | None) -> list[InitErrorDetails]:
    """An adjudicated level has a written reason; any other level has none."""
    if adjudicated and reason is None:
        return [
            field_problem(
                "adjudication_reason_required",
                "an adjudicated level states the adjudicator's reason",
                "adjudication_reason",
            )
        ]
    if not adjudicated and reason is not None:
        return [
            field_problem(
                "adjudication_reason_not_allowed",
                "must be null when this level was not adjudicated",
                "adjudication_reason",
            )
        ]
    return []


def _distinct(values: tuple[str, ...], code: str, what: str) -> tuple[str, ...]:
    seen: set[str] = set()
    errors: list[InitErrorDetails] = []
    for index, value in enumerate(values):
        if value in seen:
            errors.append(field_problem(code, f"{what} {value} appears more than once", index))
        seen.add(value)
    raise_field_problems(what, errors)
    return values


class EvidenceSpan(ContractPart):
    """A passage of the stored source text that bears on the claim."""

    passage_id: NonEmptyText
    offsets: tuple[Count, Count]

    @field_validator("offsets")
    @classmethod
    def _offsets_increase(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value, "offsets_not_increasing")


def _spans(spans: tuple[EvidenceSpan, ...]) -> frozenset[tuple[str, tuple[int, int]]]:
    return frozenset((span.passage_id, span.offsets) for span in spans)


class PairRaw(ContractPart):
    """One annotator's labels for a claim-source pair, stored unchanged."""

    evidence_spans: tuple[EvidenceSpan, ...]
    agreement_label: SourceLabel
    scope_flags: tuple[ScopeFlag, ...]
    note: Note

    @field_validator("scope_flags")
    @classmethod
    def _flags_are_distinct(cls, value: tuple[ScopeFlag, ...]) -> tuple[ScopeFlag, ...]:
        _distinct(tuple(flag.value for flag in value), "duplicate_scope_flag", "scope flag")
        return value

    def key(self) -> tuple[object, ...]:
        """What is compared between annotators: spans and flags as sets."""
        return (_spans(self.evidence_spans), self.agreement_label, frozenset(self.scope_flags))


class GoldPair(ContractPart):
    """One claim-source pair with its reference labels; the unit for S2 to S5.

    `raw` holds each annotator's own labels; `adjudicated` says whether the
    adjudicator set the reference labels of this pair.
    """

    pair_id: PairId
    source_id: NonEmptyText
    source_group: NonEmptyText
    text_hash: Sha256Hash
    checked_text: CheckedText
    extraction_quality: ExtractionQuality
    evidence_spans: tuple[EvidenceSpan, ...]
    agreement_label: SourceLabel
    scope_flags: tuple[ScopeFlag, ...]
    raw: dict[str, PairRaw]
    adjudicated: StrictBool
    adjudication_reason: NonEmptyText | None

    @field_validator("scope_flags")
    @classmethod
    def _flags_are_distinct(cls, value: tuple[ScopeFlag, ...]) -> tuple[ScopeFlag, ...]:
        _distinct(tuple(flag.value for flag in value), "duplicate_scope_flag", "scope flag")
        return value

    @model_validator(mode="after")
    def _reason_fits(self) -> Self:
        raise_field_problems(
            "GoldPair", _reason_problems(self.adjudicated, self.adjudication_reason)
        )
        return self


class ClaimRaw(ContractPart):
    """One annotator's labels for a reference claim, stored unchanged."""

    status: GoldStatus
    expert_would_review: StrictBool
    note: Note

    def key(self) -> tuple[object, ...]:
        """What is compared between annotators: the note is left out."""
        return (self.status, self.expert_would_review)


class GoldClaim(ContractPart):
    """One reference atomic claim of the text unit.

    `raw` holds each annotator's own status and review flag; `adjudicated`
    says whether the adjudicator set them; `ambiguous` marks a claim that
    remained disputed after joint discussion.
    """

    claim_id: GoldClaimId
    text: NonEmptyText
    span: tuple[Count, Count]
    kind: ClaimKind
    pairs: tuple[GoldPair, ...]
    status: GoldStatus
    expert_would_review: StrictBool
    raw: dict[str, ClaimRaw]
    adjudicated: StrictBool
    adjudication_reason: NonEmptyText | None
    ambiguous: StrictBool

    @field_validator("span")
    @classmethod
    def _span_increases(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value, "span_not_increasing")

    @model_validator(mode="after")
    def _pair_ids_belong_to_the_claim(self) -> Self:
        errors = _reason_problems(self.adjudicated, self.adjudication_reason)
        if not self.pairs:
            # Only a claim that cites no source has no pairs (RFC-002, section 4).
            if self.status is not GoldStatus.INSUFFICIENT_EVIDENCE:
                errors.append(
                    field_problem(
                        "too_short",
                        "a claim needs at least one pair unless its status is "
                        "insufficient_evidence",
                        "pairs",
                    )
                )
            errors += [
                field_problem(
                    "raw_status_without_pairs",
                    "a claim without pairs has the raw status insufficient_evidence",
                    "raw",
                    annotator,
                    "status",
                )
                for annotator, raw in self.raw.items()
                # Checked only for a claim whose own status allows no pairs;
                # otherwise the missing pairs are the problem to report.
                if self.status is GoldStatus.INSUFFICIENT_EVIDENCE
                and raw.status is not GoldStatus.INSUFFICIENT_EVIDENCE
            ]
        seen: set[str] = set()
        for index, pair in enumerate(self.pairs):
            if not pair.pair_id.startswith(f"{self.claim_id}-s"):
                errors.append(
                    field_problem(
                        "pair_id_mismatch",
                        f"{pair.pair_id} does not start with the claim id {self.claim_id}",
                        "pairs",
                        index,
                        "pair_id",
                    )
                )
            elif pair.pair_id in seen:
                errors.append(
                    field_problem(
                        "duplicate_id",
                        f"{pair.pair_id} appears more than once",
                        "pairs",
                        index,
                        "pair_id",
                    )
                )
            seen.add(pair.pair_id)
        raise_field_problems("GoldClaim", errors)
        return self


class ExtractedClaim(ContractPart):
    """A claim as one annotator listed it at claim extraction.

    `kind` is the annotator's kind of the claim (guideline section 4.4).
    `citations` are the source ids the claim relies on (guideline section
    4.1); empty for a claim that cites no source.
    """

    span: tuple[Count, Count]
    text: NonEmptyText
    kind: ClaimKind
    citations: tuple[NonEmptyText, ...]

    @field_validator("span")
    @classmethod
    def _span_increases(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value, "span_not_increasing")

    @field_validator("citations")
    @classmethod
    def _citations_are_distinct(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _distinct(value, "duplicate_citation", "citation")


def _citations(claim: ExtractedClaim | GoldClaim) -> frozenset[str]:
    if isinstance(claim, ExtractedClaim):
        return frozenset(claim.citations)
    return frozenset(pair.source_id for pair in claim.pairs)


def _claim_set(
    claims: Sequence[ExtractedClaim | GoldClaim],
) -> frozenset[tuple[object, str, ClaimKind, frozenset[str]]]:
    """What is compared between claim lists: span, text, kind and citations as a set.

    A reference claim's citations are the sources of its pairs.
    """
    return frozenset((claim.span, claim.text, claim.kind, _citations(claim)) for claim in claims)


class ClaimExtraction(ContractPart):
    """Each annotator's own list of claims, and whether the lists were adjudicated."""

    raw: dict[str, tuple[ExtractedClaim, ...]]
    adjudicated: StrictBool
    adjudication_reason: NonEmptyText | None

    @model_validator(mode="after")
    def _reason_fits(self) -> Self:
        raise_field_problems(
            "ClaimExtraction", _reason_problems(self.adjudicated, self.adjudication_reason)
        )
        return self


def _raw_key_problems(
    raw: dict[str, object], annotators: tuple[str, ...], *loc: str | int
) -> list[InitErrorDetails]:
    """The raw entries must be exactly one per annotator."""
    errors: list[InitErrorDetails] = [
        {"type": "missing", "loc": (*loc, "raw", annotator), "input": None}
        for annotator in annotators
        if annotator not in raw
    ]
    errors += [
        field_problem("unknown_annotator", f"{key} is not one of the annotators", *loc, "raw", key)
        for key in raw
        if key not in annotators
    ]
    return errors


def _not_adjudicated(*loc: str | int) -> InitErrorDetails:
    return field_problem(
        "adjudication_required",
        "the annotators' raw entries differ here, so this level must be adjudicated",
        *loc,
        "adjudicated",
    )


def _differs(what: str, *loc: str | int) -> InitErrorDetails:
    return field_problem(
        "differs_from_raw",
        f"the annotators agree on the {what} and nothing was adjudicated, "
        "so the reference value must be theirs",
        *loc,
    )


class Annotation(ContractPart):
    """The two annotators, the adjudicator and the claim extraction."""

    annotators: tuple[AnnotatorId, ...]
    adjudicator: AnnotatorId | None
    claim_extraction: ClaimExtraction

    @field_validator("annotators")
    @classmethod
    def _two_distinct_annotators(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # Two annotators label each item (RFC-002, section 5).
        _length(value, 2, 2)
        return _distinct(value, "duplicate_annotator", "annotator")

    @model_validator(mode="after")
    def _extraction_agrees(self) -> Self:
        errors: list[InitErrorDetails] = []
        if self.adjudicator is not None and self.adjudicator in self.annotators:
            errors.append(
                field_problem(
                    "adjudicator_is_annotator",
                    f"the adjudicator {self.adjudicator} is one of the annotators",
                    "adjudicator",
                )
            )
        extraction = self.claim_extraction
        errors += _raw_key_problems(dict(extraction.raw), self.annotators, "claim_extraction")
        lists = [extraction.raw[a] for a in self.annotators if a in extraction.raw]
        if (
            len(lists) == 2
            and _claim_set(lists[0]) != _claim_set(lists[1])
            and not extraction.adjudicated
        ):
            errors.append(_not_adjudicated("claim_extraction"))
        raise_field_problems("Annotation", errors)
        return self


class PerturbationRecord(ContractPart):
    """The hidden record of a perturbed item.

    It is never shown to annotators or to the system, and is used only for
    analysis (RFC-002, section 4).
    """

    target_error: Identifier
    secondary_errors: tuple[Identifier, ...]
    error_class: ErrorClass
    confirmed_by: AnnotatorId
    source_item: ItemId

    @field_validator("secondary_errors")
    @classmethod
    def _errors_are_distinct(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _distinct(value, "duplicate_error", "error")


class GenerationRecord(ContractPart):
    """The hidden record of a system-generated item: what produced it."""

    generated_by: SystemCode


class GoldItem(ContractDocument):
    """One gold item (RFC-002, section 4).

    Attributes:
        item_id: Id of the item, unique within a release.
        gold_version: The release, `major.minor`.
        split: `dev` or `test`; null until the release is frozen, when
            `check_release` requires one (`split_not_set`).
        domain: `ml` or `biomedicine`.
        origin: `natural`, `perturbed` or `system_generated`.
        hard_case: The hard-case group of RFC-002, section 3, or null.
        text_unit: The text the claims come from.
        claims: The reference atomic claims, each with its pairs, labels and
            raw entries.
        annotation: Annotators, adjudicator and claim extraction.
        hidden: A `PerturbationRecord` for a perturbed item, a
            `GenerationRecord` for a system-generated one. Absent, not null,
            for a natural item.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    item_id: ItemId
    gold_version: GoldVersion
    split: GoldSplit | None
    domain: Domain
    origin: Origin
    hard_case: HardCase | None
    text_unit: NonEmptyText
    claims: tuple[GoldClaim, ...]
    annotation: Annotation
    hidden: PerturbationRecord | GenerationRecord | None = None

    @field_validator("claims")
    @classmethod
    def _has_a_claim(cls, value: tuple[GoldClaim, ...]) -> tuple[GoldClaim, ...]:
        _length(value, 1)
        return value

    @field_validator("hidden", mode="before")
    @classmethod
    def _record_of_the_origin(cls, value: object, info: ValidationInfo) -> object:
        # Runs only when the key is present, null included.
        origin = info.data.get("origin")
        if origin is None:
            # The origin is invalid and is reported on its own field.
            return None
        if origin is Origin.NATURAL:
            raise PydanticCustomError(
                "hidden_not_allowed", "a natural item has no hidden record; leave the key out"
            )
        if value is None or isinstance(value, PerturbationRecord | GenerationRecord):
            return value
        model = PerturbationRecord if origin is Origin.PERTURBED else GenerationRecord
        return model.model_validate(value)

    @model_validator(mode="after")
    def _parts_agree(self) -> Self:
        # One problem per offending value, on the field to change.
        errors: list[InitErrorDetails] = []
        if self.origin is not Origin.NATURAL and self.hidden is None:
            errors.append(
                field_problem(
                    "hidden_required",
                    f"an item of origin {self.origin.value} needs its hidden record",
                    "hidden",
                )
            )
        if isinstance(self.hidden, PerturbationRecord) and self.hidden.source_item == self.item_id:
            errors.append(
                field_problem(
                    "self_reference", "an item cannot be its own origin", "hidden", "source_item"
                )
            )
        errors += self._claim_problems()
        errors += self._raw_problems()
        raise_field_problems("GoldItem", errors)
        return self

    def _claim_problems(self) -> list[InitErrorDetails]:
        errors: list[InitErrorDetails] = []
        seen: set[str] = set()
        length = len(self.text_unit)
        for index, claim in enumerate(self.claims):
            if not claim.claim_id.startswith(f"{self.item_id}-c"):
                errors.append(
                    field_problem(
                        "claim_id_mismatch",
                        f"{claim.claim_id} does not start with the item id {self.item_id}",
                        "claims",
                        index,
                        "claim_id",
                    )
                )
            elif claim.claim_id in seen:
                errors.append(
                    field_problem(
                        "duplicate_id",
                        f"{claim.claim_id} appears more than once",
                        "claims",
                        index,
                        "claim_id",
                    )
                )
            seen.add(claim.claim_id)
            if claim.span[1] > length:
                errors.append(_out_of_range(claim.span[1], length, "claims", index, "span"))
        for annotator, extracted in self.annotation.claim_extraction.raw.items():
            for index, listed in enumerate(extracted):
                if listed.span[1] > length:
                    errors.append(
                        _out_of_range(
                            listed.span[1],
                            length,
                            "annotation",
                            "claim_extraction",
                            "raw",
                            annotator,
                            index,
                            "span",
                        )
                    )
        return errors

    def _raw_problems(self) -> list[InitErrorDetails]:
        """Check the raw entries, the adjudication and the reference values.

        Raw entries are one per annotator. Where they differ, the level is
        adjudicated; where they agree and nothing was adjudicated, the
        reference values are theirs.
        """
        errors: list[InitErrorDetails] = []
        annotators = self.annotation.annotators
        extraction = self.annotation.claim_extraction
        lists = [extraction.raw[a] for a in annotators if a in extraction.raw]
        if (
            len(lists) == 2
            and not extraction.adjudicated
            and _claim_set(lists[0]) == _claim_set(lists[1])
            and _claim_set(self.claims) != _claim_set(lists[0])
        ):
            errors.append(_differs("claim list", "claims"))
        adjudicated = extraction.adjudicated
        for i, claim in enumerate(self.claims):
            adjudicated = adjudicated or claim.adjudicated
            errors += _raw_key_problems(dict(claim.raw), annotators, "claims", i)
            entries = [claim.raw[a] for a in annotators if a in claim.raw]
            if len(entries) == 2:
                first, second = entries
                if first.key() != second.key() and not claim.adjudicated:
                    errors.append(_not_adjudicated("claims", i))
                if first.key() == second.key() and not claim.adjudicated:
                    if claim.status is not first.status:
                        errors.append(_differs("status", "claims", i, "status"))
                    if claim.expert_would_review is not first.expert_would_review:
                        errors.append(_differs("review flag", "claims", i, "expert_would_review"))
            for j, pair in enumerate(claim.pairs):
                adjudicated = adjudicated or pair.adjudicated
                errors += _pair_raw_problems(pair, annotators, "claims", i, "pairs", j)
        if adjudicated and self.annotation.adjudicator is None:
            errors.append(
                field_problem(
                    "adjudicator_required",
                    "something in the item was adjudicated, so it names its adjudicator",
                    "annotation",
                    "adjudicator",
                )
            )
        if not adjudicated and self.annotation.adjudicator is not None:
            errors.append(
                field_problem(
                    "adjudicator_not_allowed",
                    "must be null when nothing in the item was adjudicated",
                    "annotation",
                    "adjudicator",
                )
            )
        return errors

    @classmethod
    def from_json(cls, text: str, source: str = "gold item") -> Self:
        """Parse and validate the JSON text of one item.

        Raises:
            ContractValidationError: If the text is not a valid item.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json_line(self) -> str:
        """Return the item as one line of JSON that ends with a newline.

        A natural item has no `hidden` key.
        """
        document = self.model_dump(mode="json")
        if self.hidden is None:
            del document["hidden"]
        return json.dumps(document, ensure_ascii=False) + "\n"

    def pairs(self) -> list[tuple[int, int, GoldPair]]:
        """Return every pair with the index of its claim and its own index."""
        return [
            (claim_index, pair_index, pair)
            for claim_index, claim in enumerate(self.claims)
            for pair_index, pair in enumerate(claim.pairs)
        ]


def _out_of_range(end: int, length: int, *loc: str | int) -> InitErrorDetails:
    return field_problem(
        "span_out_of_range",
        f"the end ({end}) is beyond the text unit ({length} characters)",
        *loc,
    )


def _pair_raw_problems(
    pair: GoldPair, annotators: tuple[str, ...], *loc: str | int
) -> list[InitErrorDetails]:
    errors = _raw_key_problems(dict(pair.raw), annotators, *loc)
    entries = [pair.raw[a] for a in annotators if a in pair.raw]
    if len(entries) != 2 or pair.adjudicated:
        return errors
    first, second = entries
    if first.key() != second.key():
        errors.append(_not_adjudicated(*loc))
        return errors
    if _spans(pair.evidence_spans) != _spans(first.evidence_spans):
        errors.append(_differs("evidence spans", *loc, "evidence_spans"))
    if pair.agreement_label is not first.agreement_label:
        errors.append(_differs("agreement label", *loc, "agreement_label"))
    if frozenset(pair.scope_flags) != frozenset(first.scope_flags):
        errors.append(_differs("scope flags", *loc, "scope_flags"))
    return errors


def load_gold_item(path: Path) -> GoldItem:
    """Read and validate a file that holds one gold item as a JSON document.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            item. The error names the path as it was given.
    """
    return GoldItem.validate_document(read_json(path), str(path))


def read_gold_release(path: Path) -> tuple[GoldItem, ...]:
    """Read a release: a JSON Lines file with one gold item per line.

    Every line is checked, and every problem is reported, its field prefixed
    with the line number, for example `line 3, split`. The rules across items
    are checked separately by `check_release`.

    Raises:
        ContractValidationError: If the file cannot be read, a line is empty,
            or an item is invalid.
    """
    text = read_contract_text(path)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        # The newline that ends the last line.
        lines.pop()
    items: list[GoldItem] = []
    problems: list[Problem] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            problems.append(Problem(f"line {number}", "the line is empty", "empty_line"))
            continue
        try:
            items.append(GoldItem.from_json(line, str(path)))
        except ContractValidationError as error:
            problems += [
                Problem(_on_line(number, problem.field), problem.reason, problem.code)
                for problem in error.problems
            ]
    if problems:
        raise ContractValidationError(str(path), tuple(problems))
    return tuple(items)


def _on_line(number: int, field: str) -> str:
    return f"line {number}" if field == DOCUMENT_FIELD else f"line {number}, {field}"


@dataclass(frozen=True)
class ReleaseCheck:
    """The result of `check_release`.

    Attributes:
        problems: Breaches of the rules across items; a release with any is
            not valid.
        departures: Reference labels that depart from the annotation
            guideline's rules. They are reported for the adjudicator and do
            not make the release invalid, because the adjudicator may depart
            from a rule with a written reason.
    """

    problems: tuple[Problem, ...]
    departures: tuple[Problem, ...]


_SEVERE = frozenset({Severity.MAJOR, Severity.CRITICAL})


def guideline_status(labels: Sequence[str], flags: Sequence[Collection[str]]) -> GoldStatus:
    """Return the status that the guideline's rules give (section 5.4).

    `labels` holds the agreement label of each pair of a claim and `flags`
    the scope flags of the same pairs. The rules are applied in order:

    1. No sources: `insufficient_evidence`.
    2. Any pair `conflicting`: `insufficient_evidence`.
    3. A pair `entails` or `partial` and another `contradicts`:
       `insufficient_evidence`.
    4. Every pair that is not `neutral` is `entails`, at least one is, and no
       pair has a major or critical flag: `verified`.
    5. A pair `entails` or `partial`: `partially_supported`.
    6. A pair `contradicts`: `contradicted`.
    7. Otherwise (every pair `neutral`): `insufficient_evidence`.

    This checks reference labels made by people; it never sets one.
    """
    supports = {"entails", "partial"}
    if not labels or "conflicting" in labels:
        return GoldStatus.INSUFFICIENT_EVIDENCE
    if supports & set(labels) and "contradicts" in labels:
        return GoldStatus.INSUFFICIENT_EVIDENCE
    severe = any(FLAG_SEVERITY[ScopeFlag(flag)] in _SEVERE for pair in flags for flag in pair)
    if (
        "entails" in labels
        and not severe
        and all(label in ("entails", "neutral") for label in labels)
    ):
        return GoldStatus.VERIFIED
    if supports & set(labels):
        return GoldStatus.PARTIALLY_SUPPORTED
    if "contradicts" in labels:
        return GoldStatus.CONTRADICTED
    return GoldStatus.INSUFFICIENT_EVIDENCE


def _departures(items: Sequence[GoldItem]) -> list[Problem]:
    departures: list[Problem] = []
    for item in items:
        for i, claim in enumerate(item.claims):
            for j, pair in enumerate(claim.pairs):
                if pair.agreement_label is SourceLabel.NEUTRAL and pair.scope_flags:
                    departures.append(
                        Problem(
                            f"{item.item_id}.claims.{i}.pairs.{j}.scope_flags",
                            "a neutral pair gets no flags (guideline section 5.3)",
                            "flags_on_neutral_pair",
                        )
                    )
            expected = guideline_status(
                [pair.agreement_label.value for pair in claim.pairs],
                [[flag.value for flag in pair.scope_flags] for pair in claim.pairs],
            )
            if claim.status is not expected:
                departures.append(
                    Problem(
                        f"{item.item_id}.claims.{i}.status",
                        f"{claim.status.value} differs from {expected.value}, the status "
                        "the guideline's rules give (section 5.4)",
                        "status_differs_from_rules",
                    )
                )
    return departures


def check_release(items: Sequence[GoldItem]) -> ReleaseCheck:
    """Check the rules that hold across the items of one release.

    - Item ids are unique.
    - Every item has the version of the first item.
    - A perturbed item's origin is in the release, is a natural item, and is
      in the same split (RFC-002, section 6).
    - A source has one source group and one text hash throughout.
    - Every item has a split (`split_not_set`); the split rules are checked
      among the items that have one.
    - No source group is in both splits. Each such group is reported once,
      on the first pair, in release order, whose item is in another split
      than the first item of the group.

    Each problem's field starts with the id of the item to change, for
    example `G0412.split`.

    It also reports, without making the release invalid, each departure from
    the annotation guideline: flags on a `neutral` pair (section 5.3), and a
    claim status other than the one `guideline_status` gives (section 5.4).

    Returns:
        The problems and the departures; each is empty when there are none.
    """
    problems: list[Problem] = [
        Problem(
            f"{item.item_id}.split",
            "the item has no split yet; a frozen release has dev or test for every item",
            "split_not_set",
        )
        for item in items
        if item.split is None
    ]
    by_id: dict[str, GoldItem] = {}
    for item in items:
        if item.item_id in by_id:
            problems.append(
                Problem(
                    f"{item.item_id}.item_id",
                    f"the item id {item.item_id} appears more than once",
                    "duplicate_item_id",
                )
            )
        else:
            by_id[item.item_id] = item
    if items:
        version = items[0].gold_version
        problems += [
            Problem(
                f"{item.item_id}.gold_version",
                f"{item.gold_version} differs from the release version {version}",
                "gold_version_mismatch",
            )
            for item in items
            if item.gold_version != version
        ]
    problems += _origin_problems(items, by_id)
    problems += _source_problems(items)
    problems += _group_problems(items)
    return ReleaseCheck(tuple(problems), tuple(_departures(items)))


def _origin_problems(items: Sequence[GoldItem], by_id: dict[str, GoldItem]) -> list[Problem]:
    problems: list[Problem] = []
    for item in items:
        if not isinstance(item.hidden, PerturbationRecord):
            continue
        source = item.hidden.source_item
        origin = by_id.get(source)
        field = f"{item.item_id}.hidden.source_item"
        if origin is None:
            problems.append(
                Problem(field, f"the origin {source} is not in the release", "unknown_source_item")
            )
        elif origin.origin is not Origin.NATURAL:
            problems.append(
                Problem(
                    field,
                    f"the origin {source} is {origin.origin.value}, not a natural item",
                    "source_item_not_natural",
                )
            )
        elif origin.split is not None and item.split is not None and origin.split is not item.split:
            problems.append(
                Problem(
                    f"{item.item_id}.split",
                    f"{item.split.value} differs from the split of its origin {source} "
                    f"({origin.split.value})",
                    "split_differs_from_origin",
                )
            )
    return problems


def _pair_field(item: GoldItem, claim: int, pair: int, name: str) -> str:
    return f"{item.item_id}.claims.{claim}.pairs.{pair}.{name}"


def _source_problems(items: Sequence[GoldItem]) -> list[Problem]:
    problems: list[Problem] = []
    first: dict[str, GoldPair] = {}
    for item in items:
        for claim, index, pair in item.pairs():
            known = first.setdefault(pair.source_id, pair)
            if pair.source_group != known.source_group:
                problems.append(
                    Problem(
                        _pair_field(item, claim, index, "source_group"),
                        f"the source {pair.source_id} is in the group {known.source_group} "
                        "elsewhere in the release",
                        "source_group_mismatch",
                    )
                )
            if pair.text_hash != known.text_hash:
                problems.append(
                    Problem(
                        _pair_field(item, claim, index, "text_hash"),
                        f"the source {pair.source_id} has another text hash elsewhere "
                        "in the release",
                        "text_hash_mismatch",
                    )
                )
    return problems


def _group_problems(items: Sequence[GoldItem]) -> list[Problem]:
    problems: list[Problem] = []
    split_of_group: dict[str, GoldSplit] = {}
    reported: set[str] = set()
    for item in items:
        if item.split is None:
            continue
        for claim, index, pair in item.pairs():
            group = pair.source_group
            split = split_of_group.setdefault(group, item.split)
            if split is not item.split and group not in reported:
                reported.add(group)
                problems.append(
                    Problem(
                        _pair_field(item, claim, index, "source_group"),
                        f"the source group {group} is in both splits",
                        "source_group_in_both_splits",
                    )
                )
    return problems


__all__ = [
    "Annotation",
    "AnnotatorId",
    "ClaimExtraction",
    "ClaimRaw",
    "Domain",
    "ErrorClass",
    "EvidenceSpan",
    "ExtractedClaim",
    "GenerationRecord",
    "GoldClaim",
    "GoldItem",
    "GoldPair",
    "GoldSplit",
    "GoldStatus",
    "HardCase",
    "ItemId",
    "Origin",
    "PairRaw",
    "PerturbationRecord",
    "ReleaseCheck",
    "check_release",
    "guideline_status",
    "load_gold_item",
    "read_gold_release",
]
