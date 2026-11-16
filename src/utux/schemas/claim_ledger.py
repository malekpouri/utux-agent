"""Schema of a claim ledger entry, a line of `claims.jsonl`.

The fields and the closed sets of values are those of RFC-001, section 6,
for every claim type. This module only describes what a stored entry may
hold. It contains no verification logic: which status a claim gets is decided
by the deterministic rules of RFC-001, which are built in milestone M2.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    Field,
    StrictBool,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.common import (
    ClaimId,
    Count,
    NonEmptyText,
    RelativePath,
    ResultId,
    Sha256Hash,
    UtcTimestamp,
)
from utux.schemas.json_io import parse_json, read_json


class ClaimType(StrEnum):
    """Where a claim's support comes from."""

    LITERATURE = "literature"
    RESULT = "result"
    DERIVED = "derived"


class ClaimKind(StrEnum):
    """The kind of assertion, tagged at claim extraction (RFC-001, S1)."""

    FINDING = "finding"
    QUANTITATIVE = "quantitative"
    METHOD = "method"
    DEFINITION = "definition"
    BACKGROUND = "background"


class ClaimStatus(StrEnum):
    """The four scientific statuses, and `unverified` for a claim not yet checked."""

    VERIFIED = "verified"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNVERIFIED = "unverified"


class Confidence(StrEnum):
    """Ordinal confidence level, set by rule and not reported by a model."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AgreementLabel(StrEnum):
    """The label of one claim-passage pair (RFC-001, S3)."""

    ENTAILS = "entails"
    PARTIAL = "partial"
    NEUTRAL = "neutral"
    CONTRADICTS = "contradicts"


class SourceLabel(StrEnum):
    """The label of one claim-source pair.

    The four agreement labels, or `conflicting` when one passage of the
    source entails the claim and another contradicts it.
    """

    ENTAILS = "entails"
    PARTIAL = "partial"
    NEUTRAL = "neutral"
    CONTRADICTS = "contradicts"
    CONFLICTING = "conflicting"


class ScopeFlag(StrEnum):
    """The seven scope flags of RFC-001, S4."""

    DIRECTION_MISMATCH = "direction_mismatch"
    CAUSAL_OVERREACH = "causal_overreach"
    MAGNITUDE_MISMATCH = "magnitude_mismatch"
    OVERGENERALISATION = "overgeneralisation"
    METRIC_MISMATCH = "metric_mismatch"
    CERTAINTY_ESCALATION = "certainty_escalation"
    MISSING_COMPARATOR = "missing_comparator"


class Severity(StrEnum):
    """How serious a scope flag is."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


FLAG_SEVERITY: dict[ScopeFlag, Severity] = {
    ScopeFlag.DIRECTION_MISMATCH: Severity.CRITICAL,
    ScopeFlag.CAUSAL_OVERREACH: Severity.CRITICAL,
    ScopeFlag.MAGNITUDE_MISMATCH: Severity.CRITICAL,
    ScopeFlag.OVERGENERALISATION: Severity.MAJOR,
    ScopeFlag.METRIC_MISMATCH: Severity.MAJOR,
    ScopeFlag.CERTAINTY_ESCALATION: Severity.MINOR,
    ScopeFlag.MISSING_COMPARATOR: Severity.MINOR,
}
"""The severity RFC-001 gives each scope flag (table in S4)."""


class Reason(StrEnum):
    """Machine-readable causes of a verdict: the scope flags and nine others."""

    DIRECTION_MISMATCH = "direction_mismatch"
    CAUSAL_OVERREACH = "causal_overreach"
    MAGNITUDE_MISMATCH = "magnitude_mismatch"
    OVERGENERALISATION = "overgeneralisation"
    METRIC_MISMATCH = "metric_mismatch"
    CERTAINTY_ESCALATION = "certainty_escalation"
    MISSING_COMPARATOR = "missing_comparator"
    NO_SOURCE = "no_source"
    NO_TEXT = "no_text"
    NO_EVIDENCE_FOUND = "no_evidence_found"
    ASSESSOR_DISAGREEMENT = "assessor_disagreement"
    CONFLICT_WITHIN_SOURCE = "conflict_within_source"
    CONFLICT_ACROSS_SOURCES = "conflict_across_sources"
    CITATION_NOT_SUPPORTING = "citation_not_supporting"
    SECOND_ASSESSOR_UNAVAILABLE = "second_assessor_unavailable"
    DEGRADED_SOURCE_TEXT = "degraded_source_text"


class CheckedText(StrEnum):
    """Which text of a source was checked."""

    ABSTRACT = "abstract"
    FULL_TEXT = "full_text"


class ExtractionQuality(StrEnum):
    """How reliable the stored text of a source is (RFC-001, S2)."""

    CLEAN = "clean"
    GOOD = "good"
    DEGRADED = "degraded"


class Span(ContractPart):
    """Where the claim sits in a file of the project, as character offsets."""

    file: RelativePath
    start: Count
    end: Count

    @field_validator("end")
    @classmethod
    def _end_is_after_start(cls, value: int, info: ValidationInfo) -> int:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise PydanticCustomError(
                "span_end_not_after_start",
                "the end ({end}) must be greater than the start ({start})",
                {"end": value, "start": start},
            )
        return value


class ScopeFlagEntry(ContractPart):
    """One scope flag with the two slots that disagree."""

    flag: ScopeFlag
    severity: Severity
    claim_slot: NonEmptyText
    evidence_slot: NonEmptyText

    @field_validator("severity")
    @classmethod
    def _severity_is_the_one_of_the_flag(cls, value: Severity, info: ValidationInfo) -> Severity:
        flag = info.data.get("flag")
        if flag is not None and FLAG_SEVERITY[flag] is not value:
            raise PydanticCustomError(
                "severity_mismatch",
                "the severity of {flag} is {expected}",
                {"flag": flag.value, "expected": FLAG_SEVERITY[flag].value},
            )
        return value


class SourceEvidence(ContractPart):
    """Evidence for a literature claim: one entry per cited source.

    Attributes:
        source_id: Identifier of the source, such as a DOI.
        passage_id: The passage of the stored source text that holds the quote.
        offsets: Start and end of the quote in the stored text.
        quote: The verbatim quote that decides the primary label. For a
            conflicting source it is the contradicting passage; the trace
            holds every passage with its label.
        checked_text: Whether the abstract or the full text was checked.
        extraction_quality: How reliable the stored text is.
        primary_label: The source-level label of the first assessment.
        secondary_label: The source-level label of the independent
            assessment, or null when that assessment did not run.
        scope_flags: The scope flags raised for this source.
    """

    evidence_type: Literal["source"]
    source_id: NonEmptyText
    passage_id: NonEmptyText
    offsets: tuple[Count, Count]
    quote: NonEmptyText
    checked_text: CheckedText
    extraction_quality: ExtractionQuality
    primary_label: SourceLabel
    secondary_label: SourceLabel | None
    scope_flags: tuple[ScopeFlagEntry, ...]

    @field_validator("offsets")
    @classmethod
    def _offsets_increase(cls, value: tuple[int, int]) -> tuple[int, int]:
        if value[1] <= value[0]:
            raise PydanticCustomError(
                "offsets_not_increasing",
                "the end offset ({end}) must be greater than the start offset ({start})",
                {"end": value[1], "start": value[0]},
            )
        return value


class ResultRecordEvidence(ContractPart):
    """Evidence for a result claim: the id of a result record."""

    evidence_type: Literal["result_record"]
    id: ResultId


class ClaimEvidence(ContractPart):
    """Evidence for a derived claim: the id of a claim it follows from."""

    evidence_type: Literal["claim"]
    id: ClaimId


_EVIDENCE_MODELS: dict[str, type[SourceEvidence | ResultRecordEvidence | ClaimEvidence]] = {
    "source": SourceEvidence,
    "result_record": ResultRecordEvidence,
    "claim": ClaimEvidence,
}

# The evidence type each claim type takes.
EVIDENCE_FOR: dict[ClaimType, str] = {
    ClaimType.LITERATURE: "source",
    ClaimType.RESULT: "result_record",
    ClaimType.DERIVED: "claim",
}


def _pick_evidence(
    value: object, handler: ValidatorFunctionWrapHandler
) -> SourceEvidence | ResultRecordEvidence | ClaimEvidence:
    """Validate an evidence entry against the model its `evidence_type` names.

    Pydantic's own handling of a tagged union puts the tag into the path of
    every error. Choosing the model here keeps paths exact, for example
    `evidence.0.quote`.
    """
    if isinstance(value, SourceEvidence | ResultRecordEvidence | ClaimEvidence):
        return value
    if not isinstance(value, dict):
        raise ValidationError.from_exception_data(
            "evidence", [{"type": "dict_type", "loc": (), "input": None}]
        )
    if "evidence_type" not in value:
        raise ValidationError.from_exception_data(
            "evidence", [{"type": "missing", "loc": ("evidence_type",), "input": None}]
        )
    tag = value["evidence_type"]
    model = _EVIDENCE_MODELS.get(tag) if isinstance(tag, str) else None
    if model is None:
        unknown = PydanticCustomError(
            "enum", "Input should be 'source', 'result_record' or 'claim'"
        )
        raise ValidationError.from_exception_data(
            "evidence", [{"type": unknown, "loc": ("evidence_type",), "input": None}]
        )
    return model.model_validate(value)


Evidence = Annotated[
    SourceEvidence | ResultRecordEvidence | ClaimEvidence,
    Field(discriminator="evidence_type"),
    WrapValidator(_pick_evidence),
]
"""One evidence entry: `source`, `result_record` or `claim`, by `evidence_type`."""


class HumanReview(ContractPart):
    """The decision of a person who reviewed the claim.

    The machine verdict stays in the entry's own `status` and `confidence`.
    """

    reviewer: Annotated[str, Field(pattern=r"^human:[a-z0-9][a-z0-9_.-]*$", strict=True)]
    decision: ClaimStatus
    note: NonEmptyText | None
    reviewed_at: UtcTimestamp


VerifiedBy = Annotated[
    str,
    Field(pattern=r"^([a-z][a-z0-9_]*@[0-9]+|human:[a-z0-9][a-z0-9_.-]*)$", strict=True),
]
"""A check with its protocol version, such as `support_check@1`, or `human:<id>`."""

CheckId = Annotated[str, Field(pattern=r"^k-[0-9]{6,}$", strict=True)]
"""The id of one run of a check, for example `k-000218`."""


class ClaimLedgerEntry(ContractDocument):
    """One claim with its verdict and enough to audit it. Every field is required.

    Attributes:
        id: Id of the claim.
        type: Where the claim's support comes from.
        kind: The kind of assertion.
        text: The claim.
        span: Where the claim sits in the project's text.
        status: The verdict.
        confidence: Ordinal level. `high` and `medium` require `verified`.
        needs_human: Whether the claim goes to human review.
        reasons: Machine-readable causes of the verdict.
        evidence: The evidence entries. A literature claim takes only
            `source` entries, a result claim only `result_record` entries and
            a derived claim only `claim` entries. A verified claim has at
            least one.
        verified_by: The checks, with their versions, and people behind the
            verdict.
        check_id: The check run that set the verdict, or null if none ran.
        trace: Path to the full record of that run, or null.
        claim_hash: Hash of the claim text and its source ids.
        checked_at: When the check ran, or null.
        human: The human review, or null.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    id: ClaimId
    type: ClaimType
    kind: ClaimKind
    text: NonEmptyText
    span: Span
    status: ClaimStatus
    confidence: Confidence
    needs_human: StrictBool
    reasons: tuple[Reason, ...]
    evidence: tuple[Evidence, ...]
    verified_by: tuple[VerifiedBy, ...]
    check_id: CheckId | None
    trace: RelativePath | None
    claim_hash: Sha256Hash
    checked_at: UtcTimestamp | None
    human: HumanReview | None

    @model_validator(mode="after")
    def _fields_agree(self) -> Self:
        # One problem per offending value, on the field the user must change.
        errors: list[InitErrorDetails] = []
        if self.confidence is not Confidence.LOW and self.status is not ClaimStatus.VERIFIED:
            errors.append(
                {
                    "type": PydanticCustomError(
                        "confidence_requires_verified",
                        "confidence {confidence} requires the status verified, not {status}",
                        {"confidence": self.confidence.value, "status": self.status.value},
                    ),
                    "loc": ("confidence",),
                    "input": None,
                }
            )
        if self.status is ClaimStatus.VERIFIED and not self.evidence:
            errors.append(
                {
                    "type": PydanticCustomError(
                        "evidence_required", "a verified claim needs at least one evidence entry"
                    ),
                    "loc": ("evidence",),
                    "input": None,
                }
            )
        expected = EVIDENCE_FOR[self.type]
        for position, entry in enumerate(self.evidence):
            if entry.evidence_type != expected:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "evidence_type_mismatch",
                            "a {claim} claim takes only {expected} evidence, not {found}",
                            {
                                "claim": self.type.value,
                                "expected": expected,
                                "found": entry.evidence_type,
                            },
                        ),
                        "loc": ("evidence", position, "evidence_type"),
                        "input": None,
                    }
                )
            elif isinstance(entry, ClaimEvidence) and entry.id == self.id:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "self_reference", "a claim cannot follow from itself"
                        ),
                        "loc": ("evidence", position, "id"),
                        "input": None,
                    }
                )
        if errors:
            raise ValidationError.from_exception_data(type(self).__name__, errors)
        return self

    @classmethod
    def from_json(cls, text: str, source: str = "claim ledger entry") -> Self:
        """Parse and validate the JSON text of one ledger entry.

        Raises:
            ContractValidationError: If the text is not a valid entry.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json_line(self) -> str:
        """Return the entry as one line of JSON that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


def load_claim_ledger_entry(path: Path) -> ClaimLedgerEntry:
    """Read and validate a file that holds one ledger entry as a JSON document.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            entry. The error names the path as it was given.
    """
    return ClaimLedgerEntry.validate_document(read_json(path), str(path))
