"""v2 → v1 structural adapter shared by every Phase-B FM checker.

Phase B of the v2 migration adds ``*_v2.py`` modules — one per FM —
whose check methods accept ``TokenEconomyV2`` as input. Internally they
delegate to the existing v1 checker. This module holds the single
adapter that builds a v1 IR from a v2 IR; every v2 FM imports
``to_v1_for_fm`` from here.

Phase C will replace this adapter with v2-native helpers that reason
about multi-phase Functions, goods, redemptions, and events directly.
Until then, this is the bridge.

Goods, redemptions, and events are dropped during the adapter step —
the v1 FMs don't read them. ``expected_Q_override`` is required:
v1's FM1 / FM3 read ``participants.expected_Q``, and a v2 IR that
doesn't carry it (because Q would be goods-derived in a future phase)
cannot be checked via this adapter yet.

For phaseable Functions, only the first phase is used. All
v1-migrated IRs have exactly one phase per Function, so this is
lossless on every existing example. Native v2 IRs with multi-phase
Functions are out of scope for Phase B.
"""

from __future__ import annotations

from schema import te_ir as v1
from schema import te_ir_v2 as v2


# ---------------------------------------------------------------------------
# Leaf adapters
# ---------------------------------------------------------------------------


def _ac_to_v1(ac: v2.AsymptoticClass) -> v1.AsymptoticClass:
    bounds = (
        v1.Bounds(min=ac.bounds.min, max=ac.bounds.max)
        if ac.bounds is not None
        else None
    )
    return v1.AsymptoticClass(
        family=v1.AsymptoticFamily(ac.family.value),
        degree=ac.degree,
        bounds=bounds,
        parameter_ranges={
            k: v1.NumberRange(min=r.min, max=r.max)
            for k, r in ac.parameter_ranges.items()
        },
    )


def _function_to_v1_rule(fn: v2.Function, *, is_burn: bool) -> v1.Rule:
    """Build a v1 Rule from a v2 Function using only its first phase.

    Single-phase Functions (every v1-migrated Function is one) round-
    trip exactly. Multi-phase native v2 Functions silently drop
    phases 2+ — handled by v2-native helpers in Phase C.
    """
    if not fn.phases:
        raise ValueError("Function has no phases")
    first = fn.phases[0]

    if is_burn:
        if fn.trigger_kind is None:
            v1_kind: v1.EmissionTriggerKind | v1.BurnTriggerKind = (
                v1.BurnTriggerKind.NONE
            )
        else:
            v1_kind = v1.BurnTriggerKind(fn.trigger_kind.value)
    else:
        if fn.trigger_kind is None:
            v1_kind = v1.EmissionTriggerKind.NONE
        else:
            v1_kind = v1.EmissionTriggerKind(fn.trigger_kind.value)

    trigger = v1.RuleTrigger(
        kind=v1_kind,
        event_predicate=fn.event_predicate,
        event_frequency=(
            _ac_to_v1(fn.event_frequency)
            if fn.event_frequency is not None
            else None
        ),
        conditions=[],
    )
    schedule = (
        v1.ScheduleModifiers(
            supply_cap=fn.schedule.supply_cap,
            halving_period=fn.schedule.halving_period,
            halving_factor=fn.schedule.halving_factor,
            halving_offset=fn.schedule.halving_offset,
            vesting_periods=fn.schedule.vesting_periods,
        )
        if fn.schedule is not None
        else None
    )
    return v1.Rule(
        trigger=trigger,
        function=v1.FunctionShape(
            sign=v1.FunctionSign(first.shape.sign.value),
            asymptotic_class=_ac_to_v1(first.shape.asymptotic_class),
        ),
        regimes=[],
        schedule=schedule,
    )


def _cross_token_flow_to_v1(ctf: v2.CrossTokenFlow) -> v1.CrossTokenFlow:
    if not ctf.amount.phases:
        raise ValueError("CrossTokenFlow.amount Function has no phases")
    amount_ac = _ac_to_v1(ctf.amount.phases[0].shape.asymptotic_class)
    return v1.CrossTokenFlow(
        source_token=ctf.source_token,
        source_event=ctf.source_event,
        target_token=ctf.target_token,
        target_action=v1.CrossTokenAction(ctf.target_action.value),
        amount=amount_ac,
        coupling=v1.FlowCoupling(ctf.coupling.value),
        coupling_ratio=(
            v1.NumberRange(
                min=ctf.coupling_ratio.min,
                max=ctf.coupling_ratio.max,
            )
            if ctf.coupling_ratio is not None
            else None
        ),
    )


def _token_to_v1(token: v2.Token) -> v1.Token:
    return v1.Token(
        id=token.id,
        function=[v1.TokenFunction(f.value) for f in token.function],
        value_anchor=v1.ValueAnchor(token.value_anchor.value),
        transferable=token.transferable,
        holding_incentives=[
            v1.HoldingIncentiveMechanism(hi.value) for hi in token.holding_incentives
        ],
        earning_mechanisms=[
            v1.TokenEarningMechanism(em.value) for em in token.earning_mechanisms
        ],
        contribution_verification=(
            v1.ContributionVerification(token.contribution_verification.value)
            if token.contribution_verification is not None
            else None
        ),
        redemption_mechanism=(
            v1.RedemptionMechanism(token.redemption_mechanism_override.value)
            if token.redemption_mechanism_override is not None
            else None
        ),
        emission_rules=[
            _function_to_v1_rule(f, is_burn=False) for f in token.emission_rules
        ],
        burn_rules=[
            _function_to_v1_rule(f, is_burn=True) for f in token.burn_rules
        ],
        initial_distribution=v1.InitialDistribution(
            kind=v1.InitialDistributionKind(token.initial_distribution.kind.value),
            amount=(
                v1.NumberRange(
                    min=token.initial_distribution.amount.min,
                    max=token.initial_distribution.amount.max,
                )
                if token.initial_distribution.amount is not None
                else None
            ),
            notes=token.initial_distribution.notes,
        ),
        offer_variety_K=(
            v1.NumberRange(
                min=token.offer_variety_K_override.min,
                max=token.offer_variety_K_override.max,
            )
            if token.offer_variety_K_override is not None
            else None
        ),
    )


def _agent_to_v1(ag: v2.AgentType) -> v1.AgentType:
    return v1.AgentType(
        id=ag.id,
        fraction=ag.fraction,
        expected_holding_time=v1.HoldingTimeDistribution(
            expected_periods=v1.NumberRange(
                min=ag.expected_holding_time.expected_periods.min,
                max=ag.expected_holding_time.expected_periods.max,
            )
        ),
        balance_share=ag.balance_share,
        role=v1.AgentRole(ag.role.value) if ag.role is not None else None,
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def to_v1_for_fm(te: v2.TokenEconomyV2) -> v1.TokenEconomy:
    """Adapt a v2 IR to a v1 IR for consumption by the v1 FM checkers.

    Goods, redemptions, and events are dropped — the v1 FMs do not
    read them. ``expected_Q_override`` must be present on the v2 IR:
    a v2 IR that intends Q to be goods-derived (a Phase-C feature)
    cannot be checked via this adapter.

    Raises ``ValueError`` if ``expected_Q_override`` is missing.
    """
    if te.participants.expected_Q_override is None:
        raise ValueError(
            "v2 → v1 FM adapter requires participants.expected_Q_override. "
            "Goods-derived Q is a Phase-C feature; until then, declare "
            "expected_Q_override explicitly."
        )

    return v1.TokenEconomy(
        meta=v1.Meta(
            name=te.meta.name,
            description=te.meta.description,
            archetype=v1.Archetype(te.meta.archetype.value),
            nfrs=v1.NFRs(
                resilience=te.meta.nfrs.resilience,
                adaptability=te.meta.nfrs.adaptability,
                accessibility=te.meta.nfrs.accessibility,
                transparency=te.meta.nfrs.transparency,
                proportionality=te.meta.nfrs.proportionality,
                circulation_speed=v1.CirculationSpeed(
                    te.meta.nfrs.circulation_speed.value
                ),
                governance_maturity=v1.GovernanceMaturity(
                    te.meta.nfrs.governance_maturity.value
                ),
            ),
        ),
        tokens=[_token_to_v1(t) for t in te.tokens],
        participants=v1.ParticipantsSpec(
            count_N=v1.NumberRange(
                min=te.participants.count_N.min,
                max=te.participants.count_N.max,
            ),
            expected_Q=v1.NumberRange(
                min=te.participants.expected_Q_override.min,
                max=te.participants.expected_Q_override.max,
            ),
            average_demand_d=v1.NumberRange(
                min=te.participants.average_demand_d.min,
                max=te.participants.average_demand_d.max,
            ),
            growth_g=_ac_to_v1(te.participants.growth_g),
            topology=v1.Topology(te.participants.topology.value),
            agent_types=[_agent_to_v1(a) for a in te.participants.agent_types],
            average_activity_frequency=(
                v1.NumberRange(
                    min=te.participants.average_activity_frequency.min,
                    max=te.participants.average_activity_frequency.max,
                )
                if te.participants.average_activity_frequency is not None
                else None
            ),
            topology_params={
                k: v1.NumberRange(min=r.min, max=r.max)
                for k, r in te.participants.topology_params.items()
            },
        ),
        governance=v1.GovernanceSpec(
            type=v1.GovernanceType(te.governance.type.value),
            rule_structure={
                k: v1.ControllingActor(v.value)
                for k, v in te.governance.rule_structure.items()
            },
            monitoring_capacity_gamma=v1.NumberRange(
                min=te.governance.monitoring_capacity_gamma.min,
                max=te.governance.monitoring_capacity_gamma.max,
            ),
            sanction_structure=v1.SanctionStructure(
                kind=v1.SanctionKind(te.governance.sanction_structure.kind.value),
                S_normalized=(
                    v1.NumberRange(
                        min=te.governance.sanction_structure.S_normalized.min,
                        max=te.governance.sanction_structure.S_normalized.max,
                    )
                    if te.governance.sanction_structure.S_normalized is not None
                    else None
                ),
            ),
            token_balance_gini=(
                v1.NumberRange(
                    min=te.governance.token_balance_gini.min,
                    max=te.governance.token_balance_gini.max,
                )
                if te.governance.token_balance_gini is not None
                else None
            ),
            vote_weighting=v1.VoteWeighting(te.governance.vote_weighting.value),
            vote_weighting_params={
                k: v1.NumberRange(min=r.min, max=r.max)
                for k, r in te.governance.vote_weighting_params.items()
            },
        ),
        cross_token_flows=[
            _cross_token_flow_to_v1(c) for c in te.cross_token_flows
        ],
    )
