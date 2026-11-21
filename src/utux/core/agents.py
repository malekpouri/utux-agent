"""The prompts and outputs of the three roles of stages 3 to 5 (M1-13).

A prompt is a versioned file of the pack, `<role>@<n>.md`, whose first line
is `# Role: <role>`; the highest version is used, and its name, such as
`methodologist@1`, is logged with every model call. Each role answers in
JSON, which is validated against its schema here; the workflow asks once
more with the problems if it fails (ADR-0007, RFC-001 section 2).

- The methodologist returns numbered steps with a success criterion and the
  metrics each produces; `render_method` writes `method.md` from them, so the
  metric lines always have their exact form.
- The implementer returns the code of the step.
- The analyst returns a text that refers to every number by its result id,
  `[R0001]`, and contains no other digit and no number word (`NUMBER_WORDS`,
  and `per cent`); `render_results` puts each record's value and unit before
  its reference, and `check_results` checks the finished `results.md` again.
  The check catches digits and these words; it is not a proof that no number
  was written, for example as "a dozen" or in another language.
"""

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


def _number_in(text: str) -> str | None:
    """The first digit or number word of a text, or None."""
    found = _DIGIT.search(text) or _NUMBER_WORD.search(text)
    return None if found is None else found.group(0)


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
    outside a reference.

    Raises:
        AgentOutputError: An unknown reference, or a digit outside one.
    """
    unknown = sorted(set(_REFERENCE.findall(text)) - record_ids)
    if unknown:
        raise AgentOutputError(
            f"the analysis refers to {', '.join(unknown)}, not a record of the run"
        )
    number = _number_in(_REFERENCE.sub("", text))
    if number is not None:
        raise AgentOutputError(
            f"the analysis writes a number out ({number!r}); every number must be a "
            "reference such as [R0001]"
        )


def _value(record: ResultRecord) -> str:
    return f"{record.value!r} {record.unit} [{record.id}]"


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
    rest = text
    for record in records:
        rest = rest.replace(_value(record), "")
    number = _number_in(rest)
    if number is not None:
        raise AgentOutputError(
            f"results.md holds a number without its result record ({number!r}); every "
            "number must be a record's value followed by its id"
        )
