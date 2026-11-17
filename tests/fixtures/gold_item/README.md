# Synthetic fixtures for gold items

Every file here is synthetic, and every file name starts with `synthetic_`.
They were generated for the tests of `utux.evalkit.gold` and are not
annotation of any kind. None of them is, or comes from, a gold-standard item:

- the texts are invented sentences about "synthetic method A" and
  "synthetic method B";
- the sources (`synthetic:...`), source groups (`sg-synthetic-...`) and text
  hashes do not refer to any real paper; every hash is the SHA-256 of the
  text `synthetic fixture content` followed by a newline;
- the item ids are in the range `G9000` to `G9009`, the annotator ids `a90`,
  `a91` and `a92` belong to no person, and `synthetic-system-config-1` is no
  real system;
- the labels were chosen to exercise the schema, not by reading a source.
  They must never be used as reference labels.

- `valid/` holds items that must validate.
- `invalid/` holds items that must be rejected. Each one is wrong in exactly
  one way, and the file name states it. The expected field and code for each
  file are written out in `tests/unit/test_gold_item.py`.
