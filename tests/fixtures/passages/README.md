# Fixtures of the passage splitter

`passages_v1.json` holds synthetic texts and the passages `passages@1` gives
for them. `passages@1` is frozen for gold set v0 (rule 18 of `docs/plan/M2.md`):
`tests/unit/test_passages.py` fails if its output changes for these texts.
A change to the splitter is `passages@2`, with a migration of the gold set,
and a new fixture file; this one is never rewritten.
