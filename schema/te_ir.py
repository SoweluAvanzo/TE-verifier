"""Token Economy Intermediate Representation (TE-IR).

Pydantic v2 models implementing the schema sketched in docs/architecture.md.
This is the single canonical data structure shared between the questionnaire
frontend, the verifier backends, and the simulation fallback.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Primitive types
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NumberRange(_Frozen):
    """A closed interval [min, max]. Use min == max for a known point value."""

    min: float
    max: float

    @model_validator(mode="after")
    def _check_order(self) -> "NumberRange":
        if self.min > self.max:
            raise ValueError(f"NumberRange min={self.min} > max={self.max}")
        return self

    @classmethod
    def point(cls, value: float) -> "NumberRange":
        return cls(min=value, max=value)

    @property
    def is_point(self) -> bool:
        return self.min == self.max

    @property
    def midpoint(self) -> float:
        return (self.min + self.max) / 2


class Bounds(_Frozen):
    """Asymptotic bounds for the bounded_range family."""

    min: float
    max: float


# ---------------------------------------------------------------------------
# Asymptotic classes
# ---------------------------------------------------------------------------


class AsymptoticFamily(str, Enum):
    CONSTANT = "constant"
    BOUNDED_RANGE = "bounded_range"
    LINEAR = "linear"
    POLYNOMIAL = "polynomial"
    # Sub-linear power-of-time: rate ≈ a · t^(1/degree) + b. degree=2
    # gives the canonical √t shape used by Ethereum's PoS issuance curve
    # (issuance per validator scales with √(total stake)). degree=3 is
    # cube-root, useful for very-slowly-growing-with-time emission.
    SUBLINEAR_ROOT = "sublinear_root"
    LOG = "log"
    EXPONENTIAL = "exponential"
    UNSPECIFIED = "unspecified"


class AsymptoticClass(_Frozen):
    """Describes how a function grows over time, ignoring exact constants."""

    family: AsymptoticFamily
    degree: int | None = None
    bounds: Bounds | None = None
    parameter_ranges: dict[str, NumberRange] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_consistency(self) -> "AsymptoticClass":
        if self.family == AsymptoticFamily.POLYNOMIAL and self.degree is None:
            raise ValueError("polynomial family requires degree")
        if self.family == AsymptoticFamily.BOUNDED_RANGE and self.bounds is None:
            raise ValueError("bounded_range family requires bounds")
        if self.family == AsymptoticFamily.SUBLINEAR_ROOT:
            if self.degree is None:
                raise ValueError("sublinear_root family requires degree")
            if self.degree < 2:
                raise ValueError("sublinear_root requires degree ≥ 2 (degree=2 → √t)")
        return self


# ---------------------------------------------------------------------------
# Tokens, rules, triggers
# ---------------------------------------------------------------------------


class TokenFunction(str, Enum):
    MEDIUM_OF_EXCHANGE = "medium_of_exchange"
    UNIT_OF_ACCOUNT = "unit_of_account"
    GOVERNANCE_RIGHT = "governance_right"
    ACCESS_RIGHT = "access_right"
    STORE_OF_VALUE = "store_of_value"
    REPUTATION_MARKER = "reputation_marker"


class ValueAnchor(str, Enum):
    NONE = "none"
    PHYSICAL_QUANTITY = "physical_quantity"
    MARKET_PRICE = "market_price"
    PEGGED = "pegged"
    SERVICE_OR_ACCESS_UNIT = "service_or_access_unit"  # Roadmap docx 1.3 fifth option


class EmissionTriggerKind(str, Enum):
    NONE = "none"
    TIME_BASED = "time_based"
    BEHAVIORAL_EVENT = "behavioral_event"
    PHYSICAL_RESOURCE_FLOW = "physical_resource_flow"
    ALGORITHMIC = "algorithmic"


class BurnTriggerKind(str, Enum):
    NONE = "none"
    DEMAND_DRIVEN = "demand_driven"  # behavioral event tied to consumption
    RULE_DRIVEN = "rule_driven"  # time-based or scheduled
    THRESHOLD_DRIVEN = "threshold_driven"  # supply exceeds target
    EXPIRY = "expiry"
    COUPON_LAYER_ONLY = "coupon_layer_only"  # Roadmap docx 3.1 fifth option


class TokenEarningMechanism(str, Enum):
    """How participants obtain tokens (Roadmap docx 1.2)."""

    AIRDROP = "airdrop"
    BEHAVIORAL_REWARD = "behavioral_reward"
    RESOURCE_CONTRIBUTION = "resource_contribution"
    EXCHANGE_PURCHASE = "exchange_purchase"
    ALGORITHMIC_ISSUANCE = "algorithmic_issuance"


class HoldingIncentiveMechanism(str, Enum):
    """Reasons to hold rather than spend (Roadmap docx 1.4).

    Multi-select. The IR's `Token.holding_incentives` is a list of these.
    A token may have several mechanisms (e.g. governance + staking).
    """

    NONE = "none"
    TIERED_REDEMPTION = "tiered_redemption"
    GOVERNANCE_RIGHTS = "governance_rights"
    STAKING = "staking"
    REPUTATION = "reputation"
    TIME_LOCKED_REWARDS = "time_locked_rewards"


class ContributionVerification(str, Enum):
    """How the system confirms a contribution before issuing tokens
    (Roadmap docx 1.5). Maps onto FM4 monitoring capacity γ via the
    elicitation layer (`verifier.elicitation.gamma_range_from`)."""

    PHYSICAL_PRESENCE = "physical_presence"
    PEER_VERIFICATION = "peer_verification"
    SMART_CONTRACT_AUTOMATION = "smart_contract_automation"
    SELF_REPORTING = "self_reporting"
    THIRD_PARTY_CERTIFICATION = "third_party_certification"
    UNSPECIFIED = "unspecified"


class RedemptionMechanism(str, Enum):
    """How tokens are spent or exchanged (Roadmap docx 1.6).

    Drives FM3 burn-pathway feasibility and FM4/FM5 matching difficulty
    via coherence checks in the elicitation layer.
    """

    SPECIFIC_GOODS_OR_SERVICES = "specific_goods_or_services"
    TIME_BASED_BORROWING = "time_based_borrowing"
    FUNGIBLE_ACCESS = "fungible_access"
    OPEN_MARKET_EXCHANGE = "open_market_exchange"
    PEER_TO_PEER_TRANSFER = "peer_to_peer_transfer"
    UNSPECIFIED = "unspecified"


class AgentRole(str, Enum):
    """Role of an agent type. Replaces the FM4 keyword-matching heuristic
    with an explicit declaration. The contributor share φ is computed by
    summing fractions of agents whose role is `CONTRIBUTOR`.
    """

    CONTRIBUTOR = "contributor"  # net producers of value
    CONSUMER = "consumer"  # net consumers
    GOVERNANCE_ONLY = "governance_only"  # vote but neither produce nor consume
    OBSERVER = "observer"  # passive holders / speculators
    UNSPECIFIED = "unspecified"


class FunctionSign(str, Enum):
    ALWAYS_POSITIVE = "always_positive"
    ALWAYS_NEGATIVE = "always_negative"
    THRESHOLD_POSITIVE = "threshold_positive"
    DECREASING_POSITIVE = "decreasing_positive"


class ThresholdOp(str, Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="


class ThresholdVar(str, Enum):
    """Named scalars a `ThresholdCondition` can compare against.

    Each maps to a value (or range) the verifier reads from the IR;
    see `verifier.conditions._var_bounds`. Unrecognized names cause
    the condition to be treated conservatively (EVER-satisfied).
    """

    T = "t"  # elapsed periods within the verification horizon (default 52)
    M = "M"  # circulating supply at horizon (currently treated unbounded)
    Q = "Q"  # transaction volume per period
    N = "N"  # participant count
    K = "K"  # offer variety (aggregated across tokens)
    D = "d"  # average demand per participant


class ThresholdCondition(_Frozen):
    """A scalar threshold predicate over a named system variable.

    Example: ``ThresholdCondition(var=ThresholdVar.T, op=ThresholdOp.LTE, value=30.0)``
    encodes "this rule applies for the first 30 periods only".
    """

    type: Literal["threshold"] = "threshold"
    var: ThresholdVar
    op: ThresholdOp
    value: float


class TimeWindow(_Frozen):
    """A rule is active only during ``[start_period, end_period]``.

    ``end_period = None`` means open-ended (rule active from
    `start_period` to the horizon).
    """

    type: Literal["time_window"] = "time_window"
    start_period: float = 0.0
    end_period: float | None = None


class EventOccurrence(_Frozen):
    """A rule is active iff a specific source event exists in the IR.

    The verifier looks up `source_token` in `te.tokens` and checks
    that any of its emission_rules has a matching `source_event`
    (matched against the rule's free-text trigger.event_predicate or
    `RuleTrigger.kind.value`). When `source_token` is missing, the
    condition is NEVER-satisfied.
    """

    type: Literal["event_occurrence"] = "event_occurrence"
    source_token: str
    source_event: str


Condition = Annotated[
    Union[ThresholdCondition, TimeWindow, EventOccurrence],
    Field(discriminator="type"),
]


class RuleTrigger(_Frozen):
    """When a Rule fires."""

    kind: EmissionTriggerKind | BurnTriggerKind
    event_predicate: str | None = None
    event_frequency: AsymptoticClass | None = None
    # Phase B2 — structured conditions. The rule contributes its rate
    # only when all conditions hold (AND). Static 3-valued evaluation
    # in `verifier.conditions`. Empty list = always active (default).
    conditions: list[Condition] = Field(default_factory=list)


class DistributionSpec(_Frozen):
    """A stochastic envelope around an otherwise deterministic value.

    The verifier interprets a distribution as its *support* (μ ± 3σ
    for Normal, full range for Uniform, etc.) and reasons over the
    resulting range conservatively. The simulator (``verifier.abm``)
    uses the distribution proper — sampling per period or per agent.
    The two layers stay honest about what they each see.

    ``kind`` selects the family; ``parameters`` is family-specific
    so we don't proliferate sibling classes.

    Per-family parameter contract (validated below):

    * ``uniform``:    ``low``, ``high``
    * ``normal``:     ``mu``, ``sigma``
    * ``lognormal``:  ``mu``, ``sigma``  (parameters of the log)
    * ``bernoulli``:  ``p``
    * ``poisson``:    ``lambda``
    * ``beta``:       ``alpha``, ``beta``

    Schema-level mirror of ``schema.te_ir_v2.DistributionSpec`` so the
    v1 ABM can read the same field. The v2 migration shim treats this
    as a passthrough.
    """

    kind: Literal[
        "uniform",
        "normal",
        "lognormal",
        "bernoulli",
        "poisson",
        "beta",
    ]
    parameters: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self) -> "DistributionSpec":
        expected = {
            "uniform": {"low", "high"},
            "normal": {"mu", "sigma"},
            "lognormal": {"mu", "sigma"},
            "bernoulli": {"p"},
            "poisson": {"lambda"},
            "beta": {"alpha", "beta"},
        }[self.kind]
        missing = expected - self.parameters.keys()
        if missing:
            raise ValueError(
                f"distribution {self.kind} missing parameters: "
                f"{sorted(missing)}"
            )
        return self


class FunctionShape(_Frozen):
    """The (sign, asymptotic_class) classification of a Rule's function.

    When ``distribution`` is set, the ABM samples the per-period rate
    from that distribution each period (turns the rule from a
    once-per-run static sample into a noisy time-evolving rate). The
    verifier sees only the support (μ±3σ for Normal, full range for
    Uniform), so its reasoning is unchanged.
    """

    sign: FunctionSign
    asymptotic_class: AsymptoticClass
    distribution: DistributionSpec | None = None


class RegimeSwitch(_Frozen):
    """A piecewise change in function behavior above a threshold."""

    predicate: str
    function: FunctionShape


class ScheduleModifiers(_Frozen):
    """Optional schedule refinements layered on top of a Rule's base
    asymptotic class. Each field is independent; absent / default
    values mean "no modifier of this kind". Composes with the existing
    asymptotic class without changing it.

    Captures real-world emission patterns the asymptotic-class
    abstraction can't express directly:

    - ``supply_cap`` — cumulative-emission ceiling. Once ``Σ E(t) ≥
      supply_cap``, the rule emits 0 for all subsequent periods.
      Captures Bitcoin's 21M total cap.
    - ``halving_period`` + ``halving_factor`` — every ``halving_period``
      periods, multiply the per-period rate by ``halving_factor``.
      Defaults to 0.5 (halving). Set ``halving_factor=0.9`` for a
      gentler 10%-per-period decay; ``halving_factor=0.5`` and
      ``halving_period=210`` reproduces Bitcoin's halving schedule.
    - ``vesting_periods`` — linear ramp from 0 at t=0 to nominal rate
      at t=vesting_periods. Captures DAO grant-style allocations.

    The verifier's trajectory simulation uses all three; the static
    layer uses ``supply_cap`` (the easy one) and treats halving via a
    horizon-averaged rate reduction. ``vesting`` is currently
    trajectory-only.
    """

    supply_cap: float | None = None
    halving_period: int | None = None
    halving_factor: float = 0.5
    # Number of periods that have *already elapsed* since the last
    # halving event when t=0. Lets users align the simulation with
    # real-world calendar time without re-stating the entire schedule.
    # Bitcoin example: ~110 weeks elapsed since the April-2024 halving
    # by mid-2026, so the next modeled halving fires at t = 208 - 110 = 98.
    halving_offset: int = 0
    vesting_periods: int | None = None

    @field_validator("halving_factor")
    @classmethod
    def _validate_factor(cls, v: float) -> float:
        if not (0.0 < v < 1.0):
            raise ValueError("halving_factor must be strictly between 0 and 1")
        return v

    @field_validator("supply_cap")
    @classmethod
    def _validate_cap(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("supply_cap must be positive")
        return v

    @field_validator("halving_period")
    @classmethod
    def _validate_period(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("halving_period must be ≥ 1")
        return v

    @field_validator("vesting_periods")
    @classmethod
    def _validate_vesting(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("vesting_periods must be ≥ 1")
        return v

    @field_validator("halving_offset")
    @classmethod
    def _validate_halving_offset(cls, v: int) -> int:
        if v < 0:
            raise ValueError("halving_offset must be ≥ 0")
        return v


class Rule(_Frozen):
    """A mint or burn rule. Used for both emission and burn."""

    trigger: RuleTrigger
    function: FunctionShape
    regimes: list[RegimeSwitch] = Field(default_factory=list)
    # Optional schedule modifiers (Sprint "richer specs"). When None,
    # the rule behaves exactly as before — pure asymptotic-class.
    schedule: ScheduleModifiers | None = None


class InitialDistributionKind(str, Enum):
    NONE = "none"
    WELCOME_ALLOCATION = "welcome_allocation"
    PRE_MINTED_RESERVE = "pre_minted_reserve"
    FOUNDER_ALLOCATION = "founder_allocation"


class InitialDistribution(_Frozen):
    kind: InitialDistributionKind
    amount: NumberRange | None = None
    notes: str | None = None


class Token(_Frozen):
    id: str
    function: list[TokenFunction]
    value_anchor: ValueAnchor = ValueAnchor.NONE
    transferable: bool = True
    # Phase 2: holding_incentives is the multi-select replacement for the
    # boolean below. The boolean is preserved as a back-compat shim — when
    # legacy YAMLs set holding_incentive_present=True, the model_validator
    # populates `holding_incentives = [GOVERNANCE_RIGHTS]` so existing FM2
    # logic continues to behave identically.
    holding_incentive_present: bool = False
    holding_incentives: list[HoldingIncentiveMechanism] = Field(default_factory=list)
    earning_mechanisms: list[TokenEarningMechanism] = Field(default_factory=list)
    contribution_verification: ContributionVerification | None = None
    redemption_mechanism: RedemptionMechanism | None = None
    emission_rules: list[Rule] = Field(default_factory=list)
    burn_rules: list[Rule] = Field(default_factory=list)
    initial_distribution: InitialDistribution = InitialDistribution(
        kind=InitialDistributionKind.NONE
    )
    # Per-token offer variety K (number of distinct redemption opportunities)
    offer_variety_K: NumberRange | None = None

    @field_validator("function")
    @classmethod
    def _at_least_one_function(cls, v: list[TokenFunction]) -> list[TokenFunction]:
        if not v:
            raise ValueError("token must declare at least one function")
        return v

    @model_validator(mode="after")
    def _backcompat_holding_incentives(self) -> "Token":
        """Map legacy `holding_incentive_present=True` onto the new list.

        If the user supplied no `holding_incentives` list but did set
        the legacy boolean, populate the list with a sensible default
        (`GOVERNANCE_RIGHTS` — strong incentive, common shape) so the
        Phase 2 elicitation derivation can still operate.
        """
        if self.holding_incentive_present and not self.holding_incentives:
            object.__setattr__(
                self,
                "holding_incentives",
                [HoldingIncentiveMechanism.GOVERNANCE_RIGHTS],
            )
        elif self.holding_incentives and not self.holding_incentive_present:
            non_none = any(
                hi != HoldingIncentiveMechanism.NONE
                for hi in self.holding_incentives
            )
            if non_none:
                object.__setattr__(self, "holding_incentive_present", True)
        return self


# ---------------------------------------------------------------------------
# Cross-token flows
# ---------------------------------------------------------------------------


class CrossTokenAction(str, Enum):
    MINT = "mint"
    BURN = "burn"
    TRANSFER = "transfer"


class FlowCoupling(str, Enum):
    """How a cross-token flow's per-period rate is determined.

    - INDEPENDENT (default, back-compat): the flow's `amount` is an
      independent AsymptoticClass; its per-period rate is computed in
      isolation via `verifier.asymptotic.average_rate_per_period`.
    - PROPORTIONAL_TO_SOURCE: the flow's per-period rate is
      `coupling_ratio × E_own(source_token)`, where E_own is the source
      token's per-period rate from its own emission_rules (no
      transitive cross-token contributions, so cycles are impossible).
      This captures patterns like MakerDAO's "stability fees on DAI
      drive proportional MKR buyback-and-burn".
    """

    INDEPENDENT = "independent"
    PROPORTIONAL_TO_SOURCE = "proportional_to_source"


class CrossTokenFlow(_Frozen):
    source_token: str
    source_event: str
    target_token: str
    target_action: CrossTokenAction
    amount: AsymptoticClass
    coupling: FlowCoupling = FlowCoupling.INDEPENDENT
    # Required when coupling = PROPORTIONAL_TO_SOURCE. Range of the
    # multiplier `r` such that flow_rate = r × E_own(source). Otherwise
    # ignored (kept None).
    coupling_ratio: NumberRange | None = None

    @model_validator(mode="after")
    def _validate_coupling(self) -> "CrossTokenFlow":
        if self.coupling == FlowCoupling.PROPORTIONAL_TO_SOURCE:
            if self.coupling_ratio is None:
                raise ValueError(
                    "coupling=proportional_to_source requires coupling_ratio"
                )
        return self


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


class Topology(str, Enum):
    WELL_MIXED = "well_mixed"
    SPATIAL = "spatial"
    NETWORK = "network"


class HoldingTimeDistribution(_Frozen):
    """Expected token holding time for an agent type, in periods.

    A 'period' is the time unit used for emission and exchange rates
    (typically a week, but the IR is unit-agnostic). The verifier uses
    this to compute wealth-weighted velocity for FM2.
    """

    expected_periods: NumberRange


class AgentType(_Frozen):
    id: str
    fraction: float = Field(ge=0.0, le=1.0)
    expected_holding_time: HoldingTimeDistribution
    balance_share: float | None = Field(default=None, ge=0.0, le=1.0)
    utility_hint: str | None = None
    # Phase 2: explicit role declaration replaces FM4's keyword-matching
    # heuristic. When None, the legacy keyword-match on `id` and
    # `utility_hint` is still used as a fallback (back-compat).
    role: AgentRole | None = None


class ParticipantsSpec(_Frozen):
    count_N: NumberRange
    # Token-volume transacted per period (NOT transaction count). FM1's
    # Fisher-equation check `(E - B) ≤ Q` is dimensional in tokens, so
    # this field must be expressed in token-flux terms — for a $1 stable
    # this is also dollars/period, but for ETH/BTC convert from
    # $-volume by dividing by token price. The field name is preserved
    # for back-compat with existing IR files; treat it as Q in MV=PQ
    # under V=P=1 normalization.
    expected_Q: NumberRange
    average_demand_d: NumberRange  # redemption events per participant per period
    growth_g: AsymptoticClass  # population growth class
    # Default: NETWORK. Real crypto economies are network-structured
    # (DEX pairs, social graphs, validator P2P, lock-and-vote DAOs).
    # The well-mixed assumption is rarely true and produces a
    # needlessly conservative `N ≥ 2Kd + 1` threshold. When NETWORK
    # is selected without an explicit average_degree in topology_params,
    # FM5 derives one from log(N) — see ``FM5CriticalMass``.
    topology: Topology = Topology.NETWORK
    agent_types: list[AgentType] = Field(default_factory=list)
    average_activity_frequency: NumberRange | None = None
    # Phase 5c: topology-specific parameters. For `topology = network`,
    # the recognized key is `average_degree` (NumberRange). Used by FM5
    # to apply a degree-corrected critical-mass threshold.
    topology_params: dict[str, NumberRange] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _agent_fractions(self) -> "ParticipantsSpec":
        if self.agent_types:
            total = sum(a.fraction for a in self.agent_types)
            if not (0.99 <= total <= 1.01):
                raise ValueError(
                    f"agent_type fractions must sum to ~1.0, got {total}"
                )
        return self


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


class GovernanceType(str, Enum):
    CENTRALIZED = "centralized"
    COMMITTEE = "committee"
    DAO = "dao"
    ALGORITHMIC = "algorithmic"
    HYBRID = "hybrid"


class ControllingActor(str, Enum):
    """Who can take a given governance action.

    Semantic note for FM6 (governance capture):

    - ``SINGLE_ENTITY`` — one party with unilateral authority. Always
      counted as unilateral in Γ.
    - ``COMMITTEE`` — a group with internal voting / multisig
      consensus (e.g. Bitcoin core devs by rough consensus, multisig
      treasuries, EIP process). **Not** counted as unilateral in Γ
      because internal vote dynamics distribute control. Use this for
      the common real-world case.
    - ``COMMITTEE_TRUSTED`` — a small trusted group acting without
      internal voting (e.g. a foundation board that ratifies decisions
      by fiat). Counted as unilateral in Γ. Use this only when the
      committee genuinely acts as a single actor.
    - ``TOKEN_HOLDER_VOTE`` — on-chain governance. Not unilateral.
    - ``SMART_CONTRACT`` — automated, no human discretion. Not
      unilateral.
    - ``NOT_ADJUSTABLE`` — protocol parameter fixed at deployment.
    """

    SINGLE_ENTITY = "single_entity"
    COMMITTEE = "committee"
    COMMITTEE_TRUSTED = "committee_trusted"
    TOKEN_HOLDER_VOTE = "token_holder_vote"
    SMART_CONTRACT = "smart_contract"
    NOT_ADJUSTABLE = "not_adjustable"


class SanctionKind(str, Enum):
    NONE = "none"
    WARNING = "warning"
    TOKEN_PENALTY = "token_penalty"
    EXCLUSION = "exclusion"
    GRADUATED = "graduated"
    ECONOMIC = "economic"  # e.g. PoW slashing, stake loss


class SanctionStructure(_Frozen):
    """Sanction magnitude S used in FM4 monitoring condition γS > T - R.

    `S_normalized` is on [0, 1] where 1 represents a sanction equal to or
    larger than the maximum temptation payoff. Defaults shown derive from
    Ostrom's design principle 5 (graduated sanctions) and are mapped from
    the qualitative `kind` if `S_normalized` is not set.
    """

    kind: SanctionKind
    S_normalized: NumberRange | None = None


class VoteWeighting(str, Enum):
    """How votes are weighted in token-holder governance (FM6 input).

    The token-balance Gini alone is a crude proxy for effective voting
    concentration. Real DAOs use mechanisms that *transform* the token
    distribution into a voting distribution: quadratic voting (sqrt
    scaling), vote caps (clipping), time-locking (veCRV), delegation,
    and reputation-weighted models. FM6 reads ``vote_weighting`` and
    adjusts the effective concentration accordingly.

    Variants:

    * ``LINEAR`` — 1 token = 1 vote. Effective Gini = token Gini.
      The default; matches pre-fix behavior for back-compat.
    * ``QUADRATIC`` — vote ≈ √(tokens). Effective Gini ≈ 0.5–0.7 × G
      (calibrated approximation; see ``VerifierConfig``).
    * ``CAPPED`` — max votes per address. Requires
      ``vote_weighting_params['cap_fraction']`` ∈ (0, 1].
    * ``TIME_LOCKED`` — veCRV / veToken pattern. Vote weight scales
      with locked-time fraction. Requires
      ``vote_weighting_params['avg_lock_fraction']`` ∈ [0, 1].
    * ``DELEGATED`` — token holders delegate to a smaller set. The
      effective concentration is over delegates, not holders. Requires
      ``vote_weighting_params['delegate_concentration_gini']``.
    * ``REPUTATION_WEIGHTED`` — non-token (Optimism Citizen House,
      reputation-DAOs). Requires ``vote_weighting_params['reputation_gini']``.
      If not provided, FM6's secondary signal is INCONCLUSIVE (token
      Gini doesn't apply).
    """

    LINEAR = "linear"
    QUADRATIC = "quadratic"
    CAPPED = "capped"
    TIME_LOCKED = "time_locked"
    DELEGATED = "delegated"
    REPUTATION_WEIGHTED = "reputation_weighted"


class GovernanceSpec(_Frozen):
    type: GovernanceType
    rule_structure: dict[str, ControllingActor] = Field(default_factory=dict)
    monitoring_capacity_gamma: NumberRange = NumberRange.point(0.5)
    sanction_structure: SanctionStructure = SanctionStructure(
        kind=SanctionKind.WARNING
    )
    token_balance_gini: NumberRange | None = None  # secondary FM6 signal
    # FM6 vote-weighting (audit fix #1, expanded form). LINEAR (default)
    # preserves pre-fix behavior: effective Gini = token Gini directly.
    # Other variants transform the Gini per the calibration in
    # ``VerifierConfig.vote_weighting_gini_adjustment``.
    vote_weighting: VoteWeighting = VoteWeighting.LINEAR
    # Parameters required by non-LINEAR weightings. Recognized keys:
    #   cap_fraction (CAPPED)
    #   avg_lock_fraction (TIME_LOCKED)
    #   delegate_concentration_gini (DELEGATED)
    #   reputation_gini (REPUTATION_WEIGHTED)
    vote_weighting_params: dict[str, NumberRange] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Non-functional requirements
# ---------------------------------------------------------------------------


class CirculationSpeed(str, Enum):
    CIRCULATE_FAST = "circulate_fast"
    BALANCED = "balanced"
    RETAIN_VALUE = "retain_value"


class GovernanceMaturity(str, Enum):
    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    INDEFINITE = "indefinite"


class NFRs(_Frozen):
    resilience: int = Field(default=3, ge=1, le=5)
    adaptability: int = Field(default=3, ge=1, le=5)
    accessibility: int = Field(default=3, ge=1, le=5)
    transparency: int = Field(default=3, ge=1, le=5)
    proportionality: int = Field(default=3, ge=1, le=5)
    circulation_speed: CirculationSpeed = CirculationSpeed.BALANCED
    governance_maturity: GovernanceMaturity = GovernanceMaturity.MEDIUM_TERM


class Archetype(str, Enum):
    NATIVE_PROTOCOL_ASSET = "native_protocol_asset"
    STABLECOIN = "stablecoin"
    GOVERNANCE_UTILITY_PAIR = "governance_utility_pair"
    PLAY_TO_EARN_DUAL = "play_to_earn_dual"
    COMMUNITY_REWARD = "community_reward"
    OTHER = "other"


class Meta(_Frozen):
    name: str
    description: str | None = None
    archetype: Archetype = Archetype.OTHER
    nfrs: NFRs = NFRs()
    # Trajectory simulation horizon, in periods. None → use the default
    # (260 periods ≈ 5 years of weekly periods). Cap-bound or
    # slowly-decaying systems (Bitcoin's 21M, Curve's 3.03B) need a
    # longer horizon for the cap to bind in the simulation. Bounded
    # to [1, 10000] to keep the forward-Euler loop fast in pure Python.
    simulation_horizon: int | None = Field(default=None, ge=1, le=10000)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class TokenEconomy(_Frozen):
    meta: Meta
    tokens: list[Token]
    participants: ParticipantsSpec
    governance: GovernanceSpec
    cross_token_flows: list[CrossTokenFlow] = Field(default_factory=list)

    @field_validator("tokens")
    @classmethod
    def _at_least_one_token(cls, v: list[Token]) -> list[Token]:
        if not v:
            raise ValueError("TE must declare at least one token")
        ids = [t.id for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError("token ids must be unique")
        return v

    def get_token(self, token_id: str) -> Token:
        for t in self.tokens:
            if t.id == token_id:
                return t
        raise KeyError(token_id)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_te(path: str | Path) -> TokenEconomy:
    """Load a TE-IR from a YAML file.

    The YAML structure mirrors the Pydantic models. Validation errors point
    to the offending field with full path.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    return TokenEconomy.model_validate(raw)
