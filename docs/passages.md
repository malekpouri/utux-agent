# Passages

`utux.sources.passages.split_passages(text, kind)` splits a source's stored
text into passages, by the rules of
[ADR-0015](adr/0015-shared-passage-splitter.md) (task M2-02). The gold
tooling and the verifier both use it, so the passage ids of the reference
labels are the ids the verifier retrieves.

| Kind | Passages |
| --- | --- |
| `abstract` | Sentences of the whole text |
| `full_text` | Paragraphs at blank lines, then sentences; a passage never crosses a paragraph |

Each passage has:

- `passage_id`: `p-`, the first eight hexadecimal digits of the SHA-256 hash
  of the text, `-`, and the start offset with at least six digits, for
  example `p-3ee9b44b-005321`;
- `offsets`: start and end **in Unicode code points** of the stored text;
- `text`: exactly the slice at the offsets, without the whitespace around it.

The stored text is never changed. The same text always gives the same
passages and ids, on every platform: the rules use no locale, no hash seed
and no model. A changed text gives new ids.

## Where a sentence ends

At `.`, `!` or `?`, with any closing quotes or brackets after it, when
whitespace follows and then a capital letter, a digit, an opening bracket or
quote, or the end of the text. Not:

- **inside round or square brackets**, so a citation such as
  "(Smith et al., 2020)" or "[Smith et al. 2020. Vol. 2]" stays whole;
- **after an abbreviation** of the fixed list `ABBREVIATIONS`, among them
  "e.g.", "i.e.", "Fig.", "Eq.", "Vol.", "vs." and "al." of "et al.";
- **inside a decimal number** such as 0.97, which no whitespace follows.

The rules are simple on purpose and make mistakes on hard text, for
example a sentence that ends with an abbreviation, or an author's initial
("J. Smith") read as a sentence end. The mistakes are deterministic and
shared by the reference and the system.

## Versions

The rules have a version, `SPLITTER_VERSION` (`passages@1`). Changing a rule
changes passage ids, so it is a new version. Every annotation batch records
the version its passages came from (`splitter`), and a frozen gold release
names it in its changelog; a release is never split again.

## Offsets in the browser

Offsets count code points everywhere, as Python's strings do. The offline
annotation page runs in a browser, which counts UTF-16 code units; the two
differ for a character outside the Basic Multilingual Plane, such as some
mathematical letters. The page converts on read and on write, so the spans
and evidence it exports are in code points.
