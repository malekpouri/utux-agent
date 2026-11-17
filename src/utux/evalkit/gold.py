"""The gold item schema of RFC-002, section 4, and the checks across a release.

One gold item is one text unit with its reference claims, the claim-source
pairs, the reference labels, both annotators' raw labels and, for a perturbed
item, the hidden construction record. A release is a JSON Lines file with one
item per line.

This module reads and checks items. It never creates, infers or changes a
label: reference labels are made by people (RFC-002, section 5).
"""

import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem
from utux.schemas.base import ContractDocument, ContractPart, field_problem, raise_field_problems
from utux.schemas.claim_ledger import (
    CheckedText,
    ClaimKind,
    ExtractionQuality,
    ScopeFlag,
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


class GoldPair(ContractPart):
    """One claim-source pair with its reference labels; the unit for S2 to S5."""

    pair_id: PairId
    source_id: NonEmptyText
    source_group: NonEmptyText
    text_hash: Sha256Hash
    checked_text: CheckedText
    extraction_quality: ExtractionQuality
    evidence_spans: tuple[EvidenceSpan, ...]
    agreement_label: SourceLabel
    scope_flags: tuple[ScopeFlag, ...]

    @field_validator("scope_flags")
    @classmethod
    def _flags_are_distinct(cls, value: tuple[ScopeFlag, ...]) -> tuple[ScopeFlag, ...]:
        _distinct(tuple(flag.value for flag in value), "duplicate_scope_flag", "scope flag")
        return value


class GoldClaim(ContractPart):
    """One reference atomic claim of the text unit."""

    claim_id: GoldClaimId
    text: NonEmptyText
    span: tuple[Count, Count]
    kind: ClaimKind
    pairs: tuple[GoldPair, ...]
    status: GoldStatus
    expert_would_review: StrictBool

    @field_validator("pairs")
    @classmethod
    def _has_a_pair(cls, value: tuple[GoldPair, ...]) -> tuple[GoldPair, ...]:
        _length(value, 1)
        return value

    @field_validator("span")
    @classmethod
    def _span_increases(cls, value: tuple[int, int]) -> tuple[int, int]:
        return _increasing(value, "span_not_increasing")

    @model_validator(mode="after")
    def _pair_ids_belong_to_the_claim(self) -> Self:
        errors: list[InitErrorDetails] = []
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


class RawLabel(ContractPart):
    """One annotator's labels, stored unchanged (RFC-002, section 5)."""

    agreement_label: SourceLabel
    status: GoldStatus


class Annotation(ContractPart):
    """Who labelled the item, both raw label sets and the adjudication."""

    annotators: tuple[AnnotatorId, ...]
    adjudicated: StrictBool
    adjudicator: AnnotatorId | None
    raw_labels: dict[str, RawLabel]
    ambiguous: StrictBool

    @field_validator("annotators")
    @classmethod
    def _annotators_are_distinct(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # Two annotators label each item (RFC-002, section 5).
        _length(value, 2, 2)
        return _distinct(value, "duplicate_annotator", "annotator")

    @model_validator(mode="after")
    def _labels_and_adjudication_agree(self) -> Self:
        errors: list[InitErrorDetails] = []
        if self.adjudicated and self.adjudicator is None:
            errors.append(
                field_problem(
                    "adjudicator_required",
                    "an adjudicated item names its adjudicator",
                    "adjudicator",
                )
            )
        if not self.adjudicated and self.adjudicator is not None:
            errors.append(
                field_problem(
                    "adjudicator_not_allowed",
                    "must be null for an item that was not adjudicated",
                    "adjudicator",
                )
            )
        if self.adjudicator is not None and self.adjudicator in self.annotators:
            errors.append(
                field_problem(
                    "adjudicator_is_annotator",
                    f"the adjudicator {self.adjudicator} is one of the annotators",
                    "adjudicator",
                )
            )
        for annotator in self.annotators:
            if annotator not in self.raw_labels:
                errors.append(
                    {
                        "type": "missing",
                        "loc": ("raw_labels", annotator),
                        "input": None,
                    }
                )
        for key in self.raw_labels:
            if key not in self.annotators:
                errors.append(
                    field_problem(
                        "unknown_annotator",
                        f"{key} is not one of the annotators",
                        "raw_labels",
                        key,
                    )
                )
        labels = [self.raw_labels[a] for a in self.annotators if a in self.raw_labels]
        if len(labels) == 2 and labels[0] != labels[1] and not self.adjudicated:
            errors.append(
                field_problem(
                    "adjudication_required",
                    "the annotators' raw labels differ, so the item must be adjudicated",
                    "adjudicated",
                )
            )
        raise_field_problems("Annotation", errors)
        return self


class Hidden(ContractPart):
    """The construction record of a perturbed item.

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


class GoldItem(ContractDocument):
    """One gold item (RFC-002, section 4).

    Attributes:
        item_id: Id of the item, unique within a release.
        gold_version: The release, `major.minor`.
        split: `dev` or `test`.
        domain: `ml` or `biomedicine`.
        origin: `natural`, `perturbed` or `system_generated`.
        hard_case: A code for the hard-case group the item belongs to, or
            null (RFC-002, section 3).
        text_unit: The text the claims come from.
        claims: The reference atomic claims, each with its pairs and status.
        annotation: Annotators, raw labels, adjudication and `ambiguous`.
        hidden: The construction record. Required for a perturbed item and
            null for every other item.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    item_id: ItemId
    gold_version: GoldVersion
    split: GoldSplit
    domain: Domain
    origin: Origin
    hard_case: Identifier | None
    text_unit: NonEmptyText
    claims: tuple[GoldClaim, ...]
    annotation: Annotation
    hidden: Hidden | None

    @field_validator("claims")
    @classmethod
    def _has_a_claim(cls, value: tuple[GoldClaim, ...]) -> tuple[GoldClaim, ...]:
        _length(value, 1)
        return value

    @model_validator(mode="after")
    def _parts_agree(self) -> Self:
        # One problem per offending value, on the field to change.
        errors: list[InitErrorDetails] = []
        if self.origin is Origin.PERTURBED and self.hidden is None:
            errors.append(
                field_problem(
                    "hidden_required", "a perturbed item needs its construction record", "hidden"
                )
            )
        if self.origin is not Origin.PERTURBED and self.hidden is not None:
            errors.append(
                field_problem(
                    "hidden_not_allowed",
                    f"must be null for an item of origin {self.origin.value}",
                    "hidden",
                )
            )
        if self.hidden is not None and self.hidden.source_item == self.item_id:
            errors.append(
                field_problem(
                    "self_reference", "an item cannot be its own origin", "hidden", "source_item"
                )
            )
        seen: set[str] = set()
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
            if claim.span[1] > len(self.text_unit):
                errors.append(
                    field_problem(
                        "span_out_of_range",
                        f"the end ({claim.span[1]}) is beyond the text unit "
                        f"({len(self.text_unit)} characters)",
                        "claims",
                        index,
                        "span",
                    )
                )
        raise_field_problems("GoldItem", errors)
        return self

    @classmethod
    def from_json(cls, text: str, source: str = "gold item") -> Self:
        """Parse and validate the JSON text of one item.

        Raises:
            ContractValidationError: If the text is not a valid item.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json_line(self) -> str:
        """Return the item as one line of JSON that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"

    def pairs(self) -> list[tuple[int, int, GoldPair]]:
        """Return every pair with the index of its claim and its own index."""
        return [
            (claim_index, pair_index, pair)
            for claim_index, claim in enumerate(self.claims)
            for pair_index, pair in enumerate(claim.pairs)
        ]


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


def check_release(items: Sequence[GoldItem]) -> tuple[Problem, ...]:
    """Check the rules that hold across the items of one release.

    - Item ids are unique.
    - Every item has the version of the first item.
    - A perturbed item's origin is in the release, is a natural item, and is
      in the same split (RFC-002, section 6).
    - A source has one source group and one text hash throughout.
    - No source group is in both splits. Each such group is reported once,
      on the first pair, in release order, whose item is in another split
      than the first item of the group.

    Each problem's field starts with the id of the item to change, for
    example `G0412.split`.

    Returns:
        Every problem found, or an empty tuple.
    """
    problems: list[Problem] = []
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
    return tuple(problems)


def _origin_problems(items: Sequence[GoldItem], by_id: dict[str, GoldItem]) -> list[Problem]:
    problems: list[Problem] = []
    for item in items:
        if item.hidden is None:
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
        elif origin.split is not item.split:
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
    "Domain",
    "ErrorClass",
    "EvidenceSpan",
    "GoldClaim",
    "GoldItem",
    "GoldPair",
    "GoldSplit",
    "GoldStatus",
    "Hidden",
    "ItemId",
    "Origin",
    "RawLabel",
    "check_release",
    "load_gold_item",
    "read_gold_release",
]
