"""Tripwire: no new direct trigger-field reads in the verifier.

Phase-H's contract (``verifier/events_resolver.py``) is that every
consumer reads trigger kind / frequency / predicate through
``resolve_trigger(rule, te)`` — never via ``rule.trigger.kind`` /
``rule.trigger.event_frequency`` / ``rule.trigger.event_predicate``.
The FM4 not-applicable bug (and eight sibling sites) existed because
that contract was unenforced: a consumer written before the events
catalog kept reading the inline fields, which are ``None`` for
catalog-style rules.

This test makes the contract structural. The ALLOWED set below is the
exhaustive snapshot of legitimate occurrences (the resolver itself,
documented ``te is None`` fallback branches, and string templates in
display-only modules). Any NEW direct read anywhere under ``verifier/``
fails this test with a pointer to the resolver.

If you are here because the test went red: call
``resolve_trigger(rule, te)`` (threading ``te`` if needed) instead of
reading the trigger field, then — only if your line is a genuine
``te is None`` back-compat fallback — add it to ALLOWED with a comment.
"""

from __future__ import annotations

import pathlib
import re

VERIFIER_DIR = pathlib.Path(__file__).parent.parent / "verifier"

FORBIDDEN = re.compile(
    r"\.trigger\.(kind|event_frequency|event_predicate)\b"
)

# The resolver IS the single allowed reader — exempt wholesale.
ALLOWED_FILES: set[str] = {"events_resolver.py"}

# (relative path, exact stripped line) — the audited allowed set.
ALLOWED: set[tuple[str, str]] = {
    # ``te is None`` back-compat fallbacks (hand-built rules outside a TE).
    ("asymptotic.py", "resolved_frequency = rule.trigger.event_frequency"),
    ("risk.py", "freq_ac = rule.trigger.event_frequency"),
    ("failure_modes/fm1_oversupply.py", "resolved_ef = rule.trigger.event_frequency"),
    ("simulate/trajectory.py", "freq_ac = rule.trigger.event_frequency"),
    ("shape_summary.py", "freq_ac = rule.trigger.event_frequency"),
    ("abm/engine.py", "frequency_ac = rule.trigger.event_frequency"),
    # Display-only string templates (variable-name prettification / docs).
    ("counterexample.py", '"tokens[{tok}].emission_rules[{i}].trigger.event_frequency.{p}",'),
    ("counterexample.py", '"tokens[{tok}].burn_rules[{i}].trigger.event_frequency.{p}",'),
    ("paper.py", 'derivation_source="tokens[].emission_rules.function × tokens[].emission_rules.trigger.event_frequency",'),
    ("paper.py", 'derivation_source="tokens[].burn_rules.function × tokens[].burn_rules.trigger.event_frequency",'),
}


def test_no_new_direct_trigger_reads() -> None:
    violations: list[str] = []
    for path in sorted(VERIFIER_DIR.rglob("*.py")):
        rel = str(path.relative_to(VERIFIER_DIR))
        if rel in ALLOWED_FILES:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not FORBIDDEN.search(line):
                continue
            if (rel, line.strip()) in ALLOWED:
                continue
            violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, (
        "Direct trigger-field read(s) found — route through "
        "verifier.events_resolver.resolve_trigger(rule, te) instead "
        "(see this test's docstring):\n" + "\n".join(violations)
    )
