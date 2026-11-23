"""The citation existence check (task M2-06, ADR-0016, specification section 8).

A reference exists when all of these hold:

1. it resolves by its identifier: a DOI through Crossref, an arXiv id
   through arXiv, a PMID through PubMed once M2-07 exists, with OpenAlex as
   the fallback for every scheme;
2. its title matches: after `normalise`, one minus the Levenshtein distance
   divided by the length of the longer title is at least `TITLE_SIMILARITY`;
3. the first author's family name matches: it appears as whole words in the
   service's family name where one is given, and otherwise in its display
   name, which is never split. Names are compared in the forms of
   `name_forms`: diacritics folded, ü, ö, ä also as ue, oe, ae, and hyphens
   as word boundaries (ADR-0016, amended in PR #57). Titles keep `normalise`;
4. the years differ by at most `YEAR_TOLERANCE`.

Each failed rule is a reason: `not_found`, `title_mismatch`,
`author_mismatch`, `year_mismatch`. A field missing on either side fails its
rule. Only these deterministic rules decide; no model takes part.

**An outage is not a verdict.** When no service could answer, because each
was unavailable, rate limited or gave an invalid answer, and none said the
work does not exist, the check is incomplete: the reference is kept, and its
claims stay `unverified`, the operational state of RFC-002 section 3. A
reference is removed only when a rule failed.
"""

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from utux.errors import LiteratureNotFoundError, LiteratureSourceError
from utux.events.log import EventLog
from utux.interfaces.literature_source import WorkMetadata
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.schemas.source_record import Author
from utux.sources.calls import SYSTEM_ACTOR

TITLE_SIMILARITY = 0.9
"""The least title similarity of a match (ADR-0016)."""
YEAR_TOLERANCE = 1
"""The most years a match may differ by: a preprint and its published version (ADR-0016)."""

ROUTES: Mapping[str, tuple[str, ...]] = {
    "doi": ("crossref", "openalex"),
    "arxiv": ("arxiv", "openalex"),
    # PubMed comes before OpenAlex once M2-07 adds it.
    "pmid": ("openalex",),
}
"""The services that resolve each identifier scheme, in order."""


class ExistenceReason(StrEnum):
    """Why a reference does not exist as cited (ADR-0016)."""

    NOT_FOUND = "not_found"
    TITLE_MISMATCH = "title_mismatch"
    AUTHOR_MISMATCH = "author_mismatch"
    YEAR_MISMATCH = "year_mismatch"


INCOMPLETE_REASON = "existence_check_incomplete"
"""Why a check is incomplete; never one of the `ExistenceReason` codes of a failed rule."""

CHECK_NAME = "citation_existence"
"""The `check` of its `verification_result` events."""


class Resolver(Protocol):
    """What the check needs of a literature source: `resolve`."""

    def resolve(self, identifier: str) -> WorkMetadata:
        """The work's metadata."""
        ...


@dataclass(frozen=True)
class Reference:
    """One bibliography entry, as cited.

    `first_author_family` is the family name of the first author in the
    bibliography, for example BibTeX's. Any field may be missing; a missing
    field fails its rule.
    """

    key: str
    identifier: str | None
    title: str | None
    first_author_family: str | None
    year: int | None


@dataclass(frozen=True)
class ExistenceResult:
    """The verdict on one reference.

    `exists` is None, with `incomplete` true and `incomplete_reason`
    `existence_check_incomplete`, when no service could answer.
    `resolved_by` names the service whose record was compared.
    """

    key: str
    exists: bool | None
    reasons: tuple[ExistenceReason, ...]
    resolved_by: str | None
    incomplete: bool = False

    @property
    def incomplete_reason(self) -> str | None:
        """`existence_check_incomplete` for an incomplete check, else None."""
        return INCOMPLETE_REASON if self.incomplete else None

    @property
    def outcome(self) -> str:
        """`exists`, `removed` or `incomplete`."""
        if self.incomplete:
            return "incomplete"
        return "exists" if self.exists else "removed"


def normalise(text: str) -> str:
    """Unicode NFKC, case folding, punctuation removed, runs of whitespace made one space."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept = "".join(char for char in folded if not unicodedata.category(char).startswith("P"))
    return " ".join(kept.split())


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def title_similarity(first: str, second: str) -> float:
    """One minus the Levenshtein distance over the longer length, after `normalise`.

    Two empty titles have similarity 0: nothing to match.
    """
    a, b = normalise(first), normalise(second)
    longest = max(len(a), len(b))
    if longest == 0:
        return 0.0
    return 1 - _levenshtein(a, b) / longest


_TRANSLITERATIONS = str.maketrans(
    {"ü": "ue", "ö": "oe", "ä": "ae", "Ü": "Ue", "Ö": "Oe", "Ä": "Ae"}
)


def name_forms(name: str) -> set[tuple[str, ...]]:
    """The words of a name in each accepted form (ADR-0016, amended in PR #57).

    Hyphens are word boundaries. Diacritics are folded (Unicode NFKD, the
    combining marks dropped), and ü, ö, ä are also written ue, oe, ae, so
    "Müller" has the forms "muller" and "mueller". Then case folding, and
    punctuation removed as by `normalise`.
    """

    def words(text: str) -> tuple[str, ...]:
        spaced = "".join(
            " " if unicodedata.category(char) == "Pd" else char
            for char in unicodedata.normalize("NFKC", text)
        )
        decomposed = unicodedata.normalize("NFKD", spaced)
        folded = "".join(char for char in decomposed if not unicodedata.combining(char))
        return tuple(normalise(folded).split())

    composed = unicodedata.normalize("NFC", name)
    forms = {words(composed), words(composed.translate(_TRANSLITERATIONS))}
    return {form for form in forms if form}


def _contains(words: tuple[str, ...], part: tuple[str, ...]) -> bool:
    return any(words[i : i + len(part)] == part for i in range(len(words) - len(part) + 1))


def first_author_matches(family: str, author: Author) -> bool:
    """Whether the cited family name matches the service's first author.

    The cited family name must appear as whole words in the service's
    family name where it is given, and otherwise in its display name. Both
    sides are compared in every form of `name_forms`: "Müller" matches
    "Muller" and "Mueller", and "García" matches "García-López", but "Berg"
    does not match "Bergman".
    """
    cited = name_forms(family)
    service = author.family if author.family is not None else author.display_name
    if not cited or service is None:
        return False
    return any(_contains(words, part) for words in name_forms(service) for part in cited)


def check_reference(reference: Reference, work: WorkMetadata) -> ExistenceResult:
    """Apply rules 2 to 4 to a reference and the work its identifier resolved to."""
    reasons: list[ExistenceReason] = []
    if (
        reference.title is None
        or work.title is None
        or title_similarity(reference.title, work.title) < TITLE_SIMILARITY
    ):
        reasons.append(ExistenceReason.TITLE_MISMATCH)
    if (
        reference.first_author_family is None
        or not work.authors
        or not first_author_matches(reference.first_author_family, work.authors[0])
    ):
        reasons.append(ExistenceReason.AUTHOR_MISMATCH)
    if (
        reference.year is None
        or work.year is None
        or abs(reference.year - work.year) > YEAR_TOLERANCE
    ):
        reasons.append(ExistenceReason.YEAR_MISMATCH)
    return ExistenceResult(reference.key, not reasons, tuple(reasons), None)


def resolve_reference(reference: Reference, sources: Mapping[str, Resolver]) -> ExistenceResult:
    """Resolve a reference through its services in order, and apply the rules.

    The first service that gives a record is compared. A service that says
    the work does not exist, or that is not configured, passes the reference
    on to the next. A failure of every service that did not say "not found"
    makes the check incomplete.
    """
    scheme = reference.identifier.partition(":")[0] if reference.identifier else ""
    failed = False
    for name in ROUTES.get(scheme, ()):
        source = sources.get(name)
        if source is None or reference.identifier is None:
            continue
        try:
            work = source.resolve(reference.identifier)
        except LiteratureNotFoundError:
            continue
        except LiteratureSourceError:
            failed = True
            continue
        result = check_reference(reference, work)
        return ExistenceResult(result.key, result.exists, result.reasons, name)
    if failed:
        return ExistenceResult(reference.key, None, (), None, incomplete=True)
    return ExistenceResult(reference.key, False, (ExistenceReason.NOT_FOUND,), None)


@dataclass(frozen=True)
class BibliographyCheck:
    """The bibliography after the check.

    `kept` holds the references that exist or could not be checked, in their
    order; `removed` the others with their reasons; `incomplete` the keys of
    references that could not be checked.
    """

    results: tuple[ExistenceResult, ...]
    kept: tuple[Reference, ...]
    removed: Mapping[str, tuple[ExistenceReason, ...]]
    incomplete: tuple[str, ...]

    def report(self) -> dict[str, object]:
        """The check as a JSON object: kept keys, removed keys with their rules, incomplete keys.

        An incomplete check gives its own reason, `existence_check_incomplete`,
        never a rule's.
        """
        return {
            "kept": [reference.key for reference in self.kept],
            "removed": {key: [r.value for r in reasons] for key, reasons in self.removed.items()},
            "incomplete": dict.fromkeys(self.incomplete, INCOMPLETE_REASON),
        }


def check_bibliography(
    references: Sequence[Reference], sources: Mapping[str, Resolver]
) -> BibliographyCheck:
    """Check every reference; unresolved ones are removed from the bibliography.

    Raises:
        ValueError: Two references share a key.
    """
    seen: set[str] = set()
    for reference in references:
        if reference.key in seen:
            raise ValueError(f"the reference key {reference.key} appears more than once")
        seen.add(reference.key)
    results = tuple(resolve_reference(reference, sources) for reference in references)
    kept = tuple(
        ref for ref, result in zip(references, results, strict=True) if result.exists is not False
    )
    return BibliographyCheck(
        results=results,
        kept=kept,
        removed={r.key: r.reasons for r in results if r.exists is False},
        incomplete=tuple(r.key for r in results if r.incomplete),
    )


def claims_to_unverify(
    check: BibliographyCheck, citations: Mapping[str, Iterable[str]]
) -> tuple[str, ...]:
    """The claims that cite a removed or unchecked reference: they become `unverified`.

    `citations` maps each claim id to the reference keys it cites. The ids
    are returned sorted.
    """
    affected = set(check.removed) | set(check.incomplete)
    return tuple(sorted(claim for claim, keys in citations.items() if affected.intersection(keys)))


def record_bibliography_check(
    log: EventLog, check: BibliographyCheck, *, run_id: str | None = None
) -> None:
    """Write one `verification_result` event per reference, in bibliography order.

    A completed check is `ok`, with the outcome `exists` or `removed` and,
    for a removed reference, its failed rules as space-separated codes. An
    incomplete check is `error` with `status_reason`
    `existence_check_incomplete`, so it is never read as a failed rule.
    """
    for result in check.results:
        log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.VERIFICATION_RESULT,
                status=EventStatus.ERROR if result.incomplete else EventStatus.OK,
                status_reason=result.incomplete_reason,
                run_id=run_id,
                data={
                    "check": CHECK_NAME,
                    "reference": result.key,
                    "outcome": result.outcome,
                    "reasons": " ".join(r.value for r in result.reasons) or None,
                    "resolved_by": result.resolved_by,
                },
            )
        )
