"""M2-06: the Crossref source passes the conformance suite, with recorded synthetic responses."""

from pathlib import Path

from literature_source_suite import Failure, LiteratureSourceConformance
from utux.sources.crossref import CrossrefSource

from utux.interfaces.literature_source import LiteratureSource
from utux.sources.http import HttpResponse, RecordedTransport

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "literature" / "crossref"
BASE = "https://api.crossref.org/works"
QUERY_URL = BASE + "?query=synthetic+method+comparison&rows={limit}"


def _ok(name: str) -> HttpResponse:
    return HttpResponse(200, (RECORDED / name).read_bytes())


def _no_wait(seconds: float) -> None:
    pass


class TestCrossrefSource(LiteratureSourceConformance):
    def make_source(self) -> LiteratureSource:
        routes = {BASE + "/10.0000/synthetic-known": _ok("work_known.json")}
        routes |= {QUERY_URL.format(limit=n): _ok("search_comparison.json") for n in (1, 2, 3)}
        return CrossrefSource(RecordedTransport(routes), sleep=_no_wait)

    def make_failing(self, failure: Failure) -> LiteratureSource:
        response = {
            Failure.UNAVAILABLE: HttpResponse(503, b""),
            Failure.RATE_LIMIT: HttpResponse(429, b""),
            Failure.INVALID_RESPONSE: HttpResponse(200, b"{not json"),
        }[failure]
        return CrossrefSource(RecordedTransport({}, default=response), sleep=_no_wait)
