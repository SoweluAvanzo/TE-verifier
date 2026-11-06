## =============================================================================
## te_platform/literature/catalog.py — the curator's classification of the works
## =============================================================================
## GUIDE STEP   extension of 11.1 (source tiers)
## PURPOSE      Reads catalog.yaml: for each citation key, its tier (how close
##              the work is to tokenised systems), the kinds of system it is
##              about, and where a reader finds the original.
## USED BY      literature/ingest.py, literature/rechunk.py, cli.py.
## WHY          A person decides this, not a model: it steers what the agent
##              reads first, and a work's subject does not change per passage.
## =============================================================================

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

Tier = Literal[0, 1, 2, 3]
SystemType = Literal[
    "community_token",
    "defi",
    "dao",
    "stablecoin",
    "protocol",
    "platform_token",
    "local_currency",
    "mutual_credit",
    "time_bank",
]
# What a work may be about: the system types a design can have, and two subjects.
SYSTEM_TYPES = frozenset(SystemType.__args__) | {"foundations", "methods", "law"}

_PATH = Path(__file__).with_name("catalog.yaml")


@lru_cache(maxsize=1)
def _entries() -> dict[str, dict[str, Any]]:
    works: dict[str, dict[str, Any]] = yaml.safe_load(_PATH.read_text(encoding="utf-8"))["works"]
    for key, entry in works.items():
        unknown = set(entry["systems"]) - SYSTEM_TYPES
        if unknown or entry["tier"] not in (0, 1, 2, 3):
            raise ValueError(f"catalog.yaml, {key}: bad tier or systems {sorted(unknown)}")
    return works


def lookup(citation_key: str) -> dict[str, Any] | None:
    """Return a work's {tier, systems, url?}, or None when it is not in the catalog."""
    return _entries().get(citation_key)


def all_entries() -> dict[str, dict[str, Any]]:
    """Return every entry of the catalog, by citation key."""
    return dict(_entries())


def is_legal(systems: list[str]) -> bool:
    """Return True for laws and guidelines, which are split by article."""
    return "law" in systems
