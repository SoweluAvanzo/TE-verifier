"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import TokenEconomy, load_te
from verifier import Report, verify

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return EXAMPLES_DIR


def load_example(name: str) -> TokenEconomy:
    return load_te(EXAMPLES_DIR / f"{name}.yaml")


def report_for(name: str) -> Report:
    return verify(load_example(name))


def lookup_status(report: Report, fm_substring: str, subject: str) -> str:
    """Return the status for the (failure_mode containing fm_substring, subject) verdict."""
    for v in report.verdicts:
        if fm_substring in v.failure_mode and v.subject == subject:
            return v.status.value
    raise AssertionError(
        f"no verdict found matching '{fm_substring}' / subject={subject}; "
        f"available: {[(v.failure_mode, v.subject) for v in report.verdicts]}"
    )
