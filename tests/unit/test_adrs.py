"""M0-02: decision records exist, are accepted, dated and cite their source.

The fourth criterion of M0-02, that no ADR introduces a decision absent from
the specification and RFCs, is a matter for human review and is not tested.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = REPO_ROOT / "docs" / "adr"

ADRS = [
    "0001-langgraph-orchestration-engine.md",
    "0002-file-based-stage-contracts-sqlite-checkpoints.md",
    "0003-apache-2-licence-no-denario-code.md",
    "0004-three-public-three-internal-interfaces.md",
    "0005-mcp-for-domain-tools.md",
    "0006-deterministic-verdict-rules.md",
]

# Later ADRs are checked too, so the per-file tests run on every numbered file
# in the directory and not only on the six named above.
ALL_ADRS = sorted(path.name for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))

STATUS = re.compile(r"^- Status: (Proposed|Accepted|Superseded by ADR-\d{4})$", flags=re.MULTILINE)

SECTIONS = ["Context", "Decision", "Alternatives rejected", "Consequences", "Sources"]

# A citation names a document and a section of it, for example
# "docs/spec.md, section 6" or "docs/rfc/RFC-001.md, section 4".
CITATION = re.compile(r"`docs/(spec\.md|rfc/RFC-00[12]\.md)`, sections? \d+")


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


@pytest.mark.parametrize("name", [*ADRS, "template.md"])
def test_named_adrs_and_template_exist(name: str) -> None:
    assert (ADR_DIR / name).is_file()


@pytest.mark.parametrize("name", ADRS)
def test_closed_decision_is_accepted(name: str) -> None:
    text = (ADR_DIR / name).read_text(encoding="utf-8")
    assert re.search(r"^- Status: Accepted$", text, flags=re.MULTILINE)


def test_template_has_every_section() -> None:
    text = (ADR_DIR / "template.md").read_text(encoding="utf-8")
    assert "- Status:" in text
    assert "- Date:" in text
    assert list(_sections(text)) == SECTIONS


@pytest.mark.parametrize("name", ALL_ADRS)
def test_adr_has_title_status_and_date(name: str) -> None:
    text = (ADR_DIR / name).read_text(encoding="utf-8")
    number = int(name[:4])
    assert re.match(rf"# ADR-{number:04d}: \S", text)
    assert STATUS.search(text)
    assert re.search(r"^- Date: \d{4}-\d{2}-\d{2}$", text, flags=re.MULTILINE)


@pytest.mark.parametrize("name", ALL_ADRS)
def test_adr_has_every_section_with_content(name: str) -> None:
    sections = _sections((ADR_DIR / name).read_text(encoding="utf-8"))
    assert list(sections) == SECTIONS
    for title, body in sections.items():
        assert body.strip(), f"section '{title}' is empty"


@pytest.mark.parametrize("name", ALL_ADRS)
def test_adr_cites_a_section_of_the_specification_or_an_rfc(name: str) -> None:
    sources = _sections((ADR_DIR / name).read_text(encoding="utf-8"))["Sources"]
    assert CITATION.search(sources)


@pytest.mark.parametrize("name", ALL_ADRS)
def test_cited_documents_exist(name: str) -> None:
    text = (ADR_DIR / name).read_text(encoding="utf-8")
    for cited in set(re.findall(r"`(docs/[\w/.-]+\.md)`", text)):
        assert (REPO_ROOT / cited).is_file(), cited


@pytest.mark.parametrize("document", ["docs/spec.md", "docs/rfc/RFC-001.md", "docs/rfc/RFC-002.md"])
def test_readme_links_the_project_documents(document: str) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"]({document})" in readme
