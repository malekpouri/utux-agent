"""M2-06: Crossref as a literature source, on recorded synthetic responses.

Crossref's REST API documentation (access and authentication, last updated
2025-10-16) recommends a `mailto` for its polite pool, with higher limits:
DOI lookups 5 a second without it and 10 with it, queries 1 and 3 a second.
"""

import json
from pathlib import Path

import pytest
from utux.sources.crossref import CrossrefSource

from utux.errors import LiteratureNotFoundError
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import Author, SourceVersion
from utux.sources.http import HttpResponse, RecordedTransport

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "literature" / "crossref"
BASE = "https://api.crossref.org/works"
KNOWN = "doi:10.0000/synthetic-known"


def _ok(name: str) -> HttpResponse:
    return HttpResponse(200, (RECORDED / name).read_bytes())


def _work(**changes: object) -> HttpResponse:
    document = json.loads((RECORDED / "work_known.json").read_text(encoding="utf-8"))
    document["message"].update(changes)
    for key in [k for k, v in changes.items() if v is None]:
        del document["message"][key]
    return HttpResponse(200, json.dumps(document).encode())


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _source(transport: RecordedTransport, **options: object) -> CrossrefSource:
    return CrossrefSource(transport, sleep=lambda s: None, **options)  # type: ignore[arg-type]


def test_resolve_keeps_crossref_family_names_and_organisation_names_unsplit() -> None:
    transport = RecordedTransport({BASE + "/10.0000/synthetic-known": _ok("work_known.json")})
    work = _source(transport).resolve(KNOWN)
    assert work.identifier == KNOWN
    assert work.title == "A synthetic method comparison"
    assert work.authors == (
        Author(family="Doe", given="Jane"),
        Author(display_name="Synthetic Consortium"),
    )
    assert work.year == 2024
    assert work.venue == "Synthetic Journal"
    assert work.url == "https://doi.org/10.0000/synthetic-known"


@pytest.mark.parametrize(
    ("dates", "year"),
    [
        ({"issued": None, "published-print": {"date-parts": [[2021]]}}, 2021),
        ({"issued": None, "published-online": {"date-parts": [[2020, 5]]}}, 2020),
        ({"issued": {"date-parts": [[None]]}}, None),
        ({"issued": None}, None),
    ],
)
def test_the_year_comes_from_issued_then_print_then_online(
    dates: dict[str, object], year: int | None
) -> None:
    transport = RecordedTransport({}, default=_work(**dates))
    assert _source(transport).resolve(KNOWN).year == year


def test_fetch_gives_the_jats_abstract_as_plain_text() -> None:
    transport = RecordedTransport({}, default=_ok("work_known.json"))
    fetched = _source(transport).fetch(KNOWN)
    # The abstract's own heading is left out; whitespace runs become one space.
    assert fetched.text == "We compare method A and method B. A beats B on dataset X."
    assert fetched.checked_text is CheckedText.ABSTRACT
    assert fetched.source_version is SourceVersion.INDEX_ABSTRACT
    assert fetched.extraction_method == "crossref_jats_abstract"
    assert fetched.licence == "https://creativecommons.org/licenses/by/4.0/"


@pytest.mark.parametrize(
    "abstract",
    [
        None,
        '<!DOCTYPE x [<!ENTITY e "boom">]><jats:p>&e;</jats:p>',
        "<jats:p>An unclosed paragraph",
    ],
)
def test_an_absent_unsafe_or_broken_abstract_gives_no_text(abstract: str | None) -> None:
    transport = RecordedTransport({}, default=_work(abstract=abstract))
    fetched = _source(transport).fetch(KNOWN)
    assert fetched.text is None
    assert fetched.checked_text is None
    assert fetched.extraction_method is None


def test_only_dois_are_resolved_and_others_make_no_request() -> None:
    transport = RecordedTransport({})
    with pytest.raises(LiteratureNotFoundError, match="arxiv"):
        _source(transport).resolve("arxiv:0000.00001")
    assert transport.requests == []


def test_the_contact_email_is_sent_as_mailto_only_when_set() -> None:
    plain = RecordedTransport({}, default=_ok("work_known.json"))
    _source(plain).resolve(KNOWN)
    assert plain.requests[0].url == BASE + "/10.0000/synthetic-known"
    polite = RecordedTransport({}, default=_ok("work_known.json"))
    _source(polite, contact_email="synthetic@example.org").resolve(KNOWN)
    assert polite.requests[0].url == (
        BASE + "/10.0000/synthetic-known?mailto=synthetic%40example.org"
    )


def test_no_request_carries_a_key_or_an_authorization_header() -> None:
    transport = RecordedTransport({}, default=_ok("work_known.json"))
    source = _source(transport, contact_email="synthetic@example.org")
    source.resolve(KNOWN)
    source.fetch(KNOWN)
    transport.default = _ok("search_comparison.json")
    source.search("synthetic method comparison", 3)
    for request in transport.requests:
        assert {name.lower() for name in request.headers} == {"user-agent", "accept"}
        for word in ("key", "token", "secret", "password", "auth"):
            assert word not in request.url.lower()


@pytest.mark.parametrize(
    ("email", "lookup", "query"),
    [(None, 0.2, 1.0), ("synthetic@example.org", 0.1, 1 / 3)],
)
def test_requests_keep_crossrefs_rate_limits(
    email: str | None, lookup: float, query: float
) -> None:
    clock = _Clock()
    transport = RecordedTransport({}, default=_ok("work_known.json"))
    source = CrossrefSource(
        transport, contact_email=email, sleep=clock.sleep, monotonic=clock.monotonic
    )
    source.resolve(KNOWN)
    source.resolve(KNOWN)
    transport.default = _ok("search_comparison.json")
    source.search("synthetic method comparison", 3)
    source.search("synthetic method comparison", 3)
    assert clock.sleeps == pytest.approx([lookup, query, query])
