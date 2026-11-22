"""M2-02: the passage splitter of ADR-0015.

Every text here is synthetic. Expected passages are written out by hand.
"""

import hashlib
import subprocess
import sys

import pytest
from utux.sources.passages import SPLITTER_VERSION, Passage, split_passages

from utux.schemas.claim_ledger import CheckedText

ABSTRACT = CheckedText.ABSTRACT
FULL = CheckedText.FULL_TEXT


def _texts(text: str, kind: CheckedText = ABSTRACT) -> list[str]:
    return [p.text for p in split_passages(text, kind)]


def _prefix(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def test_an_abstract_is_split_into_sentences_with_offsets_and_ids() -> None:
    text = "We compare A and B. A beats B on dataset X. A is slow."
    passages = split_passages(text, ABSTRACT)
    assert [(p.offsets, p.text) for p in passages] == [
        ((0, 19), "We compare A and B."),
        ((20, 43), "A beats B on dataset X."),
        ((44, 54), "A is slow."),
    ]
    assert [p.passage_id for p in passages] == [
        f"p-{_prefix(text)}-000000",
        f"p-{_prefix(text)}-000020",
        f"p-{_prefix(text)}-000044",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "  Leading space. And a second sentence!  ",
        "Line one is here.\nLine two is here?\tThird one.",
        "Short.",
        "No full stop at the end",
    ],
)
def test_the_text_of_each_passage_is_the_slice_at_its_offsets(text: str) -> None:
    passages = split_passages(text, ABSTRACT)
    assert passages
    for passage in passages:
        assert text[passage.offsets[0] : passage.offsets[1]] == passage.text
        assert passage.text == passage.text.strip()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "The method, e.g. a tree, works. It is fast.",
            ["The method, e.g. a tree, works.", "It is fast."],
        ),
        (
            "Smith et al. Reported a gain. Then it fell.",
            ["Smith et al. Reported a gain.", "Then it fell."],
        ),
        (
            "Results by Smith et al. (2020) hold. They are new.",
            ["Results by Smith et al. (2020) hold.", "They are new."],
        ),
        (
            "Accuracy rose to 0.97 on the test set. Error fell.",
            ["Accuracy rose to 0.97 on the test set.", "Error fell."],
        ),
        (
            "As shown in Fig. 3, it grows. See Eq. 2 for details.",
            ["As shown in Fig. 3, it grows.", "See Eq. 2 for details."],
        ),
        (
            "It holds [Smith et al. 2020. Vol. 2]. Next one.",
            ["It holds [Smith et al. 2020. Vol. 2].", "Next one."],
        ),
        (
            "It holds (see Jones. Lee. 2019). Next one.",
            ["It holds (see Jones. Lee. 2019).", "Next one."],
        ),
        (
            "Written by J. Smith. It was cited.",
            ["Written by J. Smith.", "It was cited."],
        ),
        (
            "It works, i.e. well. Fine.",
            ["It works, i.e. well.", "Fine."],
        ),
        (
            "Is it true? Yes! It is.",
            ["Is it true?", "Yes!", "It is."],
        ),
        (
            "It ends here [12]. The next starts.",
            ["It ends here [12].", "The next starts."],
        ),
        (
            'It ends with a quote." Then more.',
            ['It ends with a quote."', "Then more."],
        ),
    ],
)
def test_abbreviations_decimals_citations_and_et_al_do_not_end_a_sentence(
    text: str, expected: list[str]
) -> None:
    assert _texts(text) == expected


def test_full_text_is_split_into_paragraphs_then_sentences() -> None:
    text = "First paragraph. Its second sentence.\n\nSecond paragraph\nwithout a stop\n\n\nThird."
    assert _texts(text, FULL) == [
        "First paragraph.",
        "Its second sentence.",
        "Second paragraph\nwithout a stop",
        "Third.",
    ]


def test_a_passage_never_crosses_a_paragraph() -> None:
    text = "One sentence\n\nis not this one."
    assert _texts(text, FULL) == ["One sentence", "is not this one."]
    # An abstract is one block: the blank line is whitespace.
    assert _texts(text, ABSTRACT) == ["One sentence\n\nis not this one."]


def test_an_empty_or_blank_text_has_no_passages() -> None:
    assert split_passages("", ABSTRACT) == ()
    assert split_passages(" \n\t ", FULL) == ()


def test_ids_change_with_the_text_and_are_unique() -> None:
    first = split_passages("A one. B two.", ABSTRACT)
    second = split_passages("A one. B three.", ABSTRACT)
    assert first[0].passage_id != second[0].passage_id
    ids = [p.passage_id for p in split_passages("A. B. C. D. E. F.", ABSTRACT)]
    assert len(set(ids)) == len(ids)


def test_offsets_count_code_points() -> None:
    # U+1D465 MATHEMATICAL ITALIC SMALL X is outside the Basic Multilingual Plane.
    text = "Let \U0001d465 be large. Then it holds."
    first, second = split_passages(text, ABSTRACT)
    assert first.offsets == (0, 15)
    assert second.offsets == (16, 30)
    assert text[second.offsets[0] : second.offsets[1]] == "Then it holds."


def test_the_same_text_gives_the_same_ids_in_another_process() -> None:
    text = "Stable ids. On every platform, e.g. this one. Values 1.5 and 2.0 stay."
    here = [p.passage_id for p in split_passages(text, ABSTRACT)]
    script = (
        "import sys; from utux.schemas.claim_ledger import CheckedText; "
        "from utux.sources.passages import split_passages; "
        "print(' '.join(p.passage_id for p in split_passages(sys.argv[1], CheckedText.ABSTRACT)))"
    )
    done = subprocess.run(
        [sys.executable, "-c", script, text],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "12345", "LC_ALL": "C", "PATH": ""},
    )
    assert done.stdout.split() == here


def test_the_splitter_has_a_version() -> None:
    assert SPLITTER_VERSION == "passages@1"
    assert isinstance(split_passages("A.", ABSTRACT)[0], Passage)
