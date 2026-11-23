"""M2-05: the OpenAlex source passes the conformance suite, with recorded synthetic responses."""

from pathlib import Path

from literature_source_suite import KNOWN, Failure, LiteratureSourceConformance

from utux.interfaces.literature_source import LiteratureSource
from utux.sources.http import HttpResponse, RecordedTransport
from utux.sources.openalex import OpenAlexSource

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "literature" / "openalex"
BASE = "https://api.openalex.org/works"
QUERY_URL = BASE + "?search=synthetic+method+comparison&per-page={limit}"


def _ok(name: str) -> HttpResponse:
    return HttpResponse(200, (RECORDED / name).read_bytes())


def _no_wait(seconds: float) -> None:
    pass


class TestOpenAlexSource(LiteratureSourceConformance):
    def make_source(self) -> LiteratureSource:
        routes = {BASE + "/https://doi.org/10.0000/synthetic-known": _ok("work_known.json")}
        routes |= {QUERY_URL.format(limit=n): _ok("search_comparison.json") for n in (1, 2, 3)}
        return OpenAlexSource(RecordedTransport(routes), sleep=_no_wait)

    def make_failing(self, failure: Failure) -> LiteratureSource:
        response = {
            Failure.UNAVAILABLE: HttpResponse(503, b""),
            Failure.RATE_LIMIT: HttpResponse(429, b"", {"Retry-After": "1"}),
            Failure.INVALID_RESPONSE: HttpResponse(200, b"{not json"),
        }[failure]
        return OpenAlexSource(RecordedTransport({}, default=response), sleep=_no_wait)


assert KNOWN == "doi:10.0000/synthetic-known"
