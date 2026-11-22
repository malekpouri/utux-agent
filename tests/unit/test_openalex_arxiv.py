"""M2-05: OpenAlex and arXiv, with recorded synthetic responses; no network.

Every work, identifier, author and abstract here is synthetic.
"""

import json
from pathlib import Path

import pytest
from utux.sources.arxiv import ArxivSource
from utux.sources.http import HttpClient, HttpRequest, HttpResponse, RecordedTransport
from utux.sources.openalex import OpenAlexSource, rebuild_abstract

from utux import __version__
from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
)
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import SourceVersion

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "literature"
OPENALEX = "https://api.openalex.org/works"
ARXIV = "https://export.arxiv.org/api/query"
KNOWN_URL = OPENALEX + "/https://doi.org/10.0000/synthetic-known"


def _ok(path: str) -> HttpResponse:
    return HttpResponse(200, (FIXTURES / path).read_bytes())


class _Clock:
    """A clock that moves only when the code sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# OpenAlex abstracts, rebuilt from the inverted index


def test_an_abstract_is_rebuilt_from_its_inverted_index_exactly() -> None:
    index = {"A": [4], "We": [0], "compare": [1], "B": [3, 6], "and": [2], "beats": [5], ".": [7]}
    assert rebuild_abstract(index) == "We compare and B A beats B ."


def test_an_empty_or_missing_index_has_no_abstract() -> None:
    assert rebuild_abstract(None) is None
    assert rebuild_abstract({}) is None


@pytest.mark.parametrize(
    "index",
    [
        {"a": [0], "b": [0]},
        {"a": [0], "b": [2]},
        {"a": [-1]},
        {"a": ["0"]},
    ],
    ids=["two words at one position", "a gap", "a negative position", "not a number"],
)
def test_an_index_that_does_not_make_one_text_is_invalid(index: dict[str, object]) -> None:
    with pytest.raises(LiteratureInvalidResponseError):
        rebuild_abstract(index)


def test_openalex_fetch_gives_the_abstract_and_the_metadata() -> None:
    source = OpenAlexSource(RecordedTransport({KNOWN_URL: _ok("openalex/work_known.json")}))
    fetched = source.fetch("doi:10.0000/synthetic-known")
    assert fetched.text == "We compare method A and method B . A beats B on dataset X ."
    assert fetched.checked_text is CheckedText.ABSTRACT
    assert fetched.source_version is SourceVersion.INDEX_ABSTRACT
    assert fetched.extraction_method == "openalex_inverted_index"
    assert fetched.licence == "cc-by"
    work = fetched.metadata
    assert (work.title, work.year, work.venue) == (
        "A synthetic method comparison",
        2024,
        "Synthetic Journal",
    )
    # OpenAlex gives one display name; its last word is taken as the family name.
    assert [(a.family, a.given) for a in work.authors] == [("Doe", "Jane"), ("Roe", None)]


def test_openalex_search_names_works_by_doi_or_openalex_id() -> None:
    url = OPENALEX + "?search=synthetic+method+comparison&per-page=3"
    source = OpenAlexSource(RecordedTransport({url: _ok("openalex/search_comparison.json")}))
    found = source.search("synthetic method comparison", 3)
    assert [w.identifier for w in found] == [
        "doi:10.0000/synthetic-known",
        "doi:10.0000/synthetic-2",
        "openalex:W0000000003",
    ]


def test_openalex_resolves_pmid_and_openalex_ids_and_refuses_other_schemes() -> None:
    transport = RecordedTransport({}, default=HttpResponse(404, b""))
    source = OpenAlexSource(transport)
    for identifier in ("pmid:00000000", "openalex:W0000000001"):
        with pytest.raises(LiteratureNotFoundError):
            source.resolve(identifier)
    assert [r.url for r in transport.requests] == [
        OPENALEX + "/pmid:00000000",
        OPENALEX + "/W0000000001",
    ]
    with pytest.raises(LiteratureNotFoundError, match="arxiv"):
        source.resolve("arxiv:0000.00001")
    assert len(transport.requests) == 2


# arXiv


def test_arxiv_fetch_gives_the_abstract_and_the_metadata() -> None:
    url = ARXIV + "?id_list=0000.00001&max_results=1"
    source = ArxivSource(
        RecordedTransport({url: _ok("arxiv/entry_known.xml")}), sleep=lambda s: None
    )
    fetched = source.fetch("arxiv:0000.00001")
    assert fetched.text == "We compare method A and method B. A beats B on dataset X."
    assert fetched.checked_text is CheckedText.ABSTRACT
    assert fetched.source_version is SourceVersion.PREPRINT
    assert fetched.extraction_method == "arxiv_api_atom"
    work = fetched.metadata
    assert (work.title, work.year, work.venue) == (
        "A synthetic method comparison",
        2023,
        "Synthetic Journal 1 (2024)",
    )
    assert work.url == "https://arxiv.org/abs/0000.00001v2"
    assert [(a.family, a.given) for a in work.authors] == [("Doe", "Jane"), ("Roe", None)]


def test_arxiv_refuses_a_feed_with_a_document_type_or_entities() -> None:
    url = ARXIV + "?id_list=0000.00001&max_results=1"
    source = ArxivSource(
        RecordedTransport({url: _ok("arxiv/with_entity.xml")}), sleep=lambda s: None
    )
    with pytest.raises(LiteratureInvalidResponseError, match="DOCTYPE"):
        source.resolve("arxiv:0000.00001")


def test_arxiv_resolves_only_arxiv_ids() -> None:
    source = ArxivSource(RecordedTransport({}), sleep=lambda s: None)
    with pytest.raises(LiteratureNotFoundError, match="doi"):
        source.resolve("doi:10.0000/synthetic-known")


def test_arxiv_requests_are_three_seconds_apart() -> None:
    clock = _Clock()
    url = ARXIV + "?id_list=0000.00001&max_results=1"
    transport = RecordedTransport({url: _ok("arxiv/entry_known.xml")})
    source = ArxivSource(transport, sleep=clock.sleep, monotonic=clock.monotonic)
    for _ in range(3):
        source.resolve("arxiv:0000.00001")
    assert clock.sleeps == [3.0, 3.0]


# Rate limits, retries and the user agent


def test_a_rate_limit_is_retried_after_its_retry_after_and_then_succeeds() -> None:
    clock = _Clock()
    transport = RecordedTransport(
        {KNOWN_URL: [HttpResponse(429, b"", {"Retry-After": "7"}), _ok("openalex/work_known.json")]}
    )
    source = OpenAlexSource(transport, sleep=clock.sleep, monotonic=clock.monotonic)
    assert source.resolve("doi:10.0000/synthetic-known").year == 2024
    assert len(transport.requests) == 2
    assert 7.0 in clock.sleeps


def test_retries_are_bounded_and_waits_are_capped() -> None:
    clock = _Clock()
    transport = RecordedTransport({}, default=HttpResponse(429, b"", {"Retry-After": "86400"}))
    source = OpenAlexSource(transport, sleep=clock.sleep, monotonic=clock.monotonic)
    with pytest.raises(LiteratureRateLimitError):
        source.resolve("doi:10.0000/synthetic-known")
    assert len(transport.requests) == HttpClient.MAX_ATTEMPTS
    assert max(clock.sleeps) <= HttpClient.MAX_WAIT_SECONDS


def test_the_user_agent_names_utux_and_its_version() -> None:
    transport = RecordedTransport({KNOWN_URL: _ok("openalex/work_known.json")})
    OpenAlexSource(transport).resolve("doi:10.0000/synthetic-known")
    (request,) = transport.requests
    assert request.headers["User-Agent"].startswith(f"utux/{__version__}")


def test_a_body_larger_than_the_limit_is_invalid() -> None:
    big = HttpResponse(200, b" " * (HttpClient.MAX_BYTES + 1))
    source = OpenAlexSource(RecordedTransport({KNOWN_URL: big}))
    with pytest.raises(LiteratureInvalidResponseError, match="large"):
        source.resolve("doi:10.0000/synthetic-known")


# No credentials, and the contact email only when set (M2-05, rule 8)


def _every_request(contact_email: str | None) -> list[HttpRequest]:
    openalex = RecordedTransport({}, default=_ok("openalex/work_known.json"))
    source = OpenAlexSource(openalex, contact_email=contact_email)
    source.resolve("doi:10.0000/synthetic-known")
    source.fetch("doi:10.0000/synthetic-known")
    openalex.default = _ok("openalex/search_comparison.json")
    source.search("synthetic method comparison", 3)
    arxiv = RecordedTransport({}, default=_ok("arxiv/search_comparison.xml"))
    other = ArxivSource(arxiv, sleep=lambda s: None)
    other.search("synthetic method comparison", 3)
    arxiv.default = _ok("arxiv/entry_known.xml")
    other.resolve("arxiv:0000.00001")
    other.fetch("arxiv:0000.00001")
    return [*openalex.requests, *arxiv.requests]


def test_no_literature_request_carries_credentials() -> None:
    for request in _every_request(contact_email=None):
        assert {name.lower() for name in request.headers} <= {"user-agent", "accept"}
        lowered = request.url.lower()
        for word in ("key", "token", "secret", "password", "auth", "mailto", "@"):
            assert word not in lowered, request.url


def test_the_contact_email_is_sent_only_when_set_and_only_to_openalex() -> None:
    email = "synthetic@example.org"
    requests = _every_request(contact_email=email)
    openalex = [r for r in requests if r.url.startswith(OPENALEX)]
    arxiv = [r for r in requests if r.url.startswith(ARXIV)]
    assert all("mailto=synthetic%40example.org" in r.url for r in openalex)
    assert not any(
        "example.org" in r.url or "example.org" in json.dumps(dict(r.headers)) for r in arxiv
    )
