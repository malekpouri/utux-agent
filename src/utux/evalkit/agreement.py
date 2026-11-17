"""Agreement between the two annotators of the gold set (RFC-002, section 5).

The measures are raw agreement, the confusion table, Cohen's kappa and
Gwet's AC1 for categorical labels, and token-level overlap F1 and
intersection over union for evidence spans. They are computed on the raw
labels, before adjudication. Nothing here reads or returns a reference label
of an item, and the report holds no item, claim or pair id.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldItem, GoldStatus
from utux.schemas.claim_ledger import ScopeFlag, SourceLabel

LabelPair = tuple[str, str]
"""The labels the first and the second annotator gave to one unit."""

_TOKEN = re.compile(r"\w+|[^\w\s]")


def _checked(pairs: Sequence[LabelPair], labels: Sequence[str] | None = None) -> None:
    if not pairs:
        raise GoldSetError("agreement needs at least one pair of labels")
    if labels is not None:
        known = set(labels)
        for first, second in pairs:
            for label in (first, second):
                if label not in known:
                    raise GoldSetError(f"the label {label} is not one of {', '.join(labels)}")


def _observed(pairs: Sequence[LabelPair]) -> Fraction:
    return Fraction(sum(first == second for first, second in pairs), len(pairs))


def raw_agreement(pairs: Sequence[LabelPair]) -> float:
    """Return the share of units on which both annotators gave the same label."""
    _checked(pairs)
    return float(_observed(pairs))


def confusion_table(pairs: Sequence[LabelPair], labels: Sequence[str]) -> dict[str, dict[str, int]]:
    """Return the counts of each label pair: rows are the first annotator's labels."""
    _checked(pairs, labels)
    table = {row: dict.fromkeys(labels, 0) for row in labels}
    for first, second in pairs:
        table[first][second] += 1
    return table


def _shares(pairs: Sequence[LabelPair], labels: Sequence[str]) -> list[tuple[Fraction, Fraction]]:
    n = len(pairs)
    return [
        (
            Fraction(sum(first == label for first, _ in pairs), n),
            Fraction(sum(second == label for _, second in pairs), n),
        )
        for label in labels
    ]


def cohens_kappa(pairs: Sequence[LabelPair], labels: Sequence[str]) -> float | None:
    """Return Cohen's kappa, or None when chance agreement is 1.

    kappa = (p_o - p_e) / (1 - p_e), with p_e the sum over labels of the
    product of the two annotators' shares of that label.
    """
    _checked(pairs, labels)
    expected = sum((a * b for a, b in _shares(pairs, labels)), Fraction(0))
    if expected == 1:
        return None
    return float((_observed(pairs) - expected) / (1 - expected))


def gwet_ac1(pairs: Sequence[LabelPair], labels: Sequence[str]) -> float | None:
    """Return Gwet's AC1, or None when there are fewer than two labels.

    AC1 = (p_o - p_e) / (1 - p_e), with pi_k the mean of the two annotators'
    shares of label k and p_e = sum of pi_k (1 - pi_k) over the Q labels,
    divided by Q - 1.
    """
    _checked(pairs, labels)
    if len(labels) < 2:
        return None
    pis = [(a + b) / 2 for a, b in _shares(pairs, labels)]
    expected = sum((pi * (1 - pi) for pi in pis), Fraction(0)) / (len(labels) - 1)
    return float((_observed(pairs) - expected) / (1 - expected))


@dataclass(frozen=True)
class SpanOverlap:
    """Token-level overlap between two annotators' evidence spans.

    Both are None when neither annotator selected a token.
    """

    f1: float | None
    iou: float | None


def _tokens(spans: Sequence[tuple[int, int]], text: str) -> set[int]:
    tokens = [match.span() for match in _TOKEN.finditer(text)]
    return {
        index
        for index, (token_start, token_end) in enumerate(tokens)
        for start, end in spans
        if start < token_end and end > token_start
    }


def span_overlap(
    first: Sequence[tuple[int, int]], second: Sequence[tuple[int, int]], text: str
) -> SpanOverlap:
    """Compare two sets of character spans over `text`, token by token.

    A token is a run of word characters or a single other non-space
    character. A span covers every token it touches. F1 = 2|A and B| /
    (|A| + |B|) and IoU = |A and B| / |A or B| over the covered tokens.
    """
    a, b = _tokens(first, text), _tokens(second, text)
    if not a and not b:
        return SpanOverlap(None, None)
    shared = len(a & b)
    return SpanOverlap(
        float(Fraction(2 * shared, len(a) + len(b))), float(Fraction(shared, len(a | b)))
    )


@dataclass(frozen=True)
class LabelAgreement:
    """Agreement on one kind of label."""

    units: int
    raw_agreement: float
    cohens_kappa: float | None
    gwet_ac1: float | None
    confusion: dict[str, dict[str, int]]

    def to_json(self) -> dict[str, object]:
        """Return the agreement as a JSON object."""
        return {
            "units": self.units,
            "raw_agreement": self.raw_agreement,
            "cohens_kappa": self.cohens_kappa,
            "gwet_ac1": self.gwet_ac1,
            "confusion": self.confusion,
        }


def label_agreement(pairs: Sequence[LabelPair], labels: Sequence[str]) -> LabelAgreement:
    """Return every categorical agreement measure for one kind of label."""
    return LabelAgreement(
        units=len(pairs),
        raw_agreement=raw_agreement(pairs),
        cohens_kappa=cohens_kappa(pairs, labels),
        gwet_ac1=gwet_ac1(pairs, labels),
        confusion=confusion_table(pairs, labels),
    )


@dataclass(frozen=True)
class AgreementReport:
    """Agreement of a release: status per claim, label and each flag per pair."""

    status: LabelAgreement
    agreement_label: LabelAgreement
    scope_flags: dict[str, LabelAgreement]

    def to_json(self) -> dict[str, object]:
        """Return the report as a JSON object. It holds counts and measures only."""
        return {
            "status": self.status.to_json(),
            "agreement_label": self.agreement_label.to_json(),
            "scope_flags": {flag: value.to_json() for flag, value in self.scope_flags.items()},
        }


_YES_NO = ("yes", "no")


def annotation_agreement(items: Sequence[GoldItem]) -> AgreementReport:
    """Compute agreement between the two annotators of each item.

    The first annotator is the first of `annotation.annotators`. Status is
    compared per claim, the agreement label per pair, and each scope flag per
    pair as a yes-or-no label. Ambiguous claims are included: agreement is
    measured on everything that was labelled.
    """
    statuses: list[LabelPair] = []
    labels: list[LabelPair] = []
    flags: dict[str, list[LabelPair]] = {flag.value: [] for flag in ScopeFlag}
    for item in items:
        first, second = item.annotation.annotators
        for claim in item.claims:
            statuses.append((claim.raw[first].status.value, claim.raw[second].status.value))
            for pair in claim.pairs:
                a, b = pair.raw[first], pair.raw[second]
                labels.append((a.agreement_label.value, b.agreement_label.value))
                for flag in ScopeFlag:
                    flags[flag.value].append(
                        (
                            "yes" if flag in a.scope_flags else "no",
                            "yes" if flag in b.scope_flags else "no",
                        )
                    )
    return AgreementReport(
        status=label_agreement(statuses, [status.value for status in GoldStatus]),
        agreement_label=label_agreement(labels, [label.value for label in SourceLabel]),
        scope_flags={flag: label_agreement(values, _YES_NO) for flag, values in flags.items()},
    )
