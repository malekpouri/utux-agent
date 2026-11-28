"""M2-06: the citation existence check of ADR-0016, on synthetic references and works.

Every reference and work here is synthetic. Expected similarities are worked
out by hand in the comments.
"""

import json
from pathlib import Path

import pytest

from utux.errors import (
    ContractValidationError,
    LiteratureNotFoundError,
    LiteratureUnavailableError,
)
from utux.events.log import EventLog
from utux.interfaces.literature_source import WorkMetadata
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.source_record import Author
from utux.verification.existence import (
    TITLE_SIMILARITY,
    YEAR_TOLERANCE,
    BibliographyCheck,
    ExistenceReason,
    Reference,
    check_bibliography,
    check_reference,
    claims_to_unverify,
    first_author_matches,
    normalise,
    record_bibliography_check,
    resolve_reference,
    title_similarity,
)

DOI = "doi:10.0000/synthetic-known"


def _work(**changes: object) -> WorkMetadata:
    fields: dict[str, object] = {
        "identifier": DOI,
        "title": "A synthetic method comparison",
        "authors": (Author(family="Doe", given="Jane"),),
        "year": 2024,
    }
    fields.update(changes)
    return WorkMetadata(**fields)  # type: ignore[arg-type]


def _reference(**changes: object) -> Reference:
    fields: dict[str, object] = {
        "key": "doe2024",
        "identifier": DOI,
        "title": "A Synthetic Method Comparison.",
        "first_author_family": "Doe",
        "year": 2024,
    }
    fields.update(changes)
    return Reference(**fields)  # type: ignore[arg-type]


# The rules ---------------------------------------------------------------------


def test_the_constants_are_those_of_adr_0016() -> None:
    assert TITLE_SIMILARITY == 0.9
    assert YEAR_TOLERANCE == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Deep  Learning: A Review!", "deep learning a review"),
        # NFKC turns the ligature into two letters; case folding turns ß into ss.
        ("ﬁne Straße", "fine strasse"),
        ("  (Self-)Attention—revisited ", "selfattentionrevisited"),
        # Diacritics are folded in titles too (maintainer, after PR #57).
        ("Méthode à noyaux pour l\u2019étude", "methode a noyaux pour letude"),
    ],
)
def test_normalisation_is_nfkc_case_folding_without_punctuation(text: str, expected: str) -> None:
    assert normalise(text) == expected


def test_title_similarity_is_one_minus_edit_distance_over_the_longer_length() -> None:
    # kitten -> sitting: 3 edits, the longer has 7 characters: 1 - 3/7.
    assert title_similarity("kitten", "sitting") == pytest.approx(4 / 7)
    assert title_similarity("A title.", "a TITLE") == 1.0
    # 10 characters, 1 substitution: exactly 0.9.
    assert title_similarity("abcdefghij", "abcdefghix") == pytest.approx(0.9)
    assert title_similarity("", "") == 0.0


@pytest.mark.parametrize(
    ("family", "author", "matches"),
    [
        ("Doe", Author(family="Doe", given="Jane"), True),
        ("doe", Author(family="DOE"), True),
        ("Doe", Author(family="Roe"), False),
        # A display name is searched for the family name as whole words.
        ("Doe", Author(display_name="Jane Doe"), True),
        ("van der Berg", Author(display_name="Anna van der Berg"), True),
        # The whole-word rule holds after the amendment of ADR-0016.
        ("Berg", Author(display_name="Anna Bergman"), False),
        ("Bergman", Author(display_name="Anna Berg"), False),
        # Diacritics are folded, and ü, ö, ä also match ue, oe, ae (maintainer, PR #57).
        ("Müller", Author(display_name="Hans Muller"), True),
        ("Müller", Author(display_name="Hans Mueller"), True),
        ("Mueller", Author(display_name="Hans Müller"), True),
        ("Schröder", Author(family="Schroeder"), True),
        ("Bär", Author(family="Baer"), True),
        ("Müller", Author(display_name="Hans Miller"), False),
        # Hyphens are word boundaries.
        ("García", Author(display_name="José García-López"), True),
        ("García", Author(family="García-López"), True),
        ("Garcia-Lopez", Author(family="García López"), True),
        ("López", Author(family="Lopez"), True),
        # The family field, where given, decides, even if the display name differs.
        ("Doe", Author(family="Doe", display_name="Someone Else"), True),
        ("Else", Author(family="Doe", display_name="Someone Else"), False),
    ],
)
def test_the_first_author_family_name(family: str, author: Author, matches: bool) -> None:
    assert first_author_matches(family, author) is matches


def test_a_reference_that_matches_exists() -> None:
    result = check_reference(_reference(), _work())
    assert result.exists is True
    assert result.reasons == ()


def test_a_year_one_apart_is_allowed_and_two_apart_is_not() -> None:
    assert check_reference(_reference(year=2023), _work()).exists is True
    result = check_reference(_reference(year=2022), _work())
    assert result.reasons == (ExistenceReason.YEAR_MISMATCH,)


def test_every_failed_rule_is_a_reason_in_a_fixed_order() -> None:
    work = _work(title="An unrelated synthetic title", authors=(Author(family="Roe"),), year=2010)
    result = check_reference(_reference(), work)
    assert result.exists is False
    assert result.reasons == (
        ExistenceReason.TITLE_MISMATCH,
        ExistenceReason.AUTHOR_MISMATCH,
        ExistenceReason.YEAR_MISMATCH,
    )


def test_a_field_missing_on_either_side_fails_its_rule() -> None:
    work = _work(title=None, authors=(), year=None)
    assert check_reference(_reference(), work).reasons == (
        ExistenceReason.TITLE_MISMATCH,
        ExistenceReason.AUTHOR_MISMATCH,
        ExistenceReason.YEAR_MISMATCH,
    )
    reference = _reference(title=None, first_author_family=None, year=None)
    assert len(check_reference(reference, _work()).reasons) == 3


# Resolution ---------------------------------------------------------------------


class _Source:
    """A synthetic source: works by identifier, and errors by identifier."""

    def __init__(
        self,
        name: str,
        works: dict[str, WorkMetadata] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.name = name
        self.works = works or {}
        self.errors = errors or {}
        self.calls: list[str] = []

    def resolve(self, identifier: str) -> WorkMetadata:
        self.calls.append(identifier)
        if identifier in self.errors:
            raise self.errors[identifier]
        if identifier not in self.works:
            raise LiteratureNotFoundError(f"synthetic: no {identifier}")
        return self.works[identifier]


def _sources(**overrides: _Source) -> dict[str, _Source]:
    sources = {
        "crossref": _Source("crossref", {DOI: _work()}),
        "arxiv": _Source("arxiv"),
        "openalex": _Source("openalex"),
    }
    sources.update(overrides)
    return sources


def test_a_doi_resolves_through_crossref() -> None:
    result = resolve_reference(_reference(), _sources())  # type: ignore[arg-type]
    assert (result.exists, result.resolved_by) == (True, "crossref")


def test_openalex_is_the_fallback_when_the_first_service_does_not_have_it() -> None:
    crossref = _Source("crossref")
    openalex = _Source("openalex", {DOI: _work()})
    sources = _sources(crossref=crossref, openalex=openalex)
    result = resolve_reference(_reference(), sources)  # type: ignore[arg-type]
    assert (result.exists, result.resolved_by) == (True, "openalex")
    assert crossref.calls == [DOI]


def test_an_arxiv_id_resolves_through_arxiv_and_a_pmid_through_openalex() -> None:
    sources = _sources(
        arxiv=_Source("arxiv", {"arxiv:0000.00001": _work(identifier="arxiv:0000.00001")}),
        openalex=_Source("openalex", {"pmid:00000001": _work(identifier="pmid:00000001")}),
    )
    arxiv = resolve_reference(_reference(identifier="arxiv:0000.00001"), sources)  # type: ignore[arg-type]
    pmid = resolve_reference(_reference(identifier="pmid:00000001"), sources)  # type: ignore[arg-type]
    assert (arxiv.resolved_by, pmid.resolved_by) == ("arxiv", "openalex")


@pytest.mark.parametrize("identifier", [None, "isbn:0000000000", "doi:10.0000/nowhere"])
def test_a_reference_found_nowhere_is_not_found(identifier: str | None) -> None:
    result = resolve_reference(_reference(identifier=identifier), _sources())  # type: ignore[arg-type]
    assert result.exists is False
    assert result.reasons == (ExistenceReason.NOT_FOUND,)
    assert result.incomplete is False


def test_a_reference_that_no_service_could_answer_is_not_judged() -> None:
    # An outage is not evidence that a reference is invented: the check is
    # incomplete, the reference is kept, and its claims stay unverified.
    down = LiteratureUnavailableError("synthetic outage")
    sources = _sources(
        crossref=_Source("crossref", errors={DOI: down}),
        openalex=_Source("openalex", errors={DOI: down}),
    )
    result = resolve_reference(_reference(), sources)  # type: ignore[arg-type]
    assert result.exists is None
    assert result.reasons == ()
    assert result.incomplete is True
    # A distinct reason, never one of the four rules (maintainer, PR #57).
    assert result.incomplete_reason == "existence_check_incomplete"


def test_one_service_down_and_the_other_without_the_work_is_still_incomplete() -> None:
    down = LiteratureUnavailableError("synthetic outage")
    sources = _sources(crossref=_Source("crossref", errors={DOI: down}))
    result = resolve_reference(_reference(), sources)  # type: ignore[arg-type]
    assert (result.exists, result.incomplete) == (None, True)


# The bibliography and its claims ---------------------------------------------------


def test_unresolved_references_are_removed_and_their_claims_become_unverified() -> None:
    real = _reference(key="real")
    invented = _reference(key="invented", identifier="doi:10.0000/nowhere")
    wrong_year = _reference(key="wrong_year", year=1990)
    down = _reference(key="down", identifier="doi:10.0000/down")
    outage = {"doi:10.0000/down": LiteratureUnavailableError("synthetic outage")}
    sources = _sources(
        crossref=_Source("crossref", {DOI: _work()}, outage),
        openalex=_Source("openalex", errors=outage),
    )
    check = check_bibliography([real, invented, wrong_year, down], sources)  # type: ignore[arg-type]
    assert [r.key for r in check.kept] == ["real", "down"]
    assert check.removed == {
        "invented": (ExistenceReason.NOT_FOUND,),
        "wrong_year": (ExistenceReason.YEAR_MISMATCH,),
    }
    assert check.incomplete == ("down",)
    citations = {"c1": ["real"], "c2": ["real", "invented"], "c3": ["down"], "c4": []}
    assert claims_to_unverify(check, citations) == ("c2", "c3")


def test_reference_keys_are_unique() -> None:
    with pytest.raises(ValueError, match="doe2024"):
        check_bibliography([_reference(), _reference()], _sources())  # type: ignore[arg-type]


# The report and the event log (maintainer, PR #57) -----------------------------------


def _checked() -> BibliographyCheck:
    outage = {"doi:10.0000/down": LiteratureUnavailableError("synthetic outage")}
    sources = _sources(
        crossref=_Source("crossref", {DOI: _work()}, outage),
        openalex=_Source("openalex", errors=outage),
    )
    references = [
        _reference(key="real"),
        _reference(key="invented", identifier="doi:10.0000/nowhere"),
        _reference(key="wrong", year=1990, title="Something else entirely"),
        _reference(key="down", identifier="doi:10.0000/down"),
    ]
    return check_bibliography(references, sources)  # type: ignore[arg-type]


def test_the_report_gives_an_incomplete_check_its_own_reason() -> None:
    check = _checked()
    assert check.incomplete == ("down",)
    report = check.report()
    assert report["incomplete"] == {"down": "existence_check_incomplete"}
    assert report["removed"] == {
        "invented": ["not_found"],
        "wrong": ["title_mismatch", "year_mismatch"],
    }
    assert report["kept"] == ["real", "down"]


def test_each_reference_check_is_a_verification_result_event(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    record_bibliography_check(log, _checked())
    events = [(e.status, e.status_reason, dict(e.data)) for e in log]
    check = "citation_existence"
    assert events == [
        (
            EventStatus.OK,
            None,
            {
                "check": check,
                "reference": "real",
                "outcome": "exists",
                "reasons": None,
                "resolved_by": "crossref",
            },
        ),
        (
            EventStatus.OK,
            None,
            {
                "check": check,
                "reference": "invented",
                "outcome": "removed",
                "reasons": "not_found",
                "resolved_by": None,
            },
        ),
        (
            EventStatus.OK,
            None,
            {
                "check": check,
                "reference": "wrong",
                "outcome": "removed",
                "reasons": "title_mismatch year_mismatch",
                "resolved_by": "crossref",
            },
        ),
        (
            EventStatus.ERROR,
            "existence_check_incomplete",
            {
                "check": check,
                "reference": "down",
                "outcome": "incomplete",
                "reasons": None,
                "resolved_by": None,
            },
        ),
    ]
    assert all(e.type is EventType.VERIFICATION_RESULT for e in log)


@pytest.mark.parametrize(
    ("status", "reason", "data", "code"),
    [
        # A removed reference names its failed rules; nothing else does.
        ("ok", None, {"outcome": "removed", "reasons": None}, "reasons_required"),
        ("ok", None, {"outcome": "exists", "reasons": "not_found"}, "reasons_not_allowed"),
        ("ok", None, {"outcome": "removed", "reasons": "made_up"}, "unknown_reason"),
        # An incomplete check is an error with its own reason, never ok.
        ("ok", None, {"outcome": "incomplete"}, "outcome_status_mismatch"),
        ("error", "not_found", {"outcome": "incomplete"}, "outcome_status_mismatch"),
        ("error", "existence_check_incomplete", {"outcome": "exists"}, "outcome_status_mismatch"),
        ("ok", None, {"outcome": "maybe"}, "unknown_outcome"),
    ],
)
def test_an_inconsistent_verification_result_is_refused(
    tmp_path: Path, status: str, reason: str | None, data: dict[str, object], code: str
) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    record_bibliography_check(log, _checked())
    document = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    Event.validate_document(document, "synthetic")
    document.update(status=status, status_reason=reason)
    document["data"].update(data)
    with pytest.raises(ContractValidationError) as caught:
        Event.validate_document(document, "synthetic")
    assert code in {problem.code for problem in caught.value.problems}


def test_titles_fold_diacritics_but_not_german_transliterations() -> None:
    assert title_similarity("Müller-type models", "Muller-type models") == 1.0
    # ue for ü is accepted for author names only.
    assert title_similarity("Müller", "Mueller") < 1.0
