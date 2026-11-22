"""M2-05: OpenAlex and arXiv, with recorded synthetic responses; no network.

Every work, identifier, author and abstract here is synthetic.
"""

import json
from pathlib import Path

import pytest

from utux import __version__
from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
    LiteratureSourceError,
)
from utux.events.log import EventLog
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.project_config import DataPolicy
from utux.schemas.source_record import SourceVersion
from utux.sources.arxiv import ArxivSource
from utux.sources.cache import ContentCache
from utux.sources.calls import LoggedLiteratureSource
from utux.sources.http import HttpClient, HttpRequest, HttpResponse, RecordedTransport
from utux.sources.openalex import OpenAlexSource, rebuild_abstract

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


# Credentials: none unless the user set OPENALEX_API_KEY (PR #54 review, rule 8)

SECRET = "synthetic-openalex-key-0123456789"


def _every_request(environ: dict[str, str]) -> list[HttpRequest]:
    openalex = RecordedTransport({}, default=_ok("openalex/work_known.json"))
    source = OpenAlexSource(openalex, environ=environ)
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


def _assert_no_secret_in_url(request: HttpRequest) -> None:
    lowered = request.url.lower()
    for word in ("key", "token", "secret", "password", "auth", "mailto", "@"):
        assert word not in lowered, request.url


def test_without_the_variable_no_request_carries_credentials() -> None:
    for request in _every_request({}):
        assert {name.lower() for name in request.headers} <= {"user-agent", "accept"}
        _assert_no_secret_in_url(request)


def test_with_the_variable_only_openalex_gets_it_and_only_as_a_bearer_header() -> None:
    for request in _every_request({"OPENALEX_API_KEY": SECRET}):
        _assert_no_secret_in_url(request)
        assert SECRET not in request.url
        if request.url.startswith(OPENALEX):
            assert request.headers["Authorization"] == f"Bearer {SECRET}"
            assert {name.lower() for name in request.headers} == {
                "user-agent",
                "accept",
                "authorization",
            }
        else:
            assert "Authorization" not in request.headers
            assert SECRET not in json.dumps(dict(request.headers))


def test_the_key_appears_in_no_event_cache_entry_or_error(tmp_path: Path) -> None:
    environ = {"OPENALEX_API_KEY": SECRET}
    log = EventLog(tmp_path / "events.jsonl")
    cache = ContentCache(tmp_path / "cache")
    transport = RecordedTransport(
        {KNOWN_URL: _ok("openalex/work_known.json")}, default=HttpResponse(401, b"")
    )
    logged = LoggedLiteratureSource(
        log,
        OpenAlexSource(transport, environ=environ),
        cache,
        policy=DataPolicy.EXTERNAL_ALLOWED,
    )
    logged.resolve("doi:10.0000/synthetic-known")
    logged.resolve("doi:10.0000/synthetic-known")
    with pytest.raises(LiteratureSourceError) as failed:
        logged.resolve("doi:10.0000/other")
    assert SECRET not in str(failed.value)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), path
            assert SECRET not in path.name


def test_the_contact_email_is_never_sent_to_openalex_or_arxiv() -> None:
    # A service gets the contact email only if its current documentation says
    # it helps; OpenAlex's and arXiv's do not (PR #54 review).
    for request in _every_request({}):
        assert "example.org" not in request.url
        assert "mailto" not in request.url


# A natural title query (PR #54 review: the live search for this title found nothing)


def _search_query(transport: RecordedTransport) -> str:
    from urllib.parse import parse_qs, urlsplit

    (request,) = transport.requests
    params = parse_qs(urlsplit(request.url).query)
    assert params["sortBy"] == ["relevance"]
    assert params["sortOrder"] == ["descending"]
    (query,) = params["search_query"]
    return query


def test_a_natural_title_query_searches_the_phrase_and_its_content_words() -> None:
    # arXiv API user manual, section 5.1: quotes group words into a phrase,
    # OR and parentheses combine clauses, and "all" is a field prefix.
    transport = RecordedTransport({}, default=_ok("arxiv/search_attention.xml"))
    found = ArxivSource(transport, sleep=lambda s: None).search("Attention is all you need", 3)
    assert _search_query(transport) == (
        'ti:"attention is all you need" OR all:"attention is all you need"'
        " OR (all:attention AND all:need)"
    )
    assert [work.title for work in found] == ["Attention Is All You Need"]
    assert found[0].identifier == "arxiv:0000.00004"


def test_query_words_are_never_taken_as_operators_or_field_prefixes() -> None:
    transport = RecordedTransport({}, default=_ok("arxiv/empty.xml"))
    ArxivSource(transport, sleep=lambda s: None).search("Cats AND dogs OR ti: ANDNOT mice", 3)
    query = _search_query(transport)
    assert query == (
        'ti:"cats and dogs or ti andnot mice" OR all:"cats and dogs or ti andnot mice"'
        " OR (all:cats AND all:dogs AND all:mice)"
    )


def test_a_query_of_stop_words_only_searches_the_phrase() -> None:
    transport = RecordedTransport({}, default=_ok("arxiv/empty.xml"))
    ArxivSource(transport, sleep=lambda s: None).search("all of the", 3)
    assert _search_query(transport) == 'ti:"all of the" OR all:"all of the"'
