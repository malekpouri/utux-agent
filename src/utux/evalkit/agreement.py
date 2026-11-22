"""Agreement between the two annotators of the gold set (RFC-002, section 5).

The measures are raw agreement, the confusion table, Cohen's kappa and
Gwet's AC1 for categorical labels, and token-level overlap F1 and
intersection over union for evidence spans. They are computed on the raw
labels, before adjudication. Nothing here reads or returns a reference label
of an item, and the report holds no item, claim or pair id.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldItem, GoldPair, GoldStatus
from utux.schemas.claim_ledger import ScopeFlag, SourceLabel
from utux.workspace.hashing import hash_bytes

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


ListedClaim = tuple[tuple[int, int], Collection[str]]
"""A claim as one annotator listed it: its span and the source ids it cites."""


def match_claims(first: Sequence[ListedClaim], second: Sequence[ListedClaim]) -> int:
    """Return how many claims of two lists match, one to one.

    Two claims match when their spans share at least half of the longer
    span's characters and they cite the same sources, in any order (RFC-002,
    section 7, S1). Pairs are matched greedily, the largest share first.
    """
    candidates = []
    for i, ((a_start, a_end), a_cited) in enumerate(first):
        for j, ((b_start, b_end), b_cited) in enumerate(second):
            if set(a_cited) != set(b_cited):
                continue
            shared = max(0, min(a_end, b_end) - max(a_start, b_start))
            share = Fraction(shared, max(a_end - a_start, b_end - b_start))
            if share >= Fraction(1, 2):
                candidates.append((-share, i, j))
    used_first: set[int] = set()
    used_second: set[int] = set()
    for _, i, j in sorted(candidates):
        if i not in used_first and j not in used_second:
            used_first.add(i)
            used_second.add(j)
    return len(used_first)


@dataclass(frozen=True)
class ExtractionAgreement:
    """Agreement on claim extraction: how many listed claims match.

    `share` is 2 * matched / (first + second), the share of all listed
    claims that found a match.
    """

    first: int
    second: int
    matched: int

    @property
    def share(self) -> float | None:
        """2 * matched / (first + second), or None when nothing was listed."""
        total = self.first + self.second
        return None if total == 0 else float(Fraction(2 * self.matched, total))

    def to_json(self) -> dict[str, object]:
        """Return the agreement as a JSON object."""
        return {
            "first": self.first,
            "second": self.second,
            "matched": self.matched,
            "share": self.share,
        }


@dataclass(frozen=True)
class SpanAgreement:
    """Mean token-level overlap of evidence spans over the pairs.

    Pairs where neither annotator chose a token have no F1 or IoU and are
    counted in `undefined`, not in the means.
    """

    pairs: int
    undefined: int
    mean_f1: float | None
    mean_iou: float | None

    def to_json(self) -> dict[str, object]:
        """Return the agreement as a JSON object."""
        return {
            "pairs": self.pairs,
            "undefined": self.undefined,
            "mean_f1": self.mean_f1,
            "mean_iou": self.mean_iou,
        }


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

    claim_extraction: ExtractionAgreement
    status: LabelAgreement
    expert_would_review: LabelAgreement
    agreement_label: LabelAgreement
    scope_flags: dict[str, LabelAgreement]
    evidence_spans: SpanAgreement | None

    def to_json(self) -> dict[str, object]:
        """Return the report as a JSON object. It holds counts and measures only."""
        return {
            "claim_extraction": self.claim_extraction.to_json(),
            "status": self.status.to_json(),
            "expert_would_review": self.expert_would_review.to_json(),
            "agreement_label": self.agreement_label.to_json(),
            "scope_flags": {flag: value.to_json() for flag, value in self.scope_flags.items()},
            "evidence_spans": None
            if self.evidence_spans is None
            else self.evidence_spans.to_json(),
        }


_YES_NO = ("yes", "no")


def _source_text(source_texts: Mapping[str, str], pair: GoldPair) -> str:
    text = source_texts.get(pair.source_id)
    if text is None:
        raise GoldSetError(f"no source text is given for {pair.source_id}")
    if hash_bytes(text.encode("utf-8")) != pair.text_hash:
        raise GoldSetError(
            f"the source text given for {pair.source_id} does not match its text_hash; "
            "agreement is measured only on the text the annotators read"
        )
    return text


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def annotation_agreement(
    items: Sequence[GoldItem], source_texts: Mapping[str, str] | None = None
) -> AgreementReport:
    """Compute agreement between the two annotators of each item.

    The first annotator is the first of `annotation.annotators`. Claim
    extraction is compared per item by matching the two lists; status and
    `expert_would_review` per claim; the agreement label per pair; each scope
    flag per pair as a yes-or-no label. Ambiguous claims are included:
    agreement is measured on everything that was labelled.

    Evidence spans are compared only when `source_texts` maps every
    `source_id` to its stored text, and each text must match the pair's
    `text_hash`.

    Raises:
        GoldSetError: A source text is missing or does not match its hash.
    """
    listed_first = listed_second = matched = 0
    statuses: list[LabelPair] = []
    reviews: list[LabelPair] = []
    labels: list[LabelPair] = []
    flags: dict[str, list[LabelPair]] = {flag.value: [] for flag in ScopeFlag}
    overlaps: list[SpanOverlap] = []
    for item in items:
        first, second = item.annotation.annotators
        lists = item.annotation.claim_extraction.raw
        a_spans = [(claim.span, claim.citations) for claim in lists[first]]
        b_spans = [(claim.span, claim.citations) for claim in lists[second]]
        listed_first += len(a_spans)
        listed_second += len(b_spans)
        matched += match_claims(a_spans, b_spans)
        for claim in item.claims:
            statuses.append((claim.raw[first].status.value, claim.raw[second].status.value))
            reviews.append(
                (
                    _yes_no(claim.raw[first].expert_would_review),
                    _yes_no(claim.raw[second].expert_would_review),
                )
            )
            for pair in claim.pairs:
                a, b = pair.raw[first], pair.raw[second]
                labels.append((a.agreement_label.value, b.agreement_label.value))
                for flag in ScopeFlag:
                    flags[flag.value].append(
                        (_yes_no(flag in a.scope_flags), _yes_no(flag in b.scope_flags))
                    )
                if source_texts is not None:
                    overlaps.append(
                        span_overlap(
                            [span.offsets for span in a.evidence_spans],
                            [span.offsets for span in b.evidence_spans],
                            _source_text(source_texts, pair),
                        )
                    )
    return AgreementReport(
        claim_extraction=ExtractionAgreement(listed_first, listed_second, matched),
        status=label_agreement(statuses, [status.value for status in GoldStatus]),
        expert_would_review=label_agreement(reviews, _YES_NO),
        agreement_label=label_agreement(labels, [label.value for label in SourceLabel]),
        scope_flags={flag: label_agreement(values, _YES_NO) for flag, values in flags.items()},
        evidence_spans=None if source_texts is None else span_agreement(overlaps),
    )


def span_agreement(overlaps: Sequence[SpanOverlap]) -> SpanAgreement:
    """Mean F1 and IoU of span overlaps, counting the pairs where they are undefined."""
    f1 = [o.f1 for o in overlaps if o.f1 is not None]
    iou = [o.iou for o in overlaps if o.iou is not None]
    return SpanAgreement(
        pairs=len(overlaps),
        undefined=len(overlaps) - len(f1),
        mean_f1=sum(f1) / len(f1) if f1 else None,
        mean_iou=sum(iou) / len(iou) if iou else None,
    )
