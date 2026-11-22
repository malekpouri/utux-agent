"""M2-05: live smoke tests of OpenAlex and arXiv, run by the maintainer only.

They reach the network and need no key. They are marked `live`, so they run
only with `uv run pytest -m live`. The works are well-known published papers,
used here only to check that the services answer as the sources expect.
"""

import pytest

from utux.schemas.claim_ledger import CheckedText
from utux.sources.arxiv import ArxivSource
from utux.sources.openalex import OpenAlexSource

pytestmark = pytest.mark.live

# LeCun, Bengio and Hinton, "Deep learning", Nature 521 (2015).
DOI = "doi:10.1038/nature14539"
# Vaswani and others, "Attention Is All You Need" (2017).
ARXIV_ID = "arxiv:1706.03762"


def test_openalex_resolves_fetches_and_searches() -> None:
    source = OpenAlexSource()
    work = source.resolve(DOI)
    assert work.title is not None
    assert "deep learning" in work.title.lower()
    assert work.year == 2015
    assert work.authors
    fetched = source.fetch(DOI)
    assert fetched.metadata.identifier == DOI
    if fetched.text is not None:
        assert fetched.checked_text is CheckedText.ABSTRACT
    found = source.search("deep learning review", 3)
    assert 1 <= len(found) <= 3


def test_arxiv_resolves_fetches_and_searches() -> None:
    source = ArxivSource()
    work = source.resolve(ARXIV_ID)
    assert work.title is not None
    assert "attention" in work.title.lower()
    assert work.year == 2017
    fetched = source.fetch(ARXIV_ID)
    assert fetched.text
    assert fetched.checked_text is CheckedText.ABSTRACT
    found = source.search("attention is all you need", 3)
    assert 1 <= len(found) <= 3
