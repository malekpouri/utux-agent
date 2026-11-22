# Public item fixtures

Synthetic items of `public_item` (task M0-15b), made by `utux.evalkit.public`
from the synthetic SciFact and SciClaimEval files of
`tests/unit/test_public_import.py`. No real dataset item is used.

- `valid/`: a SciFact-shaped item with a supporting and a neutral pair, and a
  SciClaimEval-shaped refuted item whose claim needs its context.
- `invalid/`: a status that does not follow from the labels, and a pair label
  (`partial`) the import never gives.
