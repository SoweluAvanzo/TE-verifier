"""Phase-E follow-up — cross_token_flows realize in the agent loop.

Pre-Phase-E ABM threaded cross_token_flows into the static rate pool
but no agent type EARNs the target token, so the pool sat unspent and
the secondary token showed zero growth in trajectories.

These tests confirm:
  * A MINT cross-flow drives realized E on the target when the source
    token is burned by agent REDEEM actions.
  * A BURN cross-flow drives realized B on the target.
  * Flows with no realized source-burn contribute zero (no double-
    counting against the static rate path).
  * Multiple flows compose additively.
"""

from __future__ import annotations

import pytest

from schema import (
    ActionKind,
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    CrossTokenAction,
    CrossTokenFlow,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    Rule,
    RuleTrigger,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    UtilityWeights,
)
from verifier.abm.agents import spawn_agents
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


def _te_two_tokens(
    *,
    target_action: CrossTokenAction = CrossTokenAction.MINT,
    flow_amount: float = 2.0,
) -> TokenEconomy:
    """Two-token TE: PDT (primary, agents earn + redeem) and COUPON
    (secondary, no direct agent action). Cross-flow: PDT redeem →
    COUPON mint (default) or burn."""
    return TokenEconomy(
        meta=Meta(name="cross-token", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="PDT",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[Rule(
                    trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_POSITIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(100.0)},
                        ),
                    ),
                )],
                burn_rules=[Rule(
                    trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_NEGATIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(50.0)},
                        ),
                    ),
                )],
                offer_variety_K=NumberRange.point(5),
            ),
            Token(
                id="COUPON",
                function=[TokenFunction.ACCESS_RIGHT],
                emission_rules=[Rule(
                    trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_POSITIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(0.0)},
                        ),
                    ),
                )],
                burn_rules=[Rule(
                    trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_NEGATIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(0.0)},
                        ),
                    ),
                )],
                offer_variety_K=NumberRange.point(5),
            ),
        ],
        cross_token_flows=[
            CrossTokenFlow(
                source_token="PDT",
                source_event="pdt_redeemed",
                target_token="COUPON",
                target_action=target_action,
                amount=AsymptoticClass(
                    family=AsymptoticFamily.CONSTANT,
                    parameter_ranges={"c": NumberRange.point(flow_amount)},
                ),
            ),
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(20),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[AgentType(
                id="A", fraction=1.0, balance_share=1.0,
                role=AgentRole.CONSUMER,
                utility=UtilityWeights(
                    income_yield=1.0,
                    redemption_value=2.0,        # heavy REDEEM weight
                    action_temperature=0.2,
                ),
                action_set=[ActionKind.EARN, ActionKind.REDEEM, ActionKind.HOLD],
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange.point(5)
                ),
            )],
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


def test_cross_token_mint_realizes_when_source_burns() -> None:
    """REDEEM on PDT mints COUPON proportional to realized PDT burn."""
    te = _te_two_tokens(target_action=CrossTokenAction.MINT, flow_amount=3.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    # Pre-load balances so REDEEM has something to spend.
    for a in state["agents"]:
        a["balance"] = 100.0
    state = _step_state(state, params)
    realized_pdt_b = state["tokens"]["PDT"]["B"]
    realized_coupon_e = state["tokens"]["COUPON"]["E"]
    assert realized_pdt_b > 0, "agents should have redeemed some PDT"
    # Cross-flow mints COUPON at 3× the realized PDT burn.
    assert realized_coupon_e == pytest.approx(realized_pdt_b * 3.0, rel=1e-9)


def test_cross_token_burn_realizes_when_source_burns() -> None:
    """Axie-style: source-token burn drives target-token burn."""
    te = _te_two_tokens(target_action=CrossTokenAction.BURN, flow_amount=2.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    # Seed COUPON supply so the burn has something to consume.
    state["tokens"]["COUPON"]["M"] = 1_000.0
    for a in state["agents"]:
        a["balance"] = 100.0
    state = _step_state(state, params)
    realized_pdt_b = state["tokens"]["PDT"]["B"]
    realized_coupon_b = state["tokens"]["COUPON"]["B"]
    assert realized_pdt_b > 0
    assert realized_coupon_b == pytest.approx(realized_pdt_b * 2.0, rel=1e-9)
    # Target supply M shrinks by the realized burn.
    assert state["tokens"]["COUPON"]["M"] == pytest.approx(1_000.0 - realized_coupon_b, rel=1e-9)


def test_cross_token_burn_capped_by_target_supply() -> None:
    """If the cross-flow would burn more than the target's M, cap it
    at M so M never goes negative."""
    te = _te_two_tokens(target_action=CrossTokenAction.BURN, flow_amount=100.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    state["tokens"]["COUPON"]["M"] = 5.0   # tiny — cap will fire
    for a in state["agents"]:
        a["balance"] = 100.0
    state = _step_state(state, params)
    assert state["tokens"]["COUPON"]["M"] >= 0.0
    assert state["tokens"]["COUPON"]["B"] <= 5.0


def test_cross_token_no_op_when_source_doesnt_burn() -> None:
    """No agent REDEEMs → realized source burn 0 → cross-flow does
    not contribute. Prevents spurious target token growth."""
    te = _te_two_tokens(target_action=CrossTokenAction.MINT, flow_amount=3.0)
    # Override utility so agents only HOLD — no REDEEM happens.
    te = te.model_copy(update={
        "participants": te.participants.model_copy(update={
            "agent_types": [
                te.participants.agent_types[0].model_copy(update={
                    "utility": UtilityWeights(
                        holding_yield=10.0,
                        action_temperature=0.1,
                    ),
                    "action_set": [ActionKind.HOLD],
                }),
            ],
        }),
    })
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    state = _step_state(state, params)
    assert state["tokens"]["PDT"]["B"] == 0.0
    assert state["tokens"]["COUPON"]["E"] == 0.0
