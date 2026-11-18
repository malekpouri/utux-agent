"""M1-05: the examples of `utux.yaml` and of the lock file in the documents
are complete and valid (M1 rule 2)."""

import json
import re
from pathlib import Path

from utux.schemas.project_config import ProjectConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_KEYS = {"pid", "host", "command", "started_at"}


def _blocks(document: str, language: str) -> list[str]:
    text = (REPO_ROOT / document).read_text(encoding="utf-8")
    return re.findall(rf"```{language}\n(.*?)```", text, flags=re.DOTALL)


def test_the_complete_file_of_the_documentation_is_valid() -> None:
    text = (REPO_ROOT / "docs" / "utux-yaml.md").read_text(encoding="utf-8")
    section = text.split("## A complete file", 1)[1]
    block = re.search(r"```yaml\n(.*?)```", section, flags=re.DOTALL)
    assert block is not None
    config = ProjectConfig.from_yaml(block.group(1), source="docs/utux-yaml.md")
    assert config.local_server.base_url
    assert config.budget.allow_unknown_cost is True


def test_the_utux_yaml_of_the_specification_is_valid() -> None:
    text = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    section = text.split("`utux.yaml` with every field set:", 1)[1]
    found = re.search(r"```yaml\n(.*?)```", section, flags=re.DOTALL)
    assert found is not None
    block = found.group(1)
    config = ProjectConfig.from_yaml(block, source="docs/spec.md")
    assert config.local_server.base_url == "http://localhost:11434/v1"
    assert config.budget.allow_unknown_cost is False


def _lock_examples(document: str) -> list[dict[str, object]]:
    found = []
    for block in _blocks(document, "json"):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and set(data) == LOCK_KEYS:
            found.append(data)
    return found


def test_the_lock_examples_hold_every_field_with_its_type() -> None:
    examples = _lock_examples("docs/project.md") + _lock_examples("docs/spec.md")
    assert len(examples) == 2
    for example in examples:
        assert isinstance(example["pid"], int)
        assert all(isinstance(example[key], str) for key in ("host", "command", "started_at"))
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(example["started_at"]))
