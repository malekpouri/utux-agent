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
)
from utux.errors import AgentOutputError, PromptError
from utux.schemas.result_record import ResultRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / PROMPTS_DIRECTORY


def _record(record_id: str, value: float, metric: str = "r2") -> ResultRecord:
    return ResultRecord(
        schema_version=1,
        id=record_id,
        metric=metric,
        value=value,
        unit="score",
        dataset="synthetic_line",
        model="linear",
        split="test",
        run_id="r001",
        source="runs/r001/outputs/metrics.json",
        tolerance=0.005,
    )


# Prompts


@pytest.mark.parametrize("role", ["methodologist", "implementer", "analyst"])
def test_each_role_has_a_versioned_prompt_in_the_pack(role: str) -> None:
    prompt = load_prompt(PROMPTS, role)
    assert prompt.version == f"{role}@1"
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
    assert rendered == "# Results\n\nThe line fits well: 0.97 score [R0001].\n"
    check_results(rendered, [_record("R0001", 0.97)])


@pytest.mark.parametrize(
    "results",
    [
        "# Results\n\nThe fit is 0.97.\n",
        "# Results\n\nThe fit is 0.95 score [R0001].\n",
        "# Results\n\nThe fit is 0.97 score [R0009].\n",
        "# Results\n\nIn 2 of the runs: 0.97 score [R0001].\n",
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
        example = text.split("```json\n", 1)[1].split("```", 1)[0]
        model.model_validate(json.loads(example))
