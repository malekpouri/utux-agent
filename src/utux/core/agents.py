"""The prompts and outputs of the three roles of stages 3 to 5 (M1-13).

A prompt is a versioned file of the pack, `<role>@<n>.md`, whose first line
is `# Role: <role>`; the highest version is used, and its name, such as
`methodologist@1`, is logged with every model call. Each role answers in
JSON, which is validated against its schema here; the workflow asks once
more with the problems if it fails (ADR-0007, RFC-001 section 2). An answer
that is exactly one fenced code block is read from inside the fence
(`unwrap_code_fence`).

- The methodologist returns numbered steps with a success criterion and the
  metrics each produces; `render_method` writes `method.md` from them, so the
  metric lines always have their exact form.
- The implementer returns the code of the step.
- The analyst returns a text that refers to every number by its result id,
  `[R0001]`, and contains no other digit and no number word (`NUMBER_WORDS`,
  and `per cent`), apart from zero to ten that state no amount, as in "the
  two models"; `render_results` puts each record's value, rounded to the
  decimals its tolerance implies, and its unit, unless the unit is
  dimensionless such as `score`, before its reference, and `check_results`
  checks the finished `results.md` again.
  The check catches digits and these words; it is not a proof that no number
  was written, for example as "a dozen" or in another language.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from utux.errors import AgentOutputError, PromptError
from utux.schemas.result_record import ResultRecord

PROMPTS_DIRECTORY = "packs/generic/prompts"
"""The prompts of the generic pack, relative to the repository."""

_PROMPT_FILE = re.compile(r"^(?P<role>[a-z]+)@(?P<version>[1-9][0-9]*)\.md$")
_REFERENCE = re.compile(r"\[(R[0-9]{3,})\]")
_DIGIT = re.compile(r"[0-9]")

NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
    "percent",
    "half",
    "twice",
    "double",
    "triple",
)
"""Common English number words, refused outside references as digits are."""

_NUMBER_WORD = re.compile(
    r"\b(?:" + "|".join(NUMBER_WORDS) + r"|per\s+cent)\b", flags=re.IGNORECASE
)


_FENCED = re.compile(r"\A```(?:json)?[ \t]*\n(.*?)\n?```\Z", flags=re.DOTALL)


def unwrap_code_fence(text: str) -> str:
    """The content of an answer that is exactly one fenced code block.

    Models often wrap their JSON in a Markdown fence. If the whole answer,
    after trimming whitespace, is one block fenced with ```json or ```, its
    content is returned. Anything else is returned unchanged, so that it is
    judged as it is: text before or after the block, more than one block, or
    a block of another language stays invalid JSON.
    """
    found = _FENCED.match(text.strip())
    if found is None or "```" in found.group(1):
        return text
    return found.group(1)


SMALL_NUMBER_WORDS = frozenset(NUMBER_WORDS[:11])
"""zero to ten: allowed as words, as in "the two models", unless they state an amount."""

# What makes a small number word an amount: a unit or a multiple after it.
_AMOUNT_AFTER = re.compile(
    r"-fold\b|\s+(?:per\s+cent|percent|percentage|times|fold|points?)\b", flags=re.IGNORECASE
)
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n")


def _number_at(masked: str) -> tuple[int, str] | None:
    """The first digit or refused number word of a text, and where it is.

    `masked` has its references, or the values that stand with their
    records, replaced by `#` of the same length, so positions match the text.
    """
    found: list[tuple[int, str]] = []
    digit = _DIGIT.search(masked)
    if digit is not None:
        found.append((digit.start(), digit.group(0)))
    for word in _NUMBER_WORD.finditer(masked):
        small = word.group(0).lower() in SMALL_NUMBER_WORDS
        if small and _AMOUNT_AFTER.match(masked, word.end()) is None:
            continue
        found.append((word.start(), word.group(0)))
        break
    return min(found) if found else None


def _sentence(text: str, position: int) -> str:
    """The sentence of a text that holds a position."""
    ends = [found.end() for found in _SENTENCE_END.finditer(text, 0, position)]
    start = ends[-1] if ends else 0
    end = _SENTENCE_END.search(text, position)
    stop = len(text) if end is None else (end.start() if end.group(0) == "\n" else end.end())
    return text[start:stop].strip()


def _refusal(text: str, masked: str) -> str | None:
    """How a text writes a number out, naming the word and its sentence; None if it does not."""
    number = _number_at(masked)
    if number is None:
        return None
    position, word = number
    return f'{word!r} in "{_sentence(text, position)}"'


def _masked(text: str, parts: list[str]) -> str:
    for part in parts:
        text = text.replace(part, "#" * len(part))
    return text


@dataclass(frozen=True)
class Prompt:
    """One version of a role's prompt.

    Attributes:
        version: The logged prompt version, `<role>@<n>`.
        text: The prompt as written.
    """

    version: str
    text: str

    def fill(self, **values: str) -> str:
        """The prompt with its `$name` placeholders filled.

        Raises:
            PromptError: A placeholder has no value.
        """
        try:
            return Template(self.text).substitute(values)
        except KeyError as error:
            raise PromptError(f"the prompt {self.version} needs a value for {error}") from error


def load_prompt(directory: Path, role: str) -> Prompt:
    """The highest version of a role's prompt in a directory.

    Raises:
        PromptError: There is no prompt for the role, or its first line is
            not `# Role: <role>`.
    """
    versions = [
        (int(found.group("version")), path)
        for path in directory.glob(f"{role}@*.md")
        if (found := _PROMPT_FILE.match(path.name)) is not None and found.group("role") == role
    ]
    if not versions:
        raise PromptError(f"there is no prompt for the {role} in {directory}")
    version, path = max(versions)
    text = path.read_text(encoding="utf-8")
    if not text.startswith(f"# Role: {role}\n"):
        raise PromptError(f"{path.name} must start with the line '# Role: {role}'")
    return Prompt(version=f"{role}@{version}", text=text)


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Text = Annotated[str, Field(min_length=1, strict=True)]
MetricName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", strict=True)]


class Step(_Output):
    """One step of a method."""

    title: Text
    description: Text
    success_criterion: Text
    metrics: Annotated[tuple[MetricName, ...], Field(min_length=1)]


class MethodPlan(_Output):
    """The methodologist's answer: at least one step."""

    steps: Annotated[tuple[Step, ...], Field(min_length=1)]


class CodeOutput(_Output):
    """The implementer's answer: the code of the step."""

    code: Text


class AnalysisOutput(_Output):
    """The analyst's answer: the results text, with numbers by result id."""

    text: Text


def render_method(plan: MethodPlan) -> str:
    """Write `method.md` from a plan: numbered steps, each with its metric lines."""
    parts = ["# Method\n"]
    for number, step in enumerate(plan.steps, start=1):
        metrics = "".join(f"- metric: {metric}\n" for metric in step.metrics)
        parts.append(
            f"\n## Step {number}: {step.title}\n\n{step.description}\n\n"
            f"Success criterion: {step.success_criterion}\n\n{metrics}"
        )
    return "".join(parts)


def check_analysis_text(text: str, record_ids: set[str]) -> None:
    """Refuse an analysis that has a number without a result id.

    Every reference must be a record of the run, and no digit may appear
    outside a reference, nor a number word. Zero to ten are allowed as
    words, as in "the two models", unless the next word is percent, per
    cent, percentage, times, fold, point or points, or the word is joined to
    fold with a hyphen (five-fold).

    Raises:
        AgentOutputError: An unknown reference, or a digit outside one.
    """
    unknown = sorted(set(_REFERENCE.findall(text)) - record_ids)
    if unknown:
        raise AgentOutputError(
            f"the analysis refers to {', '.join(unknown)}, not a record of the run"
        )
    refusal = _refusal(text, _REFERENCE.sub(lambda found: "#" * len(found.group(0)), text))
    if refusal is not None:
        raise AgentOutputError(
            f"the analysis writes a number out: {refusal}. Every number must be a reference "
            "such as [R0001]; words for zero to ten are allowed, but not before percent, "
            "times, fold or points"
        )


DIMENSIONLESS_UNITS = frozenset({"score", "ratio", "fraction", "dimensionless", "1"})
"""Units that are not shown after a value in `results.md`."""


def decimals_for_tolerance(tolerance: float) -> int | None:
    """The decimals a tolerance implies: 0.0001 gives four, 0.005 two.

    Rounding to them errs by at most the tolerance. None for a tolerance of
    zero, which asks for the exact value.
    """
    if tolerance <= 0:
        return None
    return max(0, math.ceil(-math.log10(2 * tolerance) - 1e-9))


def shown_value(record: ResultRecord) -> str:
    """A record's value as `results.md` shows it: to the decimals of its tolerance.

    The record itself keeps the full value (finding 9 of M1-16).
    """
    decimals = decimals_for_tolerance(record.tolerance)
    return repr(record.value) if decimals is None else f"{record.value:.{decimals}f}"


def _value(record: ResultRecord) -> str:
    unit = "" if record.unit in DIMENSIONLESS_UNITS else f" {record.unit}"
    return f"{shown_value(record)}{unit} [{record.id}]"


def render_results(output: AnalysisOutput, records: list[ResultRecord]) -> str:
    """Write `results.md`: each reference preceded by its record's value and unit."""
    by_id = {record.id: record for record in records}
    body = _REFERENCE.sub(lambda found: _value(by_id[found.group(1)]), output.text)
    return f"# Results\n\n{body.strip()}\n"


def check_results(text: str, records: list[ResultRecord]) -> None:
    """Refuse a `results.md` that holds a number without its result record.

    Every number must stand as `<value> <unit> [<id>]` with the value and
    unit of that record; once those are taken out, no digit may remain
    apart from the heading.

    Raises:
        AgentOutputError: A number without its record.
    """
    refusal = _refusal(text, _masked(text, [_value(record) for record in records]))
    if refusal is not None:
        raise AgentOutputError(
            f"results.md holds a number without its result record: {refusal}. Every "
            "number must be a record's value followed by its id"
        )
