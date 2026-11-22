"""M2-04: the scripted literature source passes the conformance suite."""

from literature_source_suite import KNOWN, Failure, LiteratureSourceConformance

from utux.errors import LiteratureRateLimitError, LiteratureUnavailableError
from utux.interfaces.literature_source import LiteratureSource
from utux.sources.scripted import ScriptedLiteratureSource, ScriptedWork, synthetic_work

CATALOG = [
    synthetic_work(KNOWN, "A synthetic method comparison", text="We compare A and B."),
    synthetic_work("doi:10.0000/synthetic-2", "Synthetic method comparison, again"),
    synthetic_work("arxiv:0000.00001", "A synthetic method comparison preprint"),
    synthetic_work("pmid:00000001", "Unrelated synthetic biology"),
]


class TestScriptedLiteratureSource(LiteratureSourceConformance):
    def make_source(self) -> LiteratureSource:
        return ScriptedLiteratureSource(CATALOG)

    def make_failing(self, failure: Failure) -> LiteratureSource:
        steps = {
            Failure.UNAVAILABLE: ScriptedWork.failing(LiteratureUnavailableError("synthetic")),
            Failure.RATE_LIMIT: ScriptedWork.failing(LiteratureRateLimitError("synthetic")),
            # An upstream answer without its identifier is not valid.
            Failure.INVALID_RESPONSE: ScriptedWork.raw({"title": "synthetic"}),
        }
        return ScriptedLiteratureSource(CATALOG, every_call=steps[failure])
