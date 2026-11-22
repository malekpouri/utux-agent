"""M2-05: the arXiv source passes the conformance suite, with recorded synthetic responses."""

from pathlib import Path

from literature_source_suite import Failure, LiteratureSourceConformance
from utux.sources.arxiv import ArxivSource
from utux.sources.http import HttpResponse, RecordedTransport

from utux.interfaces.literature_source import LiteratureSource

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "literature" / "arxiv"
BASE = "https://export.arxiv.org/api/query"
SEARCH = (
    BASE + "?search_query=all%3Asynthetic+AND+all%3Amethod+AND+all%3Acomparison"
    "&start=0&max_results={limit}"
)


def _ok(name: str) -> HttpResponse:
    return HttpResponse(200, (RECORDED / name).read_bytes())


def _no_wait(seconds: float) -> None:
    pass


class TestArxivSource(LiteratureSourceConformance):
    known = "arxiv:0000.00001"
    unknown = "arxiv:0000.99999"

    def make_source(self) -> LiteratureSource:
        routes = {
            BASE + "?id_list=0000.00001&max_results=1": _ok("entry_known.xml"),
            BASE + "?id_list=0000.99999&max_results=1": _ok("empty.xml"),
        }
        routes |= {SEARCH.format(limit=n): _ok("search_comparison.xml") for n in (1, 2, 3)}
        return ArxivSource(RecordedTransport(routes), sleep=_no_wait)

    def make_failing(self, failure: Failure) -> LiteratureSource:
        response = {
            Failure.UNAVAILABLE: HttpResponse(503, b""),
            Failure.RATE_LIMIT: HttpResponse(429, b""),
            Failure.INVALID_RESPONSE: HttpResponse(200, b"<feed"),
        }[failure]
        return ArxivSource(RecordedTransport({}, default=response), sleep=_no_wait)
