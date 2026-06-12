"""Resolve a RuleTrigger or EventOccurrence into a normalized view.

Phase-H introduces a top-level ``TokenEconomy.events`` catalog that
mint/burn/population machinery references by id. This module provides
the single resolution path used by every downstream consumer (verifier,
ABM, conditions). Consumers stop touching ``rule.trigger.kind`` /
``rule.trigger.event_frequency`` directly and instead call
``resolve_trigger(rule, te)``.

Resolution rules:

* ``event_id`` set → pull ``kind`` + ``frequency`` (or
  ``frequency_distribution``) + event-level ``conditions`` from the
  catalog entry.
* ``event_id`` unset (legacy path) → use the rule's own inline fields.

Event-level conditions are concatenated with rule-level conditions so
the verifier sees one combined predicate list per rule firing.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import (
    AsymptoticClass,
    Condition,
    DistributionSpec,
    EventDefinition,
    EventOccurrence,
    EventTriggerKind,
    Rule,
    RuleTrigger,
    TokenEconomy,
)

# ---------------------------------------------------------------------------
# Kind vocabulary
# ---------------------------------------------------------------------------
# ``ResolvedTrigger.kind`` is a plain string drawn from EITHER the legacy
# rule-side enums (EmissionTriggerKind / BurnTriggerKind) or the Phase-H
# catalog enum (EventTriggerKind). The two vocabularies agree on every
# value except one: the legacy emission enum spells the behavioral kind
# "behavioral_event" while the catalog enum spells it "behavioral". The
# predicate properties below own that mapping in ONE place — consumers
# must use them instead of comparing kind strings directly.

_CONTRIBUTION_KIND_VALUES: frozenset[str] = frozenset(
    {
        "behavioral_event",        # legacy EmissionTriggerKind.BEHAVIORAL_EVENT
        "behavioral",              # catalog EventTriggerKind.BEHAVIORAL
        "physical_resource_flow",  # identical spelling in both vocabularies
    }
)


@dataclass(frozen=True)
class ResolvedTrigger:
    """Normalized view of what makes a Rule fire."""

    kind: str                                # value of EmissionTriggerKind / BurnTriggerKind / EventTriggerKind
    event_id: str | None                     # set when the rule resolves to a catalog entry
    event_label: str | None                  # human-readable label, or None for legacy inline
    event_frequency: AsymptoticClass | None  # None for time-based / unspecified
    conditions: list[Condition]              # event-level AND rule-level, in declaration order
    event_frequency_distribution: DistributionSpec | None = None  # stochastic arrivals (catalog only)

    @property
    def is_contribution(self) -> bool:
        """True when the rule earns supply through contribution-style
        behavior (behavioral or physical resource flow) — the FM4
        applicability signal."""
        return self.kind in _CONTRIBUTION_KIND_VALUES

    @property
    def is_demand_driven(self) -> bool:
        return self.kind == "demand_driven"

    @property
    def is_time_based(self) -> bool:
        return self.kind == "time_based"

    @property
    def is_expiry(self) -> bool:
        return self.kind == "expiry"

    @property
    def is_rule_driven(self) -> bool:
        return self.kind == "rule_driven"


def resolve_trigger(rule: Rule, te: TokenEconomy) -> ResolvedTrigger:
    """Single source of truth for a Rule's effective trigger configuration."""
    trigger: RuleTrigger = rule.trigger
    if trigger.event_id is not None:
        try:
            event: EventDefinition = te.get_event(trigger.event_id)
        except KeyError as exc:
            raise ValueError(
                f"Rule references unknown event_id '{trigger.event_id}'"
            ) from exc
        return ResolvedTrigger(
            kind=event.kind.value,
            event_id=event.id,
            event_label=event.label,
            event_frequency=event.frequency,
            conditions=list(event.conditions) + list(trigger.conditions),
            event_frequency_distribution=event.frequency_distribution,
        )
    # Legacy inline path — preserve original semantics.
    kind = trigger.kind.value if trigger.kind is not None else "none"
    return ResolvedTrigger(
        kind=kind,
        event_id=None,
        event_label=trigger.event_predicate,
        event_frequency=trigger.event_frequency,
        conditions=list(trigger.conditions),
        event_frequency_distribution=None,
    )


def resolve_event_occurrence(
    condition: EventOccurrence, te: TokenEconomy
) -> tuple[str | None, str | None]:
    """Map an EventOccurrence to (event_id, label).

    When ``event_id`` is set on the condition, return it directly.
    Otherwise (legacy ``source_token`` + ``source_event``), try to
    locate the matching event in ``te.events`` whose label or kind
    matches ``source_event``. Returns ``(None, None)`` if unresolved —
    the caller decides whether to treat that as NEVER or fall through
    to the old token-rule lookup.
    """
    if condition.event_id is not None:
        try:
            event = te.get_event(condition.event_id)
            return event.id, event.label
        except KeyError:
            return condition.event_id, None
    # Legacy path: search the events catalog for a label match.
    if condition.source_event:
        for event in te.events:
            if event.label == condition.source_event or event.id == condition.source_event:
                return event.id, event.label
    return None, None
