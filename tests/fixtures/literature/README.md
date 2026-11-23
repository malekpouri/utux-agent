# Recorded synthetic responses of literature sources (M2-05)

Every file here is synthetic: written by hand in the shape of an OpenAlex
JSON answer or an arXiv Atom feed, with invented works, identifiers,
authors and abstracts. None was recorded from a real service; the tests
never reach the network (rule 6 of `docs/plan/M2.md`).

`arxiv/search_attention.xml` answers a natural title query (PR #54 review). Its title is the
real paper's title, so that the query has stop words and the word "all"; its id, date, author
and abstract are synthetic.
