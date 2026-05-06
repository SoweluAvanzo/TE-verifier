"""Counterexample prettification (P1).

The Z3 solver names internal variables with a verifier-internal scheme
(e.g. `DAI_ownE_for_fm1_DAI_emit_0_fn__b`). Without rewriting, those
names leak straight into the user-facing counterexample table and
make it unreadable.

This module rewrites the parameter_values dict on every Verdict's
counterexample to use IR-path-style names that the user can map back
to the form / YAML they wrote. Applied at dispatcher level so CLI,
JSON, and web surfaces all benefit uniformly.

The renaming is presentation-only — no math changes — and is
deliberately conservative: any name we don't recognize is left as-is
so future FM additions don't silently regress.
"""

from __future__ import annotations

import re

from verifier.failure_modes.base import Verdict


# Patterns matched in order. Each is (regex, replacement_template).
# Capture groups feed the template via .format().
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Verifier-internal aggregate intermediates we surfaced to
    # downstream code (verdict narratives) — keep readable names.
    (re.compile(r"^(?P<tok>[A-Za-z0-9_]+?)__Q$"), "{tok}.Q (transaction volume)"),
    (re.compile(r"^(?P<tok>[A-Za-z0-9_]+?)__E_total$"), "{tok}.E_total (per-period emission)"),
    (re.compile(r"^(?P<tok>[A-Za-z0-9_]+?)__B_total$"), "{tok}.B_total (per-period burn)"),
    # Per-rule emission / burn parameters
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_emit_(?P<i>\d+)_fn__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "tokens[{tok}].emission_rules[{i}].function.{p}",
    ),
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_emit_(?P<i>\d+)_freq__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "tokens[{tok}].emission_rules[{i}].trigger.event_frequency.{p}",
    ),
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_burn_(?P<i>\d+)_fn__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "tokens[{tok}].burn_rules[{i}].function.{p}",
    ),
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_burn_(?P<i>\d+)_freq__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "tokens[{tok}].burn_rules[{i}].trigger.event_frequency.{p}",
    ),
    # Cross-token flows
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_xtmint_(?P<i>\d+)__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "cross_token_flows[{i}] (mint→{tok}).{p}",
    ),
    (
        re.compile(
            r"^(?P<tok>[A-Za-z0-9_]+?)_xtburn_(?P<i>\d+)__(?P<p>[A-Za-z0-9_]+)$"
        ),
        "cross_token_flows[{i}] (burn→{tok}).{p}",
    ),
    # FM2 per-agent τ
    (
        re.compile(
            r"^tau_(?P<tok>[A-Za-z0-9_]+?)_(?P<agent>[A-Za-z0-9_]+)$"
        ),
        "agent_types[{agent}].expected_holding_time (token {tok})",
    ),
]


# Names whose entries should be removed entirely from the user-facing
# counterexample table because they are verifier-internal duplicates
# of an already-renamed variable. The `_ownE_for_fm*` chain is the
# precompute dictionary used by FM1/FM3 to build proportional cross-
# token couplings; Z3 declares fresh variables for it that overlap
# semantically with the actual rule parameters in the same query.
_DROP_PATTERN = re.compile(r"_ownE_for_fm\d+_")


def prettify_param_name(name: str) -> str | None:
    """Rewrite one Z3 variable name to a user-facing IR path.

    Returns the rewritten name, or `None` to indicate the entry should
    be dropped from the counterexample table (verifier-internal
    duplicate).
    """
    if _DROP_PATTERN.search(name):
        return None
    for pattern, template in _PATTERNS:
        m = pattern.match(name)
        if m:
            return template.format(**m.groupdict())
    return name


def prettify_counterexample(params: dict[str, float]) -> dict[str, float]:
    """Apply `prettify_param_name` across an entire dict.

    On collision (two original names map to the same pretty name) the
    last writer wins — but we keep the first appearance order via a
    plain dict.
    """
    out: dict[str, float] = {}
    for k, v in params.items():
        new = prettify_param_name(k)
        if new is None:
            continue
        out[new] = v
    return out


def prettify_verdicts(verdicts: list[Verdict]) -> None:
    """Mutate every Verdict.counterexample.parameter_values in place."""
    for v in verdicts:
        if v.counterexample is None:
            continue
        v.counterexample = v.counterexample.model_copy(
            update={
                "parameter_values": prettify_counterexample(
                    v.counterexample.parameter_values
                )
            }
        )
