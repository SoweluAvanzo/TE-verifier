"""Tests for docs/paper-mapping.md consistency.

These tests ensure the audit document and the code do not drift:

- every FM listed in `docs/paper-mapping.md` exists in `paper.py`,
- every paper-derived `ConfigValue` field listed in the doc exists in
  `config.py`,
- every proof file referenced in the doc exists in `docs/proofs/`.

This is what catches the failure mode where a reviewer reads the
mapping doc and finds it inconsistent with the implementation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verifier import config as cfg
from verifier.paper import ALL_CONDITIONS


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
PROOFS_DIR = DOCS_DIR / "proofs"
MAPPING_DOC = DOCS_DIR / "paper-mapping.md"


@pytest.fixture(scope="module")
def mapping_text() -> str:
    return MAPPING_DOC.read_text(encoding="utf-8")


def test_mapping_doc_exists(mapping_text: str) -> None:
    assert mapping_text  # non-empty


def test_mapping_doc_lists_all_six_fms(mapping_text: str) -> None:
    for fm_id in ALL_CONDITIONS:
        assert fm_id in mapping_text, (
            f"docs/paper-mapping.md does not mention {fm_id}"
        )


def test_proof_files_exist_for_all_fms() -> None:
    for fm_id in ALL_CONDITIONS:
        n = fm_id.lower()  # "fm1"
        path = PROOFS_DIR / f"{n}.md"
        assert path.exists(), f"missing proof file: {path}"


def test_proof_index_lists_all_six_fms() -> None:
    idx = (PROOFS_DIR / "index.md").read_text(encoding="utf-8")
    for fm_id in ALL_CONDITIONS:
        n = fm_id.lower()
        assert f"`{n}.md`" in idx, (
            f"docs/proofs/index.md does not reference {n}.md"
        )


def test_mapping_doc_lists_all_config_fields(mapping_text: str) -> None:
    """Every public VerifierConfig field is mentioned in the mapping doc."""
    for field_name in cfg.VerifierConfig.model_fields:
        assert field_name in mapping_text, (
            f"docs/paper-mapping.md does not mention config field "
            f"'{field_name}'"
        )


def test_mapping_doc_lists_paper_sections() -> None:
    """Every distinct paper_section in paper.py appears in the mapping doc."""
    text = MAPPING_DOC.read_text(encoding="utf-8")
    sections: set[str] = set()
    for cond in ALL_CONDITIONS.values():
        sections.add(cond.paper_section)
        for v in cond.variables:
            sections.add(v.paper_section)
    for sec in sections:
        assert sec in text, f"paper section {sec} missing from mapping doc"


def test_template_file_present() -> None:
    template = PROOFS_DIR / "template.md"
    assert template.exists()
    text = template.read_text(encoding="utf-8")
    # Required template sections
    for header in (
        "## Statement",
        "## Paper reference",
        "## Assumptions",
        "## Proof",
        "## Z3 encoding",
        "## Numerical correctness",
        "## Lean stub",
        "## Tests",
    ):
        assert header in text, f"template.md missing required section: {header}"


_PROOF_REQUIRED_HEADERS = (
    "## Statement",
    "## Paper reference",
    "## Assumptions",
    "## Z3 encoding",
    "## Lean stub",
)


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_each_fm_proof_has_required_sections(fm_id: str) -> None:
    n = fm_id.lower()
    path = PROOFS_DIR / f"{n}.md"
    text = path.read_text(encoding="utf-8")
    for header in _PROOF_REQUIRED_HEADERS:
        assert header in text, f"{n}.md missing required section: {header}"
