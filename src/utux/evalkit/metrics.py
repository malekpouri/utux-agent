"""Metrics of RFC-002, section 7, each on its stated unit.

- Claim: status (S6) per-label scores and macro-F1, the four headline
  metrics, the failure rate, and the human-review flag. A claim with several
  sources is counted once.
- Pair: agreement label (S3 and S5) per-label scores and macro-F1, and each
  scope flag (S4) as its own yes-or-no label, with micro and macro averages.

Ambiguous claims, and their pairs, are excluded from the primary metrics and
scored separately. Results hold counts and rates only: no item, claim or pair
id and no label of an item. `metrics_only` is the mode for test runs.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldClaim, GoldItem, GoldPair, GoldStatus
from utux.schemas.claim_ledger import ClaimStatus, ScopeFlag, SourceLabel


@dataclass(frozen=True)
class ClaimPrediction:
    """The system's output for one claim.

    Attributes:
        status: The status the system gave, `unverified` included.
        sent_to_review: Whether the system sent the claim to human review.
        failure_reason: Why the claim was left `unverified`; required then,
            and None otherwise.
    """

    status: ClaimStatus
    sent_to_review: bool
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        """Check that a failure reason is given exactly for `unverified`."""
        unverified = self.status is ClaimStatus.UNVERIFIED
        if unverified and not self.failure_reason:
            raise GoldSetError("an unverified prediction needs a failure reason")
        if not unverified and self.failure_reason is not None:
            raise GoldSetError("only an unverified prediction has a failure reason")


@dataclass(frozen=True)
class PairPrediction:
    """The system's output for one claim-source pair.

    `agreement_label` is None when the pair was not assessed; it then counts
    as a miss for the reference label.
    """

    agreement_label: SourceLabel | None
    scope_flags: frozenset[ScopeFlag] = frozenset()


@dataclass(frozen=True)
class Predictions:
    """The system's output for a release, by claim id and by pair id."""

    claims: Mapping[str, ClaimPrediction]
    pairs: Mapping[str, PairPrediction]


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else float(Fraction(numerator, denominator))


@dataclass(frozen=True)
class Rate:
    """A share with its counts, so that an interval can be computed from it."""

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        """Numerator / denominator, or None when the denominator is zero."""
        return _ratio(self.numerator, self.denominator)

    def to_json(self) -> dict[str, object]:
        """Return the rate as a JSON object."""
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


@dataclass(frozen=True)
class LabelScore:
    """Counts and scores of one label.

    Precision is None when the system never gave the label, recall when the
    reference never has it, and F1 when neither has it. The false-positive
    rate is FP over the units whose reference label is not this one.
    """

    tp: int
    fp: int
    fn: int
    negatives: int

    @property
    def precision(self) -> float | None:
        """TP / (TP + FP)."""
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float | None:
        """TP / (TP + FN)."""
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float | None:
        """2TP / (2TP + FP + FN), the harmonic mean of precision and recall."""
        return _ratio(2 * self.tp, 2 * self.tp + self.fp + self.fn)

    @property
    def false_positive_rate(self) -> float | None:
        """FP / (units whose reference label is not this one)."""
        return _ratio(self.fp, self.negatives)

    def to_json(self) -> dict[str, object]:
        """Return the score as a JSON object."""
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "false_positive_rate": self.false_positive_rate,
        }


def _macro(scores: Sequence[LabelScore]) -> float | None:
    values = [score.f1 for score in scores if score.f1 is not None]
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class LabelScores:
    """Per-label scores and their macro-F1.

    Macro-F1 is the unweighted mean of F1 over the labels whose F1 is
    defined; a label that neither side used is left out. `micro` pools the
    counts of all labels, for scope flags.
    """

    per_label: dict[str, LabelScore]
    micro: LabelScore | None = None

    @property
    def macro_f1(self) -> float | None:
        """The mean F1 over the labels whose F1 is defined."""
        return _macro(list(self.per_label.values()))

    def to_json(self) -> dict[str, object]:
        """Return the scores as a JSON object."""
        return {
            "per_label": {label: score.to_json() for label, score in self.per_label.items()},
            "macro_f1": self.macro_f1,
            "micro": None if self.micro is None else self.micro.to_json(),
        }


def label_scores(
    reference: Sequence[str], predicted: Sequence[str | None], labels: Sequence[str]
) -> LabelScores:
    """Score predicted labels against reference labels, unit by unit.

    For each label c, a unit is a TP when both give c, an FP when only the
    prediction does, and an FN when only the reference does. A prediction of
    None, or of a value outside `labels`, is never a TP or an FP.
    """
    if len(reference) != len(predicted):
        raise GoldSetError("reference and predicted labels differ in number")
    per_label = {}
    for label in labels:
        tp = sum(r == label and p == label for r, p in zip(reference, predicted, strict=True))
        fp = sum(r != label and p == label for r, p in zip(reference, predicted, strict=True))
        fn = sum(r == label and p != label for r, p in zip(reference, predicted, strict=True))
        negatives = sum(r != label for r in reference)
        per_label[label] = LabelScore(tp, fp, fn, negatives)
    return LabelScores(per_label)


def _flag_scores(
    reference: Sequence[frozenset[ScopeFlag]], predicted: Sequence[frozenset[ScopeFlag]]
) -> LabelScores:
    per_label = {}
    for flag in ScopeFlag:
        yes = [flag in flags for flags in reference]
        said = [flag in flags for flags in predicted]
        per_label[flag.value] = LabelScore(
            tp=sum(r and p for r, p in zip(yes, said, strict=True)),
            fp=sum(p and not r for r, p in zip(yes, said, strict=True)),
            fn=sum(r and not p for r, p in zip(yes, said, strict=True)),
            negatives=sum(not r for r in yes),
        )
    micro = LabelScore(
        tp=sum(score.tp for score in per_label.values()),
        fp=sum(score.fp for score in per_label.values()),
        fn=sum(score.fn for score in per_label.values()),
        negatives=sum(score.negatives for score in per_label.values()),
    )
    return LabelScores(per_label, micro)


@dataclass(frozen=True)
class ClaimMetrics:
    """Metrics on claims (RFC-002, section 7).

    Attributes:
        claims: The number of claims scored.
        status: Per-status scores of S6 and their macro-F1.
        false_verified_rate: Of the claims marked verified, those whose
            reference is not verified.
        critical_miss_rate: Of the claims whose reference is contradicted,
            those marked verified.
        verified_coverage: Of the claims whose reference is verified, those
            marked verified. An unverified claim counts against it.
        review_load: Of all claims, those sent to human review.
        failure_rate: Of all claims, those left unverified.
        failure_reasons: The count of each failure reason.
        wrong_status_flagged: Of the claims given a wrong status (unverified
            is not wrong), those sent to human review.
    """

    claims: int
    status: LabelScores
    false_verified_rate: Rate
    critical_miss_rate: Rate
    verified_coverage: Rate
    review_load: Rate
    failure_rate: Rate
    failure_reasons: dict[str, int] = field(default_factory=dict)
    wrong_status_flagged: Rate = Rate(0, 0)

    def to_json(self) -> dict[str, object]:
        """Return the metrics as a JSON object."""
        return {
            "claims": self.claims,
            "status": self.status.to_json(),
            "false_verified_rate": self.false_verified_rate.to_json(),
            "critical_miss_rate": self.critical_miss_rate.to_json(),
            "verified_coverage": self.verified_coverage.to_json(),
            "review_load": self.review_load.to_json(),
            "failure_rate": self.failure_rate.to_json(),
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
            "wrong_status_flagged": self.wrong_status_flagged.to_json(),
        }


@dataclass(frozen=True)
class PairMetrics:
    """Metrics on claim-source pairs: agreement label and scope flags."""

    pairs: int
    agreement_label: LabelScores
    scope_flags: LabelScores

    def to_json(self) -> dict[str, object]:
        """Return the metrics as a JSON object."""
        return {
            "pairs": self.pairs,
            "agreement_label": self.agreement_label.to_json(),
            "scope_flags": self.scope_flags.to_json(),
        }


@dataclass(frozen=True)
class Evaluation:
    """Primary metrics, without ambiguous claims, and the ambiguous ones apart."""

    claims: ClaimMetrics
    pairs: PairMetrics
    ambiguous_claims: ClaimMetrics
    ambiguous_pairs: PairMetrics

    def to_json(self) -> dict[str, object]:
        """Return the evaluation as a JSON object. It holds counts and rates only."""
        return {
            "claims": self.claims.to_json(),
            "pairs": self.pairs.to_json(),
            "ambiguous_claims": self.ambiguous_claims.to_json(),
            "ambiguous_pairs": self.ambiguous_pairs.to_json(),
        }


def _claim_metrics(claims: Sequence[GoldClaim], predictions: Predictions) -> ClaimMetrics:
    found = [_prediction(predictions.claims, claim.claim_id) for claim in claims]
    reference = [claim.status for claim in claims]
    verified, contradicted = GoldStatus.VERIFIED, GoldStatus.CONTRADICTED
    marked_verified = [
        ref for ref, p in zip(reference, found, strict=True) if p.status is ClaimStatus.VERIFIED
    ]
    wrong = [
        p
        for ref, p in zip(reference, found, strict=True)
        if p.status is not ClaimStatus.UNVERIFIED and p.status.value != ref.value
    ]
    reasons: dict[str, int] = {}
    for p in found:
        if p.failure_reason is not None:
            reasons[p.failure_reason] = reasons.get(p.failure_reason, 0) + 1
    return ClaimMetrics(
        claims=len(claims),
        status=label_scores(
            [ref.value for ref in reference],
            [p.status.value for p in found],
            [status.value for status in GoldStatus],
        ),
        false_verified_rate=Rate(
            sum(ref is not verified for ref in marked_verified), len(marked_verified)
        ),
        critical_miss_rate=Rate(
            sum(
                ref is contradicted and p.status is ClaimStatus.VERIFIED
                for ref, p in zip(reference, found, strict=True)
            ),
            sum(ref is contradicted for ref in reference),
        ),
        verified_coverage=Rate(
            sum(
                ref is verified and p.status is ClaimStatus.VERIFIED
                for ref, p in zip(reference, found, strict=True)
            ),
            sum(ref is verified for ref in reference),
        ),
        review_load=Rate(sum(p.sent_to_review for p in found), len(found)),
        failure_rate=Rate(sum(p.status is ClaimStatus.UNVERIFIED for p in found), len(found)),
        failure_reasons=reasons,
        wrong_status_flagged=Rate(sum(p.sent_to_review for p in wrong), len(wrong)),
    )


def _pair_metrics(pairs: Sequence[GoldPair], predictions: Predictions) -> PairMetrics:
    found = [_prediction(predictions.pairs, pair.pair_id) for pair in pairs]
    return PairMetrics(
        pairs=len(pairs),
        agreement_label=label_scores(
            [pair.agreement_label.value for pair in pairs],
            [None if p.agreement_label is None else p.agreement_label.value for p in found],
            [label.value for label in SourceLabel],
        ),
        scope_flags=_flag_scores(
            [frozenset(pair.scope_flags) for pair in pairs], [p.scope_flags for p in found]
        ),
    )


def _prediction[P](table: Mapping[str, P], key: str) -> P:
    if key not in table:
        raise GoldSetError(f"there is no prediction for {key}")
    return table[key]


def evaluate(items: Sequence[GoldItem], predictions: Predictions) -> Evaluation:
    """Score the system's predictions against the reference labels of `items`.

    Every claim and every pair of the items needs a prediction. Ambiguous
    claims and their pairs are scored apart from the primary metrics.

    Raises:
        GoldSetError: A claim or pair has no prediction.
    """
    claims = [claim for item in items for claim in item.claims]
    primary = [claim for claim in claims if not claim.ambiguous]
    ambiguous = [claim for claim in claims if claim.ambiguous]
    return Evaluation(
        claims=_claim_metrics(primary, predictions),
        pairs=_pair_metrics([pair for claim in primary for pair in claim.pairs], predictions),
        ambiguous_claims=_claim_metrics(ambiguous, predictions),
        ambiguous_pairs=_pair_metrics(
            [pair for claim in ambiguous for pair in claim.pairs], predictions
        ),
    )


def metrics_only(items: Sequence[GoldItem], predictions: Predictions) -> dict[str, object]:
    """Return the evaluation as numbers only, for runs on the test split.

    The result holds counts, rates and scores per label name; it never holds
    an item, claim or pair id, a text, or the label of any item, and nothing
    is printed or logged.
    """
    return evaluate(items, predictions).to_json()
