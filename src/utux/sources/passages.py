"""The passage splitter of ADR-0015, shared by the gold tooling and the verifier.

`split_passages(text, kind)` splits a source's stored text into passages:
sentences for an abstract; paragraphs at blank lines, then sentences, for
full text. A passage never crosses a paragraph. The text is never changed:
a passage's text is exactly the slice at its offsets, with the whitespace
around it left out. Offsets count Unicode code points, as Python's strings
do.

A sentence ends at `.`, `!` or `?`, with any closing quotes or brackets after
it, when whitespace follows and then a capital letter, a digit, an opening
bracket or quote, or the end of the text. It does not end:

- inside round or square brackets, so that a citation such as
  "(Smith et al., 2020)" or "[Smith et al. 2020. Vol. 2]" stays whole;
- after an abbreviation of `ABBREVIATIONS`, such as "e.g.", "Fig." or
  "et al.";
- inside a decimal number, which no whitespace follows.

An id is `p-`, the first eight hexadecimal digits of the text's SHA-256
hash, `-` and the start offset with at least six digits, for example
`p-3ee9b44b-005321`. The same text always gives the same ids, on every
platform: the rules use no locale, no hash seed and no language model. A
change of the rules is a new `SPLITTER_VERSION`, and a frozen gold release
names the version its passages came from.
"""

import re
from dataclasses import dataclass

from utux.schemas.claim_ledger import CheckedText
from utux.workspace.hashing import hash_bytes

SPLITTER_VERSION = "passages@1"
"""The version of the rules below. Changing a rule changes passage ids."""

ABBREVIATIONS = frozenset(
    {
        "al.",
        "approx.",
        "cf.",
        "ch.",
        "dr.",
        "e.g.",
        "eq.",
        "eqs.",
        "esp.",
        "fig.",
        "figs.",
        "i.e.",
        "mr.",
        "mrs.",
        "ms.",
        "no.",
        "nos.",
        "p.",
        "pp.",
        "prof.",
        "ref.",
        "refs.",
        "resp.",
        "sec.",
        "sect.",
        "st.",
        "tab.",
        "vol.",
        "vs.",
        "viz.",
    }
)
"""Words whose full stop does not end a sentence, in lower case."""

_PARAGRAPH_BREAK = re.compile(r"\n[ \t\r\f\v]*\n\s*")
_TERMINAL = frozenset(".!?")
_CLOSERS = frozenset("\"')]" + chr(0x201D) + chr(0x2019))
_OPENERS = frozenset("\"'([" + chr(0x201C) + chr(0x2018))
# The word before a full stop: letters, digits and inner full stops, as in "e.g".
_WORD_BEFORE = re.compile(r"([^\s(\[\"'\u201c\u2018]+)\Z")


@dataclass(frozen=True)
class Passage:
    """A passage of a stored text.

    Attributes:
        passage_id: Its stable id.
        offsets: Its start and end, in code points of the stored text.
        text: The text at those offsets.
    """

    passage_id: str
    offsets: tuple[int, int]
    text: str


def _paragraphs(text: str, kind: CheckedText) -> list[tuple[int, int]]:
    if kind is CheckedText.ABSTRACT:
        return [(0, len(text))]
    bounds: list[tuple[int, int]] = []
    start = 0
    for found in _PARAGRAPH_BREAK.finditer(text):
        bounds.append((start, found.start()))
        start = found.end()
    bounds.append((start, len(text)))
    return bounds


def _abbreviation_before(text: str, stop: int, start: int) -> bool:
    """Whether the full stop at `stop` belongs to an abbreviation of the list."""
    found = _WORD_BEFORE.search(text, start, stop)
    if found is None:
        return False
    return (found.group(1) + ".").lower() in ABBREVIATIONS


def _starts_sentence(char: str) -> bool:
    return char.isupper() or char.isdigit() or char in _OPENERS


def _sentence_ends(text: str, start: int, end: int) -> list[int]:
    """The ends of the sentences in text[start:end], just after their last character."""
    ends: list[int] = []
    depth = 0
    index = start
    while index < end:
        char = text[index]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char in _TERMINAL and depth == 0:
            close = index + 1
            while close < end and text[close] in _TERMINAL:
                close += 1
            while close < end and text[close] in _CLOSERS:
                close += 1
            following = close
            while following < end and text[following].isspace():
                following += 1
            spaced = following > close
            at_end = following >= end
            ends_here = (spaced and (at_end or _starts_sentence(text[following]))) or close >= end
            if char == "." and _abbreviation_before(text, index, start):
                ends_here = close >= end and at_end
            if ends_here:
                ends.append(close)
                index = close
                continue
        index += 1
    return ends


def _passage_id(prefix: str, start: int) -> str:
    return f"p-{prefix}-{start:06d}"


def split_passages(text: str, kind: CheckedText) -> tuple[Passage, ...]:
    """Split a stored text into passages, by the rules of ADR-0015.

    Args:
        text: The stored text of a source, as it is.
        kind: `abstract` (sentences) or `full_text` (paragraphs, then
            sentences).

    Returns:
        The passages in the order of the text; none for a blank text.
    """
    prefix = hash_bytes(text.encode("utf-8")).removeprefix("sha256:")[:8]
    passages: list[Passage] = []
    for paragraph_start, paragraph_end in _paragraphs(text, kind):
        cut = paragraph_start
        for stop in [*_sentence_ends(text, paragraph_start, paragraph_end), paragraph_end]:
            piece = text[cut:stop]
            stripped = piece.strip()
            if stripped:
                begin = cut + (len(piece) - len(piece.lstrip()))
                finish = begin + len(stripped)
                passages.append(Passage(_passage_id(prefix, begin), (begin, finish), stripped))
            cut = stop
    return tuple(passages)
