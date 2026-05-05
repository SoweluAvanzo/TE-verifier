"""Paper-canonical truth source for the six failure-mode conditions.

This module is the single authoritative encoding of §3 of the paper
(Domenicale–Avanzo–Schifanella, *Six Failure Modes: A Pre-Deployment
Diagnostic Framework for Tokenized Collaborative Economies*, DLT2026).

Every failure-mode module imports its formal condition, variable list,
violation predicate, and critical-value formula from here. The rest of
the codebase **must not** restate paper math; it imports from this
module instead. This is what keeps the verifier provably faithful to
the paper as the paper goes through publication revisions.

For each failure mode, a `PaperCondition` carries:

- the formal sustainability statement (LaTeX + ASCII),
- the violation predicate (the formal negation),
- the variables involved with their domains, units, and paper sections,
- the closed-form critical-value formulas used by the Z3 optimization
  layer to extract concrete redesign thresholds,
- the elicitation hooks (which Roadmap docx questions feed each variable),
- the plain-English explanation surfaces (why-it-matters, real-world
  signal, design knobs) that the webapp questionnaire and verdict screens
  render verbatim.

No numeric thresholds live in this module. Numeric thresholds live in
`verifier.config.VerifierConfig` with paper defaults and override
semantics. This module references thresholds *symbolically* (e.g.
``τ̄ ≤ τ_bar_ceiling``) and the config supplies the value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


# ---------------------------------------------------------------------------
# Variable descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperVariable:
    """A variable that appears in one or more paper conditions.

    Attributes
    ----------
    symbol:
        The mathematical symbol the paper uses (UTF-8). Examples: ``"γ"``,
        ``"τ̄"``, ``"Γ"``, ``"ρ"``, ``"E(t)"``.
    name:
        The plain-English short name. Example: ``"monitoring capacity"``.
    description:
        One-sentence definition the questionnaire UI can render verbatim.
    domain:
        Mathematical domain as a string: ``"[0, 1]"``, ``"ℝ_{>0}"``,
        ``"ℕ_{≥1}"``. The Z3 encoding uses this to bound the variable.
    units:
        Units string. ``"probability"`` for γ, ``"periods"`` for τ̄,
        ``"tokens/period"`` for E(t), ``""`` for dimensionless ratios.
    paper_section:
        The §-reference where the variable is introduced.
    elicitation_field:
        The IR field path the user populates to set this variable. Used by
        the webapp to link verdict explanations back to the source question.
        Example: ``"governance.monitoring_capacity_gamma"``.
    derivation_source:
        If this variable is normally **derived** from a structured user
        choice rather than entered directly, the structured field that
        feeds it. Example for γ: ``"tokens[].contribution_verification"``.
        ``None`` when the variable is supplied directly.
    """

    symbol: str
    name: str
    description: str
    domain: str
    units: str
    paper_section: str
    elicitation_field: str | None = None
    derivation_source: str | None = None


# ---------------------------------------------------------------------------
# Critical-value formulas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriticalValueFormula:
    """A closed-form expression for a parameter's critical (boundary) value.

    The Z3 optimization layer in `verifier.failure_modes.base` uses these
    to validate (in tests) that the optimizer returns the analytical
    extremum, and to render redesign hints in the verdict.

    Attributes
    ----------
    parameter:
        The variable name we are solving for. Example: ``"gamma"``.
    formula_latex:
        The closed-form LaTeX, e.g. ``"\\gamma^* = (T - R) / S"``.
    formula_ascii:
        ASCII rendering for terminals: ``"gamma_star = (T - R) / S"``.
    direction:
        ``">="`` if the system is sustainable when the variable is **at
        least** this value; ``"<="`` for the reverse. Example: γ\\* with
        ``">="`` because ``γ ≥ γ*`` is the safe side.
    explanation:
        One-paragraph plain-English explanation. Rendered by the verdict
        screen alongside the numeric threshold.
    """

    parameter: str
    formula_latex: str
    formula_ascii: str
    direction: str  # ">=" or "<="
    explanation: str


# ---------------------------------------------------------------------------
# Failure-mode condition descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperCondition:
    """A failure-mode formal condition as stated in the paper.

    Carries everything the verifier needs to (a) check the condition,
    (b) extract a critical value, (c) explain the verdict to the user,
    and (d) link back to the elicitation questions that feed it.

    Attributes
    ----------
    fm_id:
        Stable identifier ``"FM1"`` … ``"FM6"``.
    name:
        Short paper title. Example: ``"Free-Rider Collapse"``.
    paper_section:
        ``"§3.4"`` and similar.
    paper_equations:
        Tuple of equation references the condition is built from.
    sustainability_latex / sustainability_ascii:
        The condition that **holds when the system is sustainable**. The
        violation is its negation. Stated this way (rather than as a
        violation) because it matches how the paper writes them and is
        easier to reason about at design stage.
    violation_ascii:
        ASCII negation, hand-written for clarity (rather than computed).
    variables:
        Tuple of `PaperVariable` instances appearing in the condition.
    critical_values:
        Closed-form formulas the Z3 optimization layer uses to extract
        concrete redesign thresholds.
    plain_statement:
        Two-sentence summary suitable for the verdict screen header.
    why_it_matters:
        One-paragraph explanation of why a violation is a real failure.
        Rendered by the webapp on the verdict detail screen and linked
        from each elicitation question that feeds the condition.
    real_world_signal:
        One-paragraph description of what a system designer or operator
        would observe in the wild when this failure mode triggers.
        Concrete enough to be recognizable (case-study language is fine).
    design_knobs:
        Tuple of plain-language design levers the user can move to
        satisfy the condition. Each entry references the IR field path
        and the human-readable knob name. Used by the verdict's "what
        you can change" section.
    elicitation_questions:
        Tuple of Roadmap-docx question identifiers that feed the
        variables of this condition. Example: ``("5.1", "1.7", "5.7")``.
        Used by the webapp to link the verdict back to the source
        questions and by `docs/elicitation-mapping.md` consistency
        checks.
    nfr_reweightings:
        Tuple of (NFR identifier, effect description) pairs documenting
        which non-functional-requirement declarations alter how this
        condition is evaluated. Empty tuple if the FM is NFR-neutral.
    config_keys:
        Tuple of `VerifierConfig` keys whose values control this
        condition's threshold(s). These are the dials that move when
        the user supplies a custom config.
    """

    fm_id: str
    name: str
    paper_section: str
    paper_equations: tuple[str, ...]
    sustainability_latex: str
    sustainability_ascii: str
    violation_ascii: str
    variables: tuple[PaperVariable, ...]
    critical_values: tuple[CriticalValueFormula, ...]
    plain_statement: str
    why_it_matters: str
    real_world_signal: str
    design_knobs: tuple[tuple[str, str], ...]  # (ir_field_path, human_label)
    elicitation_questions: tuple[str, ...]
    nfr_reweightings: tuple[tuple[str, str], ...] = ()
    config_keys: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Variable registry
# ---------------------------------------------------------------------------
#
# Variables defined once and referenced from every condition that uses them.
# Keeping the definitions central guarantees a variable's domain, paper
# citation, and elicitation hook stay consistent across FMs.


_E_t = PaperVariable(
    symbol="E(t)",
    name="emission rate",
    description=(
        "Tokens minted per period as a function of time, derived from the "
        "emission trigger (when minting fires) and the emission function "
        "(how many tokens per firing)."
    ),
    domain="ℝ_{≥0}",
    units="tokens/period",
    paper_section="§3.1",
    elicitation_field="tokens[].emission_rules",
    derivation_source="tokens[].emission_rules.function × tokens[].emission_rules.trigger.event_frequency",
)

_B_t = PaperVariable(
    symbol="B(t)",
    name="burn rate",
    description=(
        "Tokens permanently destroyed per period. Demand-driven burn "
        "tracks redemption events; rule-driven burn runs on a schedule."
    ),
    domain="ℝ_{≥0}",
    units="tokens/period",
    paper_section="§3.3",
    elicitation_field="tokens[].burn_rules",
    derivation_source="tokens[].burn_rules.function × tokens[].burn_rules.trigger.event_frequency",
)

_M_t = PaperVariable(
    symbol="M(t)",
    name="circulating supply",
    description="Total tokens in circulation at time t.",
    domain="ℝ_{≥0}",
    units="tokens",
    paper_section="§3.1",
    elicitation_field=None,
    derivation_source="cumulative integral of E(t) − B(t) plus initial distribution",
)

_g_t = PaperVariable(
    symbol="g(t)",
    name="participant growth rate",
    description=(
        "Rate at which the participant base is growing, as a function of "
        "time. May be negative if participants leave."
    ),
    domain="ℝ",
    units="1/period",
    paper_section="§3.3",
    elicitation_field="participants.growth_g",
)

_V = PaperVariable(
    symbol="V",
    name="token velocity",
    description=(
        "Average number of times a unit of token changes hands per period. "
        "Bounded below by 1/τ̄ via Jensen's inequality."
    ),
    domain="ℝ_{>0}",
    units="1/period",
    paper_section="§3.2",
    derivation_source="participants.agent_types[].expected_holding_time, balance_share",
)

_tau_bar = PaperVariable(
    symbol="τ̄",
    name="wealth-weighted average holding time",
    description=(
        "Σ_i (M_i / M) · E_i[τ]  — the average period a unit of token is "
        "held, weighted by who holds the most. Drives velocity from below."
    ),
    domain="ℝ_{>0}",
    units="periods",
    paper_section="§3.2",
    derivation_source="participants.agent_types[].expected_holding_time, balance_share",
)

_Q = PaperVariable(
    symbol="Q",
    name="expected transaction volume",
    description=(
        "Number of token exchanges or redemption events the system processes "
        "per period."
    ),
    domain="ℝ_{≥0}",
    units="transactions/period",
    paper_section="§3.1",
    elicitation_field="participants.expected_Q",
)

_N = PaperVariable(
    symbol="N",
    name="participant count",
    description="Number of registered participants in the system.",
    domain="ℕ_{≥1}",
    units="participants",
    paper_section="§3.5",
    elicitation_field="participants.count_N",
)

_K = PaperVariable(
    symbol="K",
    name="offer variety",
    description=(
        "Number of distinct redemption opportunities (goods, services, or "
        "exchange types) participants can spend tokens on."
    ),
    domain="ℕ_{≥1}",
    units="offers",
    paper_section="§3.4",
    elicitation_field="tokens[].offer_variety_K",
)

_d = PaperVariable(
    symbol="d",
    name="average demand per participant",
    description="Redemption events the typical participant wants per period.",
    domain="ℝ_{≥0}",
    units="redemptions/(participant·period)",
    paper_section="§3.4",
    elicitation_field="participants.average_demand_d",
)

_phi = PaperVariable(
    symbol="φ",
    name="active contributor rate",
    description=(
        "Fraction of participants whose role makes them net contributors "
        "(rather than consumers or pure observers)."
    ),
    domain="[0, 1]",
    units="fraction",
    paper_section="§3.4",
    derivation_source="participants.agent_types[] with role=contributor",
)

_gamma = PaperVariable(
    symbol="γ",
    name="monitoring capacity",
    description=(
        "Probability of detecting a non-compliant participant per period. "
        "Driven by the contribution-verification mechanism in use."
    ),
    domain="[0, 1]",
    units="probability/period",
    paper_section="§3.4",
    elicitation_field="governance.monitoring_capacity_gamma",
    derivation_source="tokens[].contribution_verification (Phase 2 elicitation)",
)

_S = PaperVariable(
    symbol="S",
    name="sanction magnitude (normalized)",
    description=(
        "Normalized severity of the penalty applied to a detected "
        "non-compliant actor. 0 means no penalty; 1 means the maximum "
        "penalty possible (typically exclusion)."
    ),
    domain="[0, 1]",
    units="normalized",
    paper_section="§3.4",
    elicitation_field="governance.sanction_structure",
    derivation_source="governance.sanction_structure.kind",
)

_T_minus_R = PaperVariable(
    symbol="T − R",
    name="temptation gap (normalized)",
    description=(
        "Normalized difference between the payoff a defector can extract "
        "(T) and the reward a cooperator earns (R). Larger gap = stronger "
        "incentive to defect."
    ),
    domain="[0, 1]",
    units="normalized",
    paper_section="§3.4",
    derivation_source="(verification, redemption mechanism) — Phase 2 elicitation",
)

_Gamma = PaperVariable(
    symbol="Γ",
    name="centralization index",
    description=(
        "Fraction of governance decisions controlled unilaterally by a "
        "single entity or small committee. 0 = full distribution; 1 = "
        "fully centralized."
    ),
    domain="[0, 1]",
    units="fraction",
    paper_section="§3.6",
    elicitation_field="governance.rule_structure",
    derivation_source="governance.rule_structure (count unilateral / count total)",
)

_Gini = PaperVariable(
    symbol="G",
    name="token-balance Gini coefficient",
    description=(
        "Inequality of token holdings across participants. High Gini in a "
        "token-vote DAO produces effective single-actor control even when "
        "Γ is nominally low."
    ),
    domain="[0, 1]",
    units="fraction",
    paper_section="§3.6",
    elicitation_field="governance.token_balance_gini",
)


# ---------------------------------------------------------------------------
# The six conditions
# ---------------------------------------------------------------------------


FM1 = PaperCondition(
    fm_id="FM1",
    name="Token Oversupply / Inflation Spiral",
    paper_section="§3.1",
    paper_equations=("eq. (5)", "eq. (7)", "eq. (8)"),
    sustainability_latex=r"\dot{M}/M + \dot{V}/V \le \dot{Q}/Q",
    sustainability_ascii="Ė/M + V̇/V ≤ Q̇/Q",
    violation_ascii="Ė/M + V̇/V > Q̇/Q   (equivalently, design-stage: E > P·Q/V)",
    variables=(_E_t, _B_t, _M_t, _V, _Q),
    critical_values=(
        CriticalValueFormula(
            parameter="E",
            formula_latex=r"E^* = P \cdot Q / V",
            formula_ascii="E* = P·Q / V   (Fisher-equation consistent emission rate)",
            direction="<=",
            explanation=(
                "The maximum emission rate the system can sustain at price "
                "level P, transaction volume Q, and velocity V without "
                "structural inflationary pressure. Any emission rate "
                "strictly above E* triggers the inflation spiral."
            ),
        ),
    ),
    plain_statement=(
        "Token supply is growing faster than the productive activity it "
        "denominates. Each unit of token buys progressively less, and "
        "rational holders accelerate spending, amplifying the imbalance."
    ),
    why_it_matters=(
        "Token-economy designers commonly fix an emission schedule first "
        "and only later check whether the productive base can absorb it. "
        "This condition catches the mismatch at design time: even before "
        "the system runs, we can show that the declared emission rate is "
        "structurally incompatible with the declared transaction volume "
        "and velocity. The user's headline diagnostic is whether their "
        "emission falls below the Fisher-equation consistent rate E*."
    ),
    real_world_signal=(
        "Holders shorten holding times; merchants raise token-denominated "
        "prices; the unit-of-account function degrades. Late-stage "
        "manifestation is hyperinflationary loops — the spiral the FM is "
        "named for."
    ),
    design_knobs=(
        ("tokens[].emission_rules", "lower emission rate or tighten its asymptotic class"),
        ("tokens[].burn_rules", "introduce or strengthen a burn mechanism"),
        ("participants.expected_Q", "grow the productive base / transaction volume"),
    ),
    elicitation_questions=("2.2", "2.3", "5.2", "5.5", "5.6"),
    config_keys=(),
)

FM2 = PaperCondition(
    fm_id="FM2",
    name="Token Velocity Trap",
    paper_section="§3.2",
    paper_equations=("eq. (9)", "eq. (10)", "eq. (11)", "eq. (12)"),
    sustainability_latex=r"\bar{\tau} > \tau_{\text{ceiling}}",
    sustainability_ascii="τ̄ > τ_ceiling   (where τ_ceiling = config.tau_bar_velocity_trap_ceiling)",
    violation_ascii="τ̄ ≤ τ_ceiling   (paper: τ̄ → 1; we use a configurable conservative ceiling)",
    variables=(_tau_bar, _V),
    critical_values=(
        CriticalValueFormula(
            parameter="tau_bar",
            formula_latex=r"\bar{\tau}^* = \tau_{\text{ceiling}}",
            formula_ascii="τ̄* = τ_ceiling   (the configurable threshold separating trap from non-trap)",
            direction=">=",
            explanation=(
                "The wealth-weighted holding time at which the system "
                "transitions out of the velocity trap. Per-agent holding "
                "times that drag τ̄ below τ_ceiling indicate the trap is "
                "active."
            ),
        ),
    ),
    plain_statement=(
        "Holders spend tokens essentially as soon as they receive them, "
        "driving velocity to its theoretical maximum. Any oversupply "
        "pressure is amplified by the high turnover; tokens function as "
        "transient receipts rather than as a store of value."
    ),
    why_it_matters=(
        "A token with no structural reason to be held collapses to a "
        "transient medium of exchange. The FM is the dual to FM1: where "
        "FM1 is about supply-side inflation, FM2 is about demand-side "
        "refusal to hold. The two together form a reinforcing pair — "
        "high velocity drives oversupply visibility, oversupply drives "
        "spend-fast behaviour."
    ),
    real_world_signal=(
        "Average holding time falls toward one period; coupons get "
        "redeemed at receipt; staking participation is low or absent; "
        "the token's price (if external markets exist) tracks emission "
        "with no smoothing."
    ),
    design_knobs=(
        ("tokens[].holding_incentives", "add governance, staking, tiered redemption, or time-locked rewards"),
        ("tokens[].function", "extend beyond pure medium-of-exchange (add governance or access right)"),
        ("participants.agent_types[].expected_holding_time", "reweight agent-type composition toward longer holders"),
    ),
    elicitation_questions=("1.1", "1.4", "5.5", "5.6"),
    nfr_reweightings=(
        (
            "NFR6 = circulate_fast",
            "Velocity trap is reclassified PASS_AS_INTENDED rather than FAIL — "
            "the user has declared high circulation a design goal.",
        ),
    ),
    config_keys=("tau_bar_velocity_trap_ceiling",),
)

FM3 = PaperCondition(
    fm_id="FM3",
    name="Burn / Emission Imbalance",
    paper_section="§3.3",
    paper_equations=("eq. (13)", "eq. (14)", "eq. (15)", "eq. (16)"),
    sustainability_latex=r"E(t) - B(t) \le g(t) \cdot M(t)",
    sustainability_ascii="E(t) − B(t) ≤ g(t) · M(t)   (equivalently ρ = B/E ≥ ρ_floor under zero growth)",
    violation_ascii="E(t) − B(t) > g(t) · M(t)   (or ρ < 1 in the steady-state form)",
    variables=(_E_t, _B_t, _M_t, _g_t),
    critical_values=(
        CriticalValueFormula(
            parameter="rho",
            formula_latex=r"\rho^* = \rho_{\text{floor}}",
            formula_ascii="ρ* = ρ_floor   (configurable; paper default: 1)",
            direction=">=",
            explanation=(
                "The burn-coverage ratio at which supply growth matches "
                "or undershoots participant growth. ρ = 1 is the steady-"
                "state floor under zero population growth; with positive "
                "growth, ρ may dip slightly below 1 and remain sustainable."
            ),
        ),
        CriticalValueFormula(
            parameter="B",
            formula_latex=r"B^* = E - g \cdot M",
            formula_ascii="B* = E − g·M   (boundary burn rate at which the inequality just holds)",
            direction=">=",
            explanation=(
                "Given the declared emission rate E and growth rate g·M, "
                "the minimum burn rate B that keeps net supply growth on "
                "track. Designers can read this directly: if your declared "
                "burn falls below B*, the system has structural "
                "inflationary pressure."
            ),
        ),
    ),
    plain_statement=(
        "Tokens are minted faster than they are destroyed (or than the "
        "participant base grows to absorb them). Without a corrective "
        "burn mechanism — ideally one tied to real consumption — supply "
        "drift accumulates without bound."
    ),
    why_it_matters=(
        "FM3 is the headline structural diagnostic for community token "
        "economies. The paper distinguishes demand-driven burn (B "
        "responds to redemption volume) from rule-driven burn (B runs on "
        "a fixed schedule); only demand-driven burn keeps ρ stable as "
        "the system scales. A no-burn design fails this condition by "
        "definition; a rule-driven burn design typically fails as soon "
        "as growth deviates from the originally assumed trajectory."
    ),
    real_world_signal=(
        "Total token supply grows monotonically while the population "
        "stagnates. The Bitcoin and Curve case studies are the canonical "
        "examples: no burn pathway, supply-side imbalance is structural."
    ),
    design_knobs=(
        ("tokens[].burn_rules", "add demand-driven burn (tie burn to redemption events)"),
        ("tokens[].redemption_mechanism", "switch to a redemption type that supports demand-driven burn"),
        ("tokens[].emission_rules", "lower the emission rate or its growth class"),
    ),
    elicitation_questions=("2.2", "3.1", "3.2", "3.3", "5.4"),
    config_keys=("rho_burn_coverage_floor",),
)

FM4 = PaperCondition(
    fm_id="FM4",
    name="Free-Rider Collapse",
    paper_section="§3.4",
    paper_equations=("eq. (17)", "eq. (18)"),
    sustainability_latex=(
        r"\varphi \ge d / K \;\wedge\; \gamma \cdot S > T - R"
    ),
    sustainability_ascii="φ ≥ d/K   AND   γ·S > T − R",
    violation_ascii="φ < d/K   OR   γ·S ≤ T − R",
    variables=(_phi, _d, _K, _gamma, _S, _T_minus_R),
    critical_values=(
        CriticalValueFormula(
            parameter="gamma",
            formula_latex=r"\gamma^* = (T - R) / S",
            formula_ascii="γ* = (T − R) / S",
            direction=">=",
            explanation=(
                "The minimum monitoring capacity at which the expected "
                "cost of cheating (γ·S) exceeds the gross gain (T − R). "
                "Below γ*, no realistic sanction will deter free-riding; "
                "the user must adopt a stronger contribution-verification "
                "mechanism or close the temptation gap."
            ),
        ),
        CriticalValueFormula(
            parameter="K",
            formula_latex=r"K^* = d / \varphi",
            formula_ascii="K* = d / φ",
            direction=">=",
            explanation=(
                "The minimum offer variety at which the active contributor "
                "rate φ suffices to satisfy demand d. Below K*, demand "
                "concentrates on too few offer types and the system runs "
                "out of contributors."
            ),
        ),
        CriticalValueFormula(
            parameter="phi",
            formula_latex=r"\varphi^* = d / K",
            formula_ascii="φ* = d / K",
            direction=">=",
            explanation=(
                "The minimum contributor fraction needed to satisfy demand "
                "given the declared offer variety. If declared agent-type "
                "fractions place φ below φ*, the system structurally "
                "lacks contributors."
            ),
        ),
    ),
    plain_statement=(
        "Either the system has too few contributors to satisfy demand "
        "(φ < d/K) or it cannot make defection costly enough to deter it "
        "(γ·S ≤ T − R). Both branches starve the system of cooperators."
    ),
    why_it_matters=(
        "FM4 is the Ostrom condition operationalized for token economies. "
        "It captures two canonical pathologies: structural undersupply "
        "of contributions, and inadequate monitoring of free-riding. "
        "Most community-token failures in the case-study record involve "
        "at least one branch of FM4, often both. The condition is "
        "particularly sensitive to elicitation quality — γ is hard for "
        "users to estimate directly, which is why the verifier derives "
        "it from the structured contribution-verification choice (Phase "
        "2)."
    ),
    real_world_signal=(
        "Either the catalog of offers regularly runs dry on the "
        "contributor side (sign of φ < d/K), or contributions visibly "
        "collapse as participants discover they can free-ride without "
        "consequence (sign of γ·S ≤ T − R). The two manifest "
        "differently and warrant different fixes — the verifier's "
        "binding-constraint output tells the user which branch failed."
    ),
    design_knobs=(
        ("tokens[].offer_variety_K", "raise K to lower d/K"),
        ("tokens[].contribution_verification", "adopt a stronger verification mechanism (raises γ)"),
        ("governance.sanction_structure", "raise S (graduated sanctions or exclusion)"),
        ("participants.agent_types[].role", "reweight composition toward contributor roles (raises φ)"),
    ),
    elicitation_questions=("1.5", "1.7", "4.4", "4.5", "5.7"),
    nfr_reweightings=(
        (
            "NFR5 = high proportionality",
            "Tightens the contributor-rate condition: a high proportionality "
            "declaration forbids passing FM4 by accident on a system with "
            "weak verification.",
        ),
    ),
    config_keys=(
        "default_temptation_gap_normalized",
        "sanction_kind_to_S_normalized",
    ),
)

FM5 = PaperCondition(
    fm_id="FM5",
    name="Insufficient Critical Mass",
    paper_section="§3.5",
    paper_equations=("eq. (19)", "eq. (20)", "eq. (21)"),
    sustainability_latex=r"N \ge 2 \cdot K \cdot d + 1",
    sustainability_ascii="N ≥ 2·K·d + 1   (well-mixed; conservative upper bound under structured topologies)",
    violation_ascii="N < 2·K·d + 1",
    variables=(_N, _K, _d),
    critical_values=(
        CriticalValueFormula(
            parameter="N",
            formula_latex=r"N^* = 2 K d + 1",
            formula_ascii="N* = 2·K·d + 1",
            direction=">=",
            explanation=(
                "Minimum participant count for which the well-mixed "
                "double-coincidence-of-wants condition is satisfied. For "
                "spatially structured or networked topologies this is a "
                "conservative upper bound — local reciprocity may sustain "
                "exchange below it."
            ),
        ),
        CriticalValueFormula(
            parameter="K",
            formula_latex=r"K^* = (N - 1) / (2 d)",
            formula_ascii="K* = (N − 1) / (2·d)",
            direction="<=",
            explanation=(
                "Maximum offer variety the declared participant count can "
                "support. Above K*, demand spreads too thin across offer "
                "types and matches become improbable."
            ),
        ),
    ),
    plain_statement=(
        "The system has too few participants to sustain liquid exchange "
        "given its offer variety and demand intensity. Match probability "
        "is too low for tokens to function as a working medium of "
        "exchange."
    ),
    why_it_matters=(
        "FM5 is the network-effects floor: below a population threshold "
        "that depends jointly on offer variety K and per-participant "
        "demand d, the system cannot self-sustain. The condition is the "
        "primary diagnostic for early-stage community-token deployments "
        "and for niche markets where K is large relative to N."
    ),
    real_world_signal=(
        "Participants report 'I have tokens but nothing to spend them "
        "on'; merchant inventories accumulate unsold listings; weekly "
        "redemption rates fall below the demand declaration. These are "
        "the hallmarks of below-critical-mass operation."
    ),
    design_knobs=(
        ("participants.count_N", "grow N above 2·K·d + 1 before launch"),
        ("tokens[].offer_variety_K", "lower K (concentrate demand on fewer offer types)"),
        ("participants.average_demand_d", "lower per-participant demand expectations"),
        ("participants.topology", "adopt spatial structure to leverage local reciprocity"),
    ),
    elicitation_questions=("1.7", "5.1", "5.7", "5.8"),
    config_keys=(),
)

FM6 = PaperCondition(
    fm_id="FM6",
    name="Governance Capture",
    paper_section="§3.6",
    paper_equations=("eq. (22)",),
    sustainability_latex=r"\Gamma \le \Gamma_{\text{threshold}}",
    sustainability_ascii="Γ ≤ Γ_threshold   (paper default Γ_threshold = 0.5)",
    violation_ascii=(
        "Γ > Γ_threshold   OR   G > G_secondary_threshold "
        "(secondary signal via concentrated token balances)"
    ),
    variables=(_Gamma, _Gini),
    critical_values=(
        CriticalValueFormula(
            parameter="Gamma",
            formula_latex=r"\Gamma^* = \Gamma_{\text{threshold}}",
            formula_ascii="Γ* = Γ_threshold   (configurable; paper default: 0.5)",
            direction="<=",
            explanation=(
                "The maximum centralization fraction at which the system "
                "still qualifies as distributed governance. Above Γ*, "
                "decision authority concentrates enough that the FM6 "
                "capture condition triggers."
            ),
        ),
        CriticalValueFormula(
            parameter="n_demote",
            formula_latex=r"n_{\text{demote}}^* = \lfloor T/2 \rfloor + 1 - U",
            formula_ascii="n_demote* = floor(total/2) + 1 − unilateral",
            direction=">=",
            explanation=(
                "The minimum number of currently-unilateral decisions "
                "that must be moved to token-holder-vote or "
                "smart-contract control to bring Γ to or below Γ*. This "
                "is what the verdict screen renders as the actionable "
                "redesign instruction."
            ),
        ),
    ),
    plain_statement=(
        "Governance authority concentrates in a single entity or small "
        "committee, or token holdings concentrate enough to grant "
        "effective single-actor control. Adaptive response to emerging "
        "imbalances is structurally compromised."
    ),
    why_it_matters=(
        "FM6 evaluates the system's capacity to *adapt* — to change "
        "rules in response to FM1–FM5 stress signals. A system with high "
        "Γ has the levers but lacks the social legitimacy to use them; "
        "a system with low Γ but high token Gini has the legitimacy but "
        "lacks the lever (because the votes themselves are concentrated). "
        "The paper treats both channels as facets of the same failure "
        "mode."
    ),
    real_world_signal=(
        "Governance proposals pass with the same small group of voters "
        "every cycle; emergency parameter changes are made unilaterally; "
        "concentrated token holders (whales, vote-aggregators like "
        "Convex) determine outcomes."
    ),
    design_knobs=(
        ("governance.rule_structure", "demote unilateral decisions to votes or smart-contract automation"),
        ("governance.token_balance_gini", "flatten ownership distribution (vote caps, quadratic voting)"),
        ("governance.type", "shift from centralized/committee toward DAO or hybrid"),
    ),
    elicitation_questions=("4.1", "4.2", "4.3"),
    nfr_reweightings=(
        (
            "NFR7 = indefinite (centralized governance is appropriate)",
            "FM6 is reclassified PASS_AS_INTENDED rather than FAIL when "
            "governance.type = centralized — the user has declared the "
            "design intent matches the structural finding.",
        ),
    ),
    config_keys=("gamma_capture_threshold", "gini_secondary_threshold"),
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


ALL_CONDITIONS: Mapping[str, PaperCondition] = {
    "FM1": FM1,
    "FM2": FM2,
    "FM3": FM3,
    "FM4": FM4,
    "FM5": FM5,
    "FM6": FM6,
}


def get_condition(fm_id: str) -> PaperCondition:
    """Return the PaperCondition for a given FM identifier.

    Raises KeyError if `fm_id` is not one of FM1..FM6.
    """
    return ALL_CONDITIONS[fm_id]


def variables_used() -> set[str]:
    """Return the set of variable symbols used by any condition."""
    out: set[str] = set()
    for cond in ALL_CONDITIONS.values():
        for v in cond.variables:
            out.add(v.symbol)
    return out
