"""M1-13: the prompts, structured outputs and text checks of the three roles.

The expected texts are written out by hand. No model is called.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from utux.core.agents import (
    PROMPTS_DIRECTORY,
    AnalysisOutput,
    CodeOutput,
    MethodPlan,
    check_analysis_text,
    check_results,
    load_prompt,
    render_method,
    render_results,
    unwrap_code_fence,
)
from utux.errors import AgentOutputError, PromptError
from utux.schemas.result_record import ResultRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / PROMPTS_DIRECTORY


def _record(
    record_id: str,
    value: float,
    metric: str = "r2",
    *,
    unit: str = "score",
    tolerance: float = 0.005,
) -> ResultRecord:
    return ResultRecord(
        schema_version=1,
        id=record_id,
        metric=metric,
        value=value,
        unit=unit,
        dataset="synthetic_line",
        model="linear",
        split="test",
        run_id="r001",
        source="runs/r001/outputs/metrics.json",
        tolerance=tolerance,
    )


# Prompts


@pytest.mark.parametrize(
    ("role", "version"),
    [("methodologist", 3), ("implementer", 3), ("analyst", 5)],
)
def test_each_role_has_a_versioned_prompt_in_the_pack(role: str, version: int) -> None:
    prompt = load_prompt(PROMPTS, role)
    assert prompt.version == f"{role}@{version}"
    assert prompt.text.splitlines()[0] == f"# Role: {role}"


def test_the_highest_version_of_a_prompt_is_used(tmp_path: Path) -> None:
    for version in (1, 2, 10):
        (tmp_path / f"analyst@{version}.md").write_text(
            f"# Role: analyst\n\nVersion {version}.\n", encoding="utf-8"
        )
    assert load_prompt(tmp_path, "analyst").version == "analyst@10"


def test_a_prompt_without_its_role_line_is_refused(tmp_path: Path) -> None:
    (tmp_path / "analyst@1.md").write_text("Write the results.\n", encoding="utf-8")
    with pytest.raises(PromptError, match="Role"):
        load_prompt(tmp_path, "analyst")


def test_a_missing_prompt_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="methodologist"):
        load_prompt(tmp_path, "methodologist")


def test_a_prompt_fills_its_placeholders_and_refuses_unknown_ones(tmp_path: Path) -> None:
    (tmp_path / "analyst@1.md").write_text("# Role: analyst\n\n$records\n", encoding="utf-8")
    prompt = load_prompt(tmp_path, "analyst")
    assert prompt.fill(records="R0001: r2") == "# Role: analyst\n\nR0001: r2\n"
    with pytest.raises(PromptError, match="records"):
        prompt.fill()


# The methodologist's plan


PLAN = {
    "steps": [
        {
            "title": "Fit a line",
            "description": "Fit a least-squares line to the synthetic data.",
            "success_criterion": "r2 on the test split is at least 0.9.",
            "metrics": ["r2"],
        },
        {
            "title": "Count the rows",
            "description": "Count the rows of the synthetic data.",
            "success_criterion": "The count is reported.",
            "metrics": ["rows", "rows_test"],
        },
    ]
}

RENDERED = """# Method

## Step 1: Fit a line

Fit a least-squares line to the synthetic data.

Success criterion: r2 on the test split is at least 0.9.

- metric: r2

## Step 2: Count the rows

Count the rows of the synthetic data.

Success criterion: The count is reported.

- metric: rows
- metric: rows_test
"""


def test_a_plan_is_rendered_as_numbered_steps_with_their_metrics() -> None:
    assert render_method(MethodPlan.model_validate(PLAN)) == RENDERED


@pytest.mark.parametrize(
    "change",
    [
        {"steps": []},
        {"steps": [{**PLAN["steps"][0], "success_criterion": ""}]},
        {"steps": [{**PLAN["steps"][0], "metrics": []}]},
        {"steps": [{**PLAN["steps"][0], "metrics": ["r2 and auc"]}]},
        {"steps": [{**PLAN["steps"][0], "extra": "x"}]},
    ],
)
def test_a_plan_that_breaks_the_form_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MethodPlan.model_validate(change)


def test_code_output_holds_non_empty_code() -> None:
    assert CodeOutput.model_validate({"code": "print(1)\n"}).code == "print(1)\n"
    with pytest.raises(ValidationError):
        CodeOutput.model_validate({"code": ""})


# The analyst's text and results.md


def test_the_analyst_refers_to_numbers_only_by_result_id() -> None:
    check_analysis_text("The line fits well: [R0001].", {"R0001"})


@pytest.mark.parametrize(
    "text",
    [
        "The line fits with r2 0.97.",
        "Over 3 runs the fit held: [R0001].",
        "See [R0002].",
        "The fit is [R1].",
    ],
)
def test_a_number_without_a_result_id_is_rejected(text: str) -> None:
    with pytest.raises(AgentOutputError):
        check_analysis_text(text, {"R0001"})


def test_results_are_rendered_with_each_records_value_and_unit() -> None:
    output = AnalysisOutput.model_validate({"text": "The line fits well: [R0001]."})
    rendered = render_results(output, [_record("R0001", 0.97)])
    # Finding 9 of M1-16: a dimensionless unit such as score is not shown.
    assert rendered == "# Results\n\nThe line fits well: 0.97 [R0001].\n"
    check_results(rendered, [_record("R0001", 0.97)])


@pytest.mark.parametrize(
    "results",
    [
        "# Results\n\nThe fit is 0.97.\n",
        "# Results\n\nThe fit is 0.95 [R0001].\n",
        "# Results\n\nThe fit is 0.97 [R0009].\n",
        "# Results\n\nIn 2 of the runs: 0.97 [R0001].\n",
        "# Results\n\nThe fit is 0.97 score [R0001].\n",
    ],
)
def test_a_results_md_with_a_number_without_its_result_record_is_rejected(results: str) -> None:
    with pytest.raises(AgentOutputError):
        check_results(results, [_record("R0001", 0.97)])


def test_the_example_reply_of_each_prompt_is_valid() -> None:
    # Each prompt shows the model one reply; it must pass its own schema.
    for role, model in (
        ("methodologist", MethodPlan),
        ("implementer", CodeOutput),
        ("analyst", AnalysisOutput),
    ):
        text = load_prompt(PROMPTS, role).text
        # The example follows "for example:" and ends at the next blank line.
        example = text.split("for example:\n\n", 1)[1].split("\n\n", 1)[0]
        model.model_validate(json.loads(example))


# Findings of M1-16: answers in a code fence


@pytest.mark.parametrize("role", ["methodologist", "implementer", "analyst"])
def test_the_prompts_show_no_code_fence_and_ask_for_one_json_object(role: str) -> None:
    text = load_prompt(PROMPTS, role).text
    assert "```" not in text
    assert "Answer with a single JSON object and nothing else" in text


@pytest.mark.parametrize(
    ("answer", "content"),
    [
        ('```json\n{"code": "x"}\n```', '{"code": "x"}'),
        ('```\n{"code": "x"}\n```', '{"code": "x"}'),
        ('  \n```json\n{\n  "code": "x"\n}\n```\n\n', '{\n  "code": "x"\n}'),
        ('{"code": "x"}', '{"code": "x"}'),
    ],
)
def test_one_fenced_block_is_unwrapped(answer: str, content: str) -> None:
    assert unwrap_code_fence(answer) == content


@pytest.mark.parametrize(
    "answer",
    [
        'Here is the code:\n```json\n{"code": "x"}\n```',
        '```json\n{"code": "x"}\n```\nI hope this helps.',
        '```json\n{"code": "x"}\n```\n```json\n{"code": "y"}\n```',
        '```python\n{"code": "x"}\n```',
    ],
)
def test_anything_but_exactly_one_fenced_block_is_left_as_it_is(answer: str) -> None:
    assert unwrap_code_fence(answer) == answer


# Number words (PR #37 review)


@pytest.mark.parametrize(
    "text",
    [
        "Seventy of the points fit: [R0001].",
        "The fit is twice as good: [R0001].",
        "About half of them: [R0001].",
        "A rise of ten per cent: [R0001].",
        "Ninety PERCENT fit: [R0001].",
        "A thousand points: [R0001].",
        "Eleven of the points fit: [R0001].",
    ],
)
def test_a_number_word_outside_a_reference_is_rejected(text: str) -> None:
    with pytest.raises(AgentOutputError, match="number"):
        check_analysis_text(text, {"R0001"})


def test_words_that_only_contain_a_number_word_are_allowed() -> None:
    check_analysis_text("The bone of the fit is often done: [R0001].", {"R0001"})


def test_a_results_md_with_a_number_word_is_rejected() -> None:
    with pytest.raises(AgentOutputError):
        check_results("# Results\n\nTwelve folds gave 0.97 [R0001].\n", [_record("R0001", 0.97)])


def test_a_number_word_as_the_unit_of_a_reference_is_allowed() -> None:
    record = _record("R0001", 0.97).model_copy(update={"unit": "percent"})
    check_results("# Results\n\nThe fit is 0.97 percent [R0001].\n", [record])


def test_the_analyst_prompt_says_configuration_numbers_belong_in_method_md() -> None:
    text = load_prompt(PROMPTS, "analyst").text
    assert "method.md" in text
    assert "folds" in text


# Findings of M1-16: small number words


@pytest.mark.parametrize(
    "text",
    [
        "Of the two models, the first fits better: [R0001].",
        "One run gave [R0001].",
        "All three models agree: [R0001].",
        "Zero errors were reported beside [R0001].",
        "Ten of them, and [R0001].",
    ],
)
def test_zero_to_ten_are_allowed_as_words(text: str) -> None:
    check_analysis_text(text, {"R0001"})


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("A rise of two percent: [R0001].", "two"),
        ("A rise of two per cent: [R0001].", "two"),
        ("Two percentage points: [R0001].", "Two"),
        ("It is three times better: [R0001].", "three"),
        ("A five-fold gain: [R0001].", "five"),
        ("A five fold gain: [R0001].", "five"),
        ("Up by four points: [R0001].", "four"),
        ("Up by one point: [R0001].", "one"),
        ("Eleven models: [R0001].", "Eleven"),
        ("Twice as good: [R0001].", "Twice"),
    ],
)
def test_a_small_number_word_before_a_unit_or_a_multiple_is_refused(text: str, word: str) -> None:
    with pytest.raises(AgentOutputError, match=repr(word)):
        check_analysis_text(text, {"R0001"})


def test_the_refusal_names_the_word_and_its_sentence() -> None:
    text = "Both models fit well: [R0001]. The tree is three times slower. That is all."
    with pytest.raises(AgentOutputError) as refused:
        check_analysis_text(text, {"R0001"})
    message = str(refused.value)
    assert "'three'" in message
    assert '"The tree is three times slower."' in message


def test_the_analyst_prompt_keeps_to_the_fields_of_each_record() -> None:
    # Lines are wrapped; the phrases are compared with single spaces.
    text = " ".join(load_prompt(PROMPTS, "analyst").text.split())
    assert "both models" in text
    assert "two models" in text
    for field in ("metric", "model", "dataset", "split", "unit"):
        assert field in text
    assert "never add a split, setting or condition the record does not state" in text


def test_the_methodologist_prompt_asks_for_one_number_per_metric() -> None:
    text = " ".join(load_prompt(PROMPTS, "methodologist").text.split())
    assert "one number that answers the research question" in text
    assert "accuracy_comparison" in text
    assert "shape" in text


def test_the_implementer_prompt_names_none_tolerance_split_and_random_state() -> None:
    text = " ".join(load_prompt(PROMPTS, "implementer").text.split())
    assert "None, not null" in text
    assert "tolerance" in text
    assert "cv5" in text
    assert "never train" in text
    assert "random_state" in text


# Finding 9 of M1-16: values rounded to their tolerance, no dimensionless unit


@pytest.mark.parametrize(
    ("value", "unit", "tolerance", "shown"),
    [
        (0.956140350877193, "score", 0.0001, "0.9561 [R0001]"),
        (0.956140350877193, "score", 0.005, "0.96 [R0001]"),
        (95.6140350877193, "percent", 0.01, "95.61 percent [R0001]"),
        (12.3456, "seconds", 0.5, "12 seconds [R0001]"),
        (0.956140350877193, "score", 0.0, "0.956140350877193 [R0001]"),
        (-0.04512, "score", 0.0005, "-0.045 [R0001]"),
    ],
)
def test_a_value_is_shown_to_the_decimals_its_tolerance_implies(
    value: float, unit: str, tolerance: float, shown: str
) -> None:
    record = _record("R0001", value, unit=unit, tolerance=tolerance)
    output = AnalysisOutput.model_validate({"text": "The fit: [R0001]."})
    rendered = render_results(output, [record])
    assert rendered == f"# Results\n\nThe fit: {shown}.\n"
    check_results(rendered, [record])
    # The record keeps the full value.
    assert record.value == value


def test_the_full_value_is_not_what_results_md_shows() -> None:
    record = _record("R0001", 0.956140350877193, tolerance=0.0001)
    with pytest.raises(AgentOutputError):
        check_results("# Results\n\nThe fit: 0.956140350877193 [R0001].\n", [record])


def test_the_analyst_prompt_says_not_to_write_unit_words() -> None:
    text = " ".join(load_prompt(PROMPTS, "analyst").text.split())
    assert "Do not write unit words" in text
    assert "utux adds" in text
