## =============================================================================
## te_platform/elicitation/routing.py — named `applies_when` rules
## =============================================================================
## GUIDE STEP   7.2
## PURPOSE      Some questions only make sense for some designs (e.g. cross-
##              token flows only for multi-token systems, the average degree
##              only for network topologies). The protocol refers to these
##              conditions by NAME in `applies_when`; this file implements
##              each name as a small function.
## WHAT A RULE READS
##              The SPEC, never the list of recorded answers: every answer is
##              written into the spec (answers.py), and a spec that arrives
##              whole (web form, uploaded YAML, evals scenario) has no answers
##              at all, yet its values must route the same way. A rule gets,
##              for each slot id it declares in `reads=`, the list of values
##              the spec holds at that slot's ir_path (one per token for
##              "tokens[]..." paths; empty when nothing is stated yet).
##              Write every rule so that an empty list makes it False: the
##              question then simply waits until the answers it depends on
##              exist.
## USED BY      ranking.py (skips slots/stages whose rule is false),
##              coverage.py (checks every rule only reads EARLIER slots).
## DEPENDS ON   protocol.py (slot -> ir_path), paths.py (reading the spec).
## WHY          Same pattern and reasoning as registry/predicates.py (D3): no
##              expression language, no eval() on YAML text.
## CONVENTION   Each rule declares the slot ids it reads (`reads=`). The
##              coverage test uses this to prove a rule never depends on a
##              question that is asked later.
## ACTIVATE     Uncomment the registry, then each rule with a test.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep `ROUTING_RULES`, `rule`,
## `applies` and the rule names exactly: the protocol YAML refers to rules by
## name (README §4 rule 5 lists ROUTING_RULES).
##
## Guide 7.2
## [ ] 1. Imports at the top: `Callable` (collections.abc), `dataclass`,
##        `Any`, Protocol (elicitation.protocol), get_value and index_combos
##        (elicitation.paths). Then the type alias
##        `Known = dict[str, list[Any]]` (slot id -> values in the spec).
## [ ] 2. A frozen dataclass `RoutingRule` with two fields: `fn` (a function
##        Known -> bool) and `reads` (tuple of slot ids the rule reads).
## [ ] 3. The registry `ROUTING_RULES: dict[str, RoutingRule] = {}` and the
##        decorator factory `rule(name, *, reads)`: it stores
##        RoutingRule(fn=fn, reads=reads) under `name`, raises ValueError if
##        the name is already registered, and returns fn unchanged.
## [ ] 4. `known_values(protocol, spec, slot_ids) -> Known`: for each id,
##        the non-null values of the spec at that slot's ir_path, over all
##        index_combos (an unknown slot id gives []).
## [ ] 5. `applies(name, spec, protocol) -> bool`: True when name is None;
##        otherwise the rule's fn(known_values(protocol, spec, rule.reads)).
## [ ] 6. The rules, one at a time, each with a test. Slot ids must match
##        policy/elicitation_protocol.yaml:
##          | @rule("network_topology", reads=("participants.topology",))
##          | def network_topology(k: Known) -> bool:
##        network_topology: "network" is among the topology values;
##        multi_token (reads meta.archetype and tokens.ids): the archetype is
##        governance_utility_pair or play_to_earn_dual, or more than one
##        token id; pegged_or_external_anchor (reads meta.archetype and
##        tokens.value_anchor): the archetype is stablecoin or some token's
##        anchor is pegged or market_price. Read the SOLUTION's note on
##        Stage 6 before using the last one.
## [ ] 7. Check: activate the 7.2 routing tests and
##        test_routing_rules_only_read_earlier_slots (needs coverage.py too)
##        in tests/platform_tests/test_platform_elicitation.py, then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from te_platform.elicitation.paths import get_value, index_combos
from te_platform.elicitation.protocol import Protocol

## What a rule sees: slot id -> the values the spec holds for it (header).
Known = dict[str, list[Any]]


@dataclass(frozen=True)
class RoutingRule:
    """A named condition and the slot ids it reads."""

    fn: Callable[[Known], bool]
    reads: tuple[str, ...]  # slot ids the rule looks at


ROUTING_RULES: dict[str, RoutingRule] = {}


def rule(
    name: str, *, reads: tuple[str, ...]
) -> Callable[[Callable[[Known], bool]], Callable[[Known], bool]]:
    """Register the decorated function as the routing rule `name`."""

    def deco(fn: Callable[[Known], bool]) -> Callable[[Known], bool]:
        if name in ROUTING_RULES:
            raise ValueError(f"routing rule {name!r} registered twice")
        ROUTING_RULES[name] = RoutingRule(fn=fn, reads=reads)
        return fn

    return deco


def known_values(protocol: Protocol, spec: dict[str, Any], slot_ids: tuple[str, ...]) -> Known:
    """Return, for each slot id, the non-null values the spec holds for it."""
    known: Known = {}
    for slot_id in slot_ids:
        slot = protocol.slot(slot_id)
        values = (
            []
            if slot is None
            else [get_value(spec, slot.ir_path, c) for c in index_combos(spec, slot.ir_path)]
        )
        known[slot_id] = [v for v in values if v is not None]
    return known


def applies(name: str | None, spec: dict[str, Any], protocol: Protocol) -> bool:
    """Tell whether a slot/stage with this `applies_when` should be asked now."""
    if name is None:
        return True
    r = ROUTING_RULES[name]
    return r.fn(known_values(protocol, spec, r.reads))


## --- Rules (extend together with the protocol file) ---------------------------
## Slot ids below must match policy/elicitation_protocol.yaml. A rule may read
## a slot the protocol does not have yet: it then sees an empty list.

## docs/specification-flow.md, Stage 1: these two archetypes FORCE a
## multi-token design; otherwise Stage 2 decides (more than one token id).
## The number of tokens is the length of `tokens` (the TE-IR has no count
## field), filled by the `list` slot tokens.ids ("tokens[].id").
_MULTI_TOKEN_ARCHETYPES = {"governance_utility_pair", "play_to_earn_dual"}


@rule("multi_token", reads=("meta.archetype", "tokens.ids"))
def multi_token(k: Known) -> bool:
    """Return True for designs with (or forced to have) several tokens."""
    forced = any(a in _MULTI_TOKEN_ARCHETYPES for a in k["meta.archetype"])
    return forced or len(k["tokens.ids"]) > 1


## Stage 6 (external signals) is forced for stablecoins and for any token
## whose value_anchor is pegged or market_price (specification-flow.md,
## Q2b and Stage 6). The TE-IR has no field for an external signal yet
## (range, rate of change, oracle latency, stale-feed behaviour), so the
## protocol has no Stage 6 and no slot uses this rule today: it is ready for
## the day the schema gains `external_signals`, and lets the interviewer
## tell such designs that external-signal risks are not verified.
_EXTERNAL_ANCHORS = {"pegged", "market_price"}


@rule("pegged_or_external_anchor", reads=("meta.archetype", "tokens.value_anchor"))
def pegged_or_external_anchor(k: Known) -> bool:
    """Return True for stablecoins and tokens anchored outside the protocol."""
    return "stablecoin" in k["meta.archetype"] or any(
        a in _EXTERNAL_ANCHORS for a in k["tokens.value_anchor"]
    )


@rule("network_topology", reads=("participants.topology",))
def network_topology(k: Known) -> bool:
    """Return True when participants interact through a network."""
    # The average degree only matters for network-structured interaction.
    return "network" in k["participants.topology"]
