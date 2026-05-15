"""schema/te_ir_v2.py — Redesigned TE-IR (Phase A of the v2 migration).

Status: opt-in. The live verifier and the five existing example YAMLs
continue to use v1 (`schema/te_ir.py`). v2 is exposed via the `schema.v2`
sub-namespace and consumed only by explicitly opted-in code:

    from schema import v2
    te = v2.load_te_v2("examples/bitcoin_v2.yaml")   # native v2 YAML
    te2 = v2.from_v1(v1_te)                          # migrate a v1 IR

The plan is to roll out v2 incrementally: this module defines the schema,
`from_v1` migrates v1 IRs mechanically, and downstream consumers (FM
checkers, simulator) will be moved one at a time. Until then v1 remains
authoritative.

Companion documents:

- ``docs/architecture.md`` — long-term system vision.
- ``docs/case-studies.md`` — five public economies encoded against v1.
- ``docs/redesign-plan.md`` — phase ledger of the v1 implementation.

What changes vs. v1
-------------------

* **Events become first-class** with structured triggers, AND/OR
  composition, stochastic firing, and DAG-validated causality.
* **Functions are unified and phaseable.** Token emission rules, token
  burn rules, good-supply rules, cross-token flows, and exchange rates
  all use one type (``Function``) with the same phase / schedule / limit
  machinery. v1's ``Rule.regimes`` is promoted from a half-supported
  afterthought to the load-bearing primitive.
* **Asymptotic classes get richer.** ``SUBLINEAR_ROOT`` (already in v1),
  plus ``LOGISTIC`` and ``POWER`` for bonding-curve and S-curve designs.
* **Goods and redemptions are first-class.** A bipartite token / real
  economy. ``expected_Q`` and ``offer_variety_K`` become *derived* from
  good supply and redemption count, with the explicit values kept as
  optional overrides.
* **Stochasticity is declarable but verifier-conservative.** Any rate
  or rule can carry a ``DistributionSpec``; the verifier reasons over
  support (μ ± 3σ for Normal, full range for Uniform), the simulator
  uses the distribution proper.
* **Agents carry structured utility weights** (not the v1
  ``utility_hint: str``). Defaults derive from role; the user overrides
  when needed.
* **References are a small DSL.** ``M[CRV]``, ``goods_supply[shoes]``,
  ``N``, ``Q``, ``phi``, ``t``, ``fraction[scholar]``. Used by event
  triggers, condition predicates, and state-driven exchange rates —
  one language reused everywhere.

What is intentionally NOT here
------------------------------

* Engine implementations (FM checkers, simulator, optimizer).
* Migration of the five example YAMLs.
* The CLI / webapp surface adjustments.

These come after the schema is agreed.

Migration
---------

The bottom of this file sketches ``from_v1`` — a back-compat shim that
maps a current ``TokenEconomy`` into the v2 shape. The mapping is
mechanical and preserves every v1 behavior. The shim lets us run the
existing FMs against v2 IRs during the transition.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Foundations
# =============================================================================


class _Frozen(BaseModel):
    """All schema nodes are frozen + extra='forbid' for safety."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NumberRange(_Frozen):
    """A closed interval ``[min, max]``. ``min == max`` for a known point."""

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
    def midpoint(self) -> float:
        return (self.min + self.max) / 2


# =============================================================================
# Reference DSL
# =============================================================================
#
# A Reference is a structured pointer to a named scalar variable in the
# IR. Used by:
#   - Conditions (LHS / RHS of a threshold predicate)
#   - State-driven Function and ExchangeRate phases
#   - Event triggers and actions
#
# The same lookup table feeds the verifier (Z3 encoding) and the
# simulator (per-period evaluation). Keeping one Reference type across
# all consumers prevents the language from forking.


class TokenSupplyRef(_Frozen):
    type: Literal["token_supply"] = "token_supply"
    token_id: str  # references Token.id


class GoodSupplyRef(_Frozen):
    type: Literal["good_supply"] = "good_supply"
    good_id: str  # references Good.id


class ParticipantCountRef(_Frozen):
    type: Literal["N"] = "N"


class TransactionVolumeRef(_Frozen):
    """Aggregate transacted token-volume per period. When goods are
    declared, this is *derived* (Σ_g supply(g) × price(g)); when not,
    it falls back to ``participants.expected_Q_override``."""

    type: Literal["Q"] = "Q"


class ContributorFractionRef(_Frozen):
    """φ — sum of fractions of agent types with role=CONTRIBUTOR."""

    type: Literal["phi"] = "phi"


class TimeRef(_Frozen):
    """Elapsed periods within the verification / simulation horizon."""

    type: Literal["t"] = "t"


class AgentFractionRef(_Frozen):
    """Fraction of the population belonging to a specific agent type."""

    type: Literal["agent_fraction"] = "agent_fraction"
    agent_type_id: str


class LiteralValue(_Frozen):
    """A user-supplied constant — RHS of threshold predicates, etc."""

    type: Literal["literal"] = "literal"
    value: float


Reference = Annotated[
    Union[
        TokenSupplyRef,
        GoodSupplyRef,
        ParticipantCountRef,
        TransactionVolumeRef,
        ContributorFractionRef,
        TimeRef,
        AgentFractionRef,
        LiteralValue,
    ],
    Field(discriminator="type"),
]


# =============================================================================
# Distributions
# =============================================================================


class DistributionSpec(_Frozen):
    """A stochastic envelope around an otherwise deterministic value.

    The verifier interprets a distribution as its *support* (μ ± 3σ for
    Normal, full range for Uniform, etc.) and reasons over the resulting
    range conservatively. The simulator uses the distribution proper —
    sampling per period or per agent. The two layers stay honest about
    what they each see.

    ``kind`` selects the family; ``parameters`` is family-specific
    (validated below) so we don't proliferate sibling classes.
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
                f"distribution {self.kind} missing parameters: {sorted(missing)}"
            )
        return self


# =============================================================================
# Conditions
# =============================================================================
#
# Conditions are evaluable predicates. Used by Function phases,
# ExchangeRate phases, Event triggers, Redemption eligibility, and
# (via Conjunction / Disjunction) by anything that wants to compose
# them.
#
# The verifier evaluates conditions 3-valued (TRUE / FALSE / UNKNOWN)
# under the open-box semantics of v1's `verifier/conditions.py`. The
# simulator evaluates them concretely per period.


class ThresholdOp(str, Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="


class ThresholdCondition(_Frozen):
    """Compare two references with a relational operator.

    Generalizes v1's ``ThresholdCondition`` (which compared a named
    variable to a constant) by letting both sides be ``Reference``
    expressions — so ``M[CRV] > M[veCRV]`` is now expressible without
    encoding the relation as a special case.
    """

    type: Literal["threshold"] = "threshold"
    lhs: Reference
    op: ThresholdOp
    rhs: Reference


class TimeWindow(_Frozen):
    """The rule / event is active during ``[start_period, end_period]``.

    ``end_period = None`` means open-ended (active to horizon).
    Compatible with v1's ``TimeWindow``.
    """

    type: Literal["time_window"] = "time_window"
    start_period: float = 0.0
    end_period: float | None = None


class EventOccurrence(_Frozen):
    """Holds iff the referenced event has fired at least once.

    Replaces v1's free-text event matching. The reference is by event
    id, validated at schema-load to exist in ``TokenEconomyV2.events``.
    """

    type: Literal["event_occurrence"] = "event_occurrence"
    event_id: str


class Conjunction(_Frozen):
    """Logical AND over child conditions. Children must be Conditions."""

    type: Literal["and"] = "and"
    children: list["Condition"]


class Disjunction(_Frozen):
    """Logical OR over child conditions."""

    type: Literal["or"] = "or"
    children: list["Condition"]


class Negation(_Frozen):
    """Logical NOT of a child condition."""

    type: Literal["not"] = "not"
    child: "Condition"


class StochasticCondition(_Frozen):
    """Fires probabilistically each period per the given distribution.

    Verifier semantics: treat as nondeterministic — the condition MAY
    hold at any period, MAY NOT hold. Worst-case reasoning takes both
    branches. Simulator semantics: sample per period and evaluate
    concretely.

    Useful for: random shocks, exogenous attack arrivals, agent
    behavioral noise.
    """

    type: Literal["stochastic"] = "stochastic"
    distribution: DistributionSpec  # typically Bernoulli(p) for per-period firing


Condition = Annotated[
    Union[
        ThresholdCondition,
        TimeWindow,
        EventOccurrence,
        Conjunction,
        Disjunction,
        Negation,
        StochasticCondition,
    ],
    Field(discriminator="type"),
]

Conjunction.model_rebuild()
Disjunction.model_rebuild()
Negation.model_rebuild()


# Convenience: the "always true" condition (open-ended time window).
def Always() -> Condition:  # noqa: N802
    return TimeWindow(start_period=0.0, end_period=None)


# =============================================================================
# Asymptotic classes
# =============================================================================


class AsymptoticFamily(str, Enum):
    CONSTANT = "constant"
    BOUNDED_RANGE = "bounded_range"
    LINEAR = "linear"
    # POLYNOMIAL with negative degree expresses x·y=k-style bonding curves.
    POLYNOMIAL = "polynomial"
    SUBLINEAR_ROOT = "sublinear_root"
    LOG = "log"
    EXPONENTIAL = "exponential"
    # NEW in v2 — motivated by exchange rates and population growth curves.
    LOGISTIC = "logistic"  # L / (1 + exp(-k·(t − t₀)))
    POWER = "power"  # a · x^w, with `w` ∈ R (weighted bonding curves)
    UNSPECIFIED = "unspecified"


class Bounds(_Frozen):
    min: float
    max: float


class AsymptoticClass(_Frozen):
    """Describes how a quantity scales with its argument.

    The argument can be ``t`` (for time-driven functions) or any
    ``Reference`` (for state-driven functions). The asymptotic class
    is *family + parameter ranges* — the verifier reasons about the
    family symbolically; the simulator evaluates pointwise at parameter
    midpoints.
    """

    family: AsymptoticFamily
    # Required for POLYNOMIAL (positive or negative int), SUBLINEAR_ROOT (≥ 2).
    degree: int | None = None
    # Required for BOUNDED_RANGE.
    bounds: Bounds | None = None
    # Free-form parameter ranges keyed by family-specific names.
    # See conventions in verifier/asymptotic.py docstring.
    parameter_ranges: dict[str, NumberRange] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "AsymptoticClass":
        if self.family == AsymptoticFamily.POLYNOMIAL and self.degree is None:
            raise ValueError("polynomial requires degree (may be negative)")
        if self.family == AsymptoticFamily.SUBLINEAR_ROOT:
            if self.degree is None or self.degree < 2:
                raise ValueError("sublinear_root requires degree ≥ 2")
        if self.family == AsymptoticFamily.BOUNDED_RANGE and self.bounds is None:
            raise ValueError("bounded_range requires bounds")
        # LOGISTIC and POWER have family-specific param-range expectations,
        # checked by a separate validator at the consuming layer.
        return self


# =============================================================================
# Function shape, limits, schedule, phases — the unified phaseable function
# =============================================================================


class FunctionSign(str, Enum):
    ALWAYS_POSITIVE = "always_positive"
    ALWAYS_NEGATIVE = "always_negative"
    THRESHOLD_POSITIVE = "threshold_positive"
    DECREASING_POSITIVE = "decreasing_positive"


class FunctionShape(_Frozen):
    """Asymptotic class + optional stochastic envelope on the magnitude.

    Deprecated: ``sign``. Retained for back-compat; defaults to
    ``always_positive``. Mint = non-negative rate intrinsically; the
    shape of the curve is captured by family + signed coefficients.
    """

    asymptotic_class: AsymptoticClass
    sign: FunctionSign = FunctionSign.ALWAYS_POSITIVE
    # Stochastic noise around the class's deterministic value. Verifier
    # reasons over support; simulator samples.
    distribution: DistributionSpec | None = None


class RateLimit(_Frozen):
    """Caps, floors, and user-marked inflection points.

    Applied per-phase (``Phase.limit``) or globally (``Function.global_limit``,
    ``ExchangeRate.global_limit``). When both are set, the global limit
    is the final clamp.

    ``inflection_at`` are user hints — predicates marking where the
    curve's behavior qualitatively changes. The verifier can split its
    reachability analysis on these without re-deriving them from
    nonlinear math. If omitted, the verifier just doesn't split.

    Example: ``inflection_at=[ThresholdCondition(GoodSupplyRef('shoes'),
    GT, LiteralValue(10000))]`` marks "behavior changes above 10k units".
    """

    cap: float | None = None
    floor: float | None = None
    inflection_at: list["Condition"] = Field(default_factory=list)


class ScheduleModifiers(_Frozen):
    """Schedule refinements (carry-over from v1, lightly extended).

    Captures real-world patterns the asymptotic class can't express
    directly: supply cap, halving cadence, vesting ramp.
    """

    supply_cap: float | None = None
    halving_period: int | None = None
    halving_factor: float = 0.5
    # NEW in v2 (already in v1 by this point) — offset since last halving.
    halving_offset: int = 0
    vesting_periods: int | None = None

    @field_validator("halving_factor")
    @classmethod
    def _factor(cls, v: float) -> float:
        if not (0.0 < v < 1.0):
            raise ValueError("halving_factor must be strictly between 0 and 1")
        return v


class Phase(_Frozen):
    """A single segment of a phaseable function.

    Phases are evaluated in declaration order; the first whose
    ``condition`` holds is the active phase at that time / state. The
    last phase should have ``condition = Always()`` to guarantee
    well-definedness — validated at TokenEconomy level.

    ``id`` is required when the phase is the target of an Event's
    ``SetPhase`` action. For phases that are never event-targeted, an
    id is optional. Referencing by id (not index) lets users add or
    reorder phases without silently breaking event wiring.
    """

    id: str | None = None
    condition: Condition
    shape: FunctionShape
    limit: RateLimit | None = None


class EmissionTriggerKind(str, Enum):
    """Carried over from v1 so FM4's pattern-matching on
    BEHAVIORAL_EVENT / PHYSICAL_RESOURCE_FLOW continues to work."""

    NONE = "none"
    TIME_BASED = "time_based"
    BEHAVIORAL_EVENT = "behavioral_event"
    PHYSICAL_RESOURCE_FLOW = "physical_resource_flow"
    ALGORITHMIC = "algorithmic"


class BurnTriggerKind(str, Enum):
    NONE = "none"
    DEMAND_DRIVEN = "demand_driven"
    RULE_DRIVEN = "rule_driven"
    THRESHOLD_DRIVEN = "threshold_driven"
    EXPIRY = "expiry"
    COUPON_LAYER_ONLY = "coupon_layer_only"


# Union of trigger kinds for typed Function.trigger_kind. The direction
# (mint vs burn) is determined by where the Function lives — under
# Token.emission_rules vs Token.burn_rules — so no separate `direction`
# field is needed.
TriggerKind = Union[EmissionTriggerKind, BurnTriggerKind]


class FunctionDriver(str, Enum):
    """What the function is a function *of*.

    - ``TIME`` — rate is f(t). Most token emission / burn schedules.
    - ``EVENT`` — rate is f(t) × event_frequency(t). v1's "per-event"
      pattern. Total per-period rate is multiplied through.
    - ``STATE`` — rate is f(of_variable). Bonding curves, demand-driven
      burn (function of Q), and any rate that depends on another IR
      variable.
    - ``CONSTANT`` — degenerate driver. Shape collapses to a single
      range.
    """

    TIME = "time"
    EVENT = "event"
    STATE = "state"
    CONSTANT = "constant"


class Function(_Frozen):
    """The unified phaseable function — replaces v1's ``Rule``.

    Used everywhere a per-period rate is needed: token emission and
    burn, good supply rules, cross-token flows, exchange rates. One
    type, one set of primitives.

    The ``id`` is optional and only required when an Event needs to
    reference this function (e.g. ``SetPhase(function_id=…)``).
    """

    id: str | None = None
    driver: FunctionDriver

    # For driver = EVENT:
    trigger_kind: TriggerKind | None = None
    event_predicate: str | None = None  # human-readable description
    event_frequency: AsymptoticClass | None = None

    # For driver = STATE:
    of_variable: Reference | None = None

    # The phases. Must end with an Always() phase or include a phase
    # whose condition is statically TRUE — verified at TokenEconomy load.
    phases: list[Phase]

    # Optional schedule modifiers (caps, halving, vesting).
    schedule: ScheduleModifiers | None = None

    # Global clamp applied after phase selection.
    global_limit: RateLimit | None = None

    @model_validator(mode="after")
    def _check_driver_fields(self) -> "Function":
        if self.driver == FunctionDriver.EVENT:
            if self.trigger_kind is None:
                raise ValueError("driver=event requires trigger_kind")
        if self.driver == FunctionDriver.STATE:
            if self.of_variable is None:
                raise ValueError("driver=state requires of_variable")
        if not self.phases:
            raise ValueError("Function must declare at least one phase")
        return self


# =============================================================================
# Events
# =============================================================================
#
# Events are first-class objects with a trigger Condition and a list
# of Actions. The event causality graph (Event → Action(FireEvent) →
# Event) must be a DAG, checked at TokenEconomy load.


class SetPhase(_Frozen):
    """Switch a Function to a specific phase by id.

    The verifier handles this by encoding "after the event fires, the
    Function's active phase is fixed to the phase whose id matches" —
    collapsing a phase choice into the assignment. Referencing by id
    (not index) survives phase reordering.
    """

    type: Literal["set_phase"] = "set_phase"
    function_id: str
    phase_id: str


class ScaleParameter(_Frozen):
    """Multiplicatively scale the value of a Reference target.

    Example: ``ScaleParameter(target=GoodSupplyRef(good_id='shoes'),
    factor=0.5)`` halves the shoe supply. ``one_shot`` distinguishes a
    one-time application from a persistent multiplier that applies
    every period after the event fires.
    """

    type: Literal["scale_parameter"] = "scale_parameter"
    target: Reference
    factor: float
    one_shot: bool = True


class FireEvent(_Frozen):
    """Cascade — trigger another event. Causality graph must be a DAG."""

    type: Literal["fire_event"] = "fire_event"
    event_id: str


Action = Annotated[
    Union[SetPhase, ScaleParameter, FireEvent],
    Field(discriminator="type"),
]


class Event(_Frozen):
    id: str
    description: str | None = None
    trigger: Condition
    actions: list[Action]
    # Whether this event can fire more than once.
    repeatable: bool = False
    # Minimum periods between successive firings (only meaningful when
    # ``repeatable=True``). Verifier treats this as a lower bound on
    # inter-event spacing.
    cooldown_periods: int = 0


# =============================================================================
# Goods and redemption
# =============================================================================


class GoodSupplyKind(str, Enum):
    INFINITE = "infinite"
    """Service-like — no scarcity. Digital downloads, public APIs."""
    FIXED = "fixed"
    """A one-time mint of N units. NFTs, limited collectibles."""
    CONSUMABLE = "consumable"
    """Finite supply, consumed on redemption. Tickets, vouchers."""
    RENEWABLE = "renewable"
    """Replenished per period by supply_rules. Daily restock,
    production rates."""


class Good(_Frozen):
    id: str
    name: str
    supply_kind: GoodSupplyKind
    initial_supply: NumberRange | None = None  # required for fixed/consumable
    supply_rules: list[Function] = Field(default_factory=list)  # renewable only
    consumed_on_redemption: bool = True
    description: str | None = None

    @model_validator(mode="after")
    def _check_supply(self) -> "Good":
        kind = self.supply_kind
        if kind in (GoodSupplyKind.FIXED, GoodSupplyKind.CONSUMABLE):
            if self.initial_supply is None:
                raise ValueError(
                    f"good {self.id} supply_kind={kind.value} requires initial_supply"
                )
        if kind == GoodSupplyKind.RENEWABLE and not self.supply_rules:
            raise ValueError(
                f"good {self.id} supply_kind=renewable requires supply_rules"
            )
        if kind == GoodSupplyKind.INFINITE and self.initial_supply is not None:
            raise ValueError(
                f"good {self.id} supply_kind=infinite must not set initial_supply"
            )
        return self


class ExchangeRateDriver(str, Enum):
    """How the rate is determined within a phase."""

    CONSTANT = "constant"
    TIME = "time"  # f(t)
    STATE = "state"  # f(of_variable) — includes bonding curves


class ExchangeRatePhase(_Frozen):
    condition: Condition
    driver: ExchangeRateDriver
    # Required if driver = STATE. Bonding curves point at
    # GoodSupplyRef(self.good_id) — checked at TokenEconomy level.
    of_variable: Reference | None = None
    # Required if driver != CONSTANT.
    shape: AsymptoticClass | None = None
    # Required if driver = CONSTANT.
    constant_rate: NumberRange | None = None
    # Phase-local clamp.
    limit: RateLimit | None = None

    @model_validator(mode="after")
    def _check_driver_fields(self) -> "ExchangeRatePhase":
        if self.driver == ExchangeRateDriver.CONSTANT:
            if self.constant_rate is None:
                raise ValueError("driver=constant requires constant_rate")
        else:
            if self.shape is None:
                raise ValueError(f"driver={self.driver.value} requires shape")
        if self.driver == ExchangeRateDriver.STATE and self.of_variable is None:
            raise ValueError("driver=state requires of_variable")
        return self


class ExchangeRate(_Frozen):
    """Phaseable exchange rate from source token to target good.

    Uses the same Phase + RateLimit primitives as Function. Bonding
    curves are not a separate variant — they are the special case where
    a STATE-driven phase references the supply of its own good.

    Verifier strategy: each phase's reachability is determined via the
    Condition language; within each reachable phase, the rate is the
    function shape clamped by the limits. State-driven rates that
    couple back to supply are decoupled at the FM level — see
    docs/redesign/notes.md (to be written).
    """

    phases: list[ExchangeRatePhase]
    global_limit: RateLimit | None = None
    distribution: DistributionSpec | None = None


class Redemption(_Frozen):
    """Spend ``source_token`` to obtain ``target_good`` at ``exchange_rate``."""

    id: str
    source_token: str
    target_good: str
    exchange_rate: ExchangeRate
    # Eligibility predicates (e.g. "only after vesting period").
    conditions: list[Condition] = Field(default_factory=list)
    # Fraction of the source tokens paid that go to fees rather than
    # to the burn / treasury / LP. Optional in v1 of redemption; the
    # full v2 fee model (split between protocol / LP / treasury) is a
    # later addition.
    fee_fraction: NumberRange | None = None


# =============================================================================
# Tokens (slimmed down; magic K and Q fields removed in favor of derivation)
# =============================================================================


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
    SERVICE_OR_ACCESS_UNIT = "service_or_access_unit"


class HoldingIncentiveMechanism(str, Enum):
    NONE = "none"
    TIERED_REDEMPTION = "tiered_redemption"
    GOVERNANCE_RIGHTS = "governance_rights"
    STAKING = "staking"
    REPUTATION = "reputation"
    TIME_LOCKED_REWARDS = "time_locked_rewards"


class TokenEarningMechanism(str, Enum):
    AIRDROP = "airdrop"
    BEHAVIORAL_REWARD = "behavioral_reward"
    RESOURCE_CONTRIBUTION = "resource_contribution"
    EXCHANGE_PURCHASE = "exchange_purchase"
    ALGORITHMIC_ISSUANCE = "algorithmic_issuance"


class ContributionVerification(str, Enum):
    PHYSICAL_PRESENCE = "physical_presence"
    PEER_VERIFICATION = "peer_verification"
    SMART_CONTRACT_AUTOMATION = "smart_contract_automation"
    SELF_REPORTING = "self_reporting"
    THIRD_PARTY_CERTIFICATION = "third_party_certification"
    UNSPECIFIED = "unspecified"


class InitialDistributionKind(str, Enum):
    NONE = "none"
    WELCOME_ALLOCATION = "welcome_allocation"
    PRE_MINTED_RESERVE = "pre_minted_reserve"
    FOUNDER_ALLOCATION = "founder_allocation"


class InitialDistribution(_Frozen):
    kind: InitialDistributionKind
    amount: NumberRange | None = None
    notes: str | None = None


class RedemptionMechanism(str, Enum):
    """Legacy v1 enum carried over for FM4's (verification, redemption)
    temptation-gap table. v2's first-class ``Redemption`` objects
    replace it semantically; this enum survives only as the type of
    ``Token.redemption_mechanism_override`` for back-compat with v1
    IRs that don't declare explicit Redemptions yet."""

    SPECIFIC_GOODS_OR_SERVICES = "specific_goods_or_services"
    TIME_BASED_BORROWING = "time_based_borrowing"
    FUNGIBLE_ACCESS = "fungible_access"
    OPEN_MARKET_EXCHANGE = "open_market_exchange"
    PEER_TO_PEER_TRANSFER = "peer_to_peer_transfer"
    UNSPECIFIED = "unspecified"


class Token(_Frozen):
    """Token specification.

    Compared to v1:

    * ``emission_rules`` and ``burn_rules`` now hold ``Function``
      instances (the unified phaseable type).
    * ``offer_variety_K`` becomes *derived* from the count of
      ``Redemption`` rules pointing out of this token. The optional
      ``offer_variety_K_override`` preserves v1 behavior when no
      Redemptions are declared.
    * ``contribution_verification`` retained — feeds FM4 γ derivation.
    * ``redemption_mechanism`` removed as a primary field; the optional
      ``redemption_mechanism_override`` preserves v1 behavior (used by
      FM4's temptation-gap derivation) when no explicit Redemption
      rules are declared. Native v2 IRs should declare ``Redemption``
      objects instead.
    """

    id: str
    function: list[TokenFunction]
    value_anchor: ValueAnchor = ValueAnchor.NONE
    transferable: bool = True
    holding_incentives: list[HoldingIncentiveMechanism] = Field(default_factory=list)
    earning_mechanisms: list[TokenEarningMechanism] = Field(default_factory=list)
    contribution_verification: ContributionVerification | None = None
    emission_rules: list[Function] = Field(default_factory=list)
    burn_rules: list[Function] = Field(default_factory=list)
    initial_distribution: InitialDistribution = InitialDistribution(
        kind=InitialDistributionKind.NONE
    )
    # Legacy override — used when no Redemption rules point out of this
    # token. Preserves v1's per-token K semantics.
    offer_variety_K_override: NumberRange | None = None
    # Legacy override — used by FM4's (verification, redemption)
    # temptation-gap derivation when no Redemption rules are declared.
    # Native v2 IRs should declare Redemption objects instead.
    redemption_mechanism_override: RedemptionMechanism | None = None

    @field_validator("function")
    @classmethod
    def _at_least_one_function(cls, v: list[TokenFunction]) -> list[TokenFunction]:
        if not v:
            raise ValueError("token must declare at least one function")
        return v


# =============================================================================
# Cross-token flows
# =============================================================================


class CrossTokenAction(str, Enum):
    MINT = "mint"
    BURN = "burn"
    TRANSFER = "transfer"


class FlowCoupling(str, Enum):
    INDEPENDENT = "independent"
    PROPORTIONAL_TO_SOURCE = "proportional_to_source"


class CrossTokenFlow(_Frozen):
    """Inter-token flow. Same as v1 modulo the new ``Function`` shape.

    Independent flows declare their own ``amount`` Function; proportional
    flows scale with the source token's own emission rate via
    ``coupling_ratio``.
    """

    source_token: str
    source_event: str  # human-readable label
    target_token: str
    target_action: CrossTokenAction
    amount: Function  # independent flows; ignored when coupling=proportional
    coupling: FlowCoupling = FlowCoupling.INDEPENDENT
    coupling_ratio: NumberRange | None = None  # required if proportional


# =============================================================================
# Agents
# =============================================================================


class AgentRole(str, Enum):
    CONTRIBUTOR = "contributor"
    CONSUMER = "consumer"
    GOVERNANCE_ONLY = "governance_only"
    OBSERVER = "observer"
    UNSPECIFIED = "unspecified"


class HoldingTimeDistribution(_Frozen):
    expected_periods: NumberRange


class UtilityWeights(_Frozen):
    """Structured utility weights on a fixed catalog of terms.

    Each term is a *non-negative weight* on a quantity that the
    simulator computes from existing IR fields. The total agent
    utility is the weighted sum.

    The catalog is fixed (do not extend per agent type). This keeps
    the simulator's per-step utility evaluation O(catalog_size). To
    express per-agent-type preferences over specific goods, use the
    ``good_preferences`` vector below.

    Defaults derive from ``AgentType.role``:

    * CONTRIBUTOR:    income_yield=1.0, redemption_value=0.3
    * CONSUMER:       redemption_value=1.0, holding_yield=0.2
    * GOVERNANCE_ONLY:governance_payoff=1.0, holding_yield=0.5
    * OBSERVER:       risk_aversion=1.0, holding_yield=0.3
    * UNSPECIFIED:    uniform 0.25 across non-aversion terms

    When ``UtilityWeights`` is omitted from an ``AgentType``, the
    role-derived defaults are used.
    """

    income_yield: float = 0.0
    holding_yield: float = 0.0
    redemption_value: float = 0.0
    governance_payoff: float = 0.0
    social_payoff: float = 0.0
    risk_aversion: float = 0.0
    # Optional per-good preference vector. Sums (if nonzero) should be
    # ≈1; renormalized at simulation time. Goods not listed default to
    # uniform weight among them.
    good_preferences: dict[str, float] = Field(default_factory=dict)
    # Softmax temperature for stochastic action selection. β = 1/T;
    # higher T → more random, lower T → more deterministic.
    action_temperature: float = 1.0
    # Phase E1 — stochastic exit (mirror of v1 UtilityWeights).
    exit_propensity: float = Field(default=0.0, ge=0.0, le=1.0)
    social_comparison_delta: float = Field(default=0.3, ge=0.0)
    # Phase E3 — reputation feedback.
    reputation_yield: float = Field(default=0.0, ge=0.0)
    reputation_decay: float = Field(default=0.0, ge=0.0, le=1.0)


class AgentType(_Frozen):
    id: str
    fraction: float = Field(ge=0.0, le=1.0)
    expected_holding_time: HoldingTimeDistribution
    balance_share: float | None = Field(default=None, ge=0.0, le=1.0)
    role: AgentRole | None = None
    # Structured utility. None = derive from role.
    utility: UtilityWeights | None = None


# =============================================================================
# Participants, governance, NFRs, meta — minor refactors
# =============================================================================


class Topology(str, Enum):
    WELL_MIXED = "well_mixed"
    SPATIAL = "spatial"
    NETWORK = "network"


class ParticipantsSpec(_Frozen):
    count_N: NumberRange
    average_demand_d: NumberRange  # redemption events per participant per period
    growth_g: AsymptoticClass
    # Default NETWORK — see v1 docstring for rationale.
    topology: Topology = Topology.NETWORK
    agent_types: list[AgentType] = Field(default_factory=list)
    average_activity_frequency: NumberRange | None = None
    topology_params: dict[str, NumberRange] = Field(default_factory=dict)
    # Optional override of derived Q. When goods are declared, Q is
    # computed from Σ_g supply(g) × price(g). When goods are absent
    # (legacy / minimal IRs) the user must provide this directly.
    expected_Q_override: NumberRange | None = None

    @model_validator(mode="after")
    def _check_agent_fractions(self) -> "ParticipantsSpec":
        if self.agent_types:
            total = sum(a.fraction for a in self.agent_types)
            if not (0.99 <= total <= 1.01):
                raise ValueError(
                    f"agent_type fractions must sum to ~1.0, got {total}"
                )
        return self


class GovernanceType(str, Enum):
    CENTRALIZED = "centralized"
    COMMITTEE = "committee"
    DAO = "dao"
    ALGORITHMIC = "algorithmic"
    HYBRID = "hybrid"


class ControllingActor(str, Enum):
    """See v1 docstring at ``schema.te_ir.ControllingActor``. v2 mirrors
    the v1 enum value-for-value so the migration is a no-op."""

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
    ECONOMIC = "economic"


class SanctionStructure(_Frozen):
    kind: SanctionKind
    S_normalized: NumberRange | None = None


class VoteWeighting(str, Enum):
    """Mirror of v1 ``VoteWeighting``. See v1 docstring for rationale.

    Variants and required ``vote_weighting_params`` keys are identical
    to v1 so the migration is a no-op."""

    LINEAR = "linear"
    QUADRATIC = "quadratic"
    CAPPED = "capped"
    TIME_LOCKED = "time_locked"
    DELEGATED = "delegated"
    REPUTATION_WEIGHTED = "reputation_weighted"


class GovernanceSpec(_Frozen):
    type: GovernanceType
    rule_structure: dict[str, ControllingActor] = Field(default_factory=dict)
    monitoring_capacity_gamma: NumberRange = NumberRange(min=0.5, max=0.5)
    sanction_structure: SanctionStructure = SanctionStructure(kind=SanctionKind.WARNING)
    token_balance_gini: NumberRange | None = None
    # FM6 vote-weighting (audit fix #1, expanded form). LINEAR default
    # preserves pre-fix behavior. See v1 schema for variant docs.
    vote_weighting: VoteWeighting = VoteWeighting.LINEAR
    vote_weighting_params: dict[str, NumberRange] = Field(default_factory=dict)


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
    """Non-functional requirements.

    NOTE FOR V2: these no longer drive per-failure-mode verdict
    reweighting (see Point 5 of the redesign — the verifier verdicts
    become honest reachability statements without pass_as_intended /
    role-gated alternates). NFRs are retained as *design goals* the
    simulator can score outcomes against — e.g. "did the trajectory
    achieve circulate_fast for the medium-of-exchange tokens?"
    """

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
    simulation_horizon: int | None = Field(default=None, ge=1, le=10000)


# =============================================================================
# Top-level
# =============================================================================


class TokenEconomyV2(_Frozen):
    """The redesigned top-level IR.

    Validators below enforce the structural invariants the verifier and
    simulator both rely on.
    """

    meta: Meta
    tokens: list[Token]
    goods: list[Good] = Field(default_factory=list)
    redemptions: list[Redemption] = Field(default_factory=list)
    participants: ParticipantsSpec
    governance: GovernanceSpec
    cross_token_flows: list[CrossTokenFlow] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

    # -------------------------------------------------------------------------
    # Structural validators (sketched — full implementations come later).
    # -------------------------------------------------------------------------

    @field_validator("tokens")
    @classmethod
    def _unique_tokens(cls, v: list[Token]) -> list[Token]:
        ids = [t.id for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError("token ids must be unique")
        if not v:
            raise ValueError("TE must declare at least one token")
        return v

    @model_validator(mode="after")
    def _check_good_ids_unique(self) -> "TokenEconomyV2":
        ids = [g.id for g in self.goods]
        if len(ids) != len(set(ids)):
            raise ValueError("good ids must be unique")
        return self

    @model_validator(mode="after")
    def _check_redemption_refs(self) -> "TokenEconomyV2":
        """Every Redemption.source_token must exist in tokens, and every
        Redemption.target_good must exist in goods. Likewise for cross-
        token flows."""
        token_ids = {t.id for t in self.tokens}
        good_ids = {g.id for g in self.goods}
        for r in self.redemptions:
            if r.source_token not in token_ids:
                raise ValueError(
                    f"redemption {r.id} references missing token {r.source_token}"
                )
            if r.target_good not in good_ids:
                raise ValueError(
                    f"redemption {r.id} references missing good {r.target_good}"
                )
        for f in self.cross_token_flows:
            if f.source_token not in token_ids:
                raise ValueError(
                    f"cross-token flow references missing source {f.source_token}"
                )
            if f.target_token not in token_ids:
                raise ValueError(
                    f"cross-token flow references missing target {f.target_token}"
                )
        return self

    @model_validator(mode="after")
    def _check_event_dag(self) -> "TokenEconomyV2":
        """The event causality graph (Event → Action(FireEvent) → Event)
        must be a DAG. Cycles tank decidability."""
        adj: dict[str, set[str]] = {e.id: set() for e in self.events}
        for e in self.events:
            for a in e.actions:
                if isinstance(a, FireEvent):
                    if a.event_id not in adj:
                        raise ValueError(
                            f"event {e.id} fires unknown event {a.event_id}"
                        )
                    adj[e.id].add(a.event_id)
        # DFS-based cycle detection.
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {k: WHITE for k in adj}

        def dfs(u: str) -> None:
            color[u] = GRAY
            for v in adj[u]:
                if color[v] == GRAY:
                    raise ValueError(f"event cycle detected through {u}→{v}")
                if color[v] == WHITE:
                    dfs(v)
            color[u] = BLACK

        for u in list(adj):
            if color[u] == WHITE:
                dfs(u)
        return self

    @model_validator(mode="after")
    def _check_phase_default(self) -> "TokenEconomyV2":
        """Every Function and ExchangeRate must have a final phase
        whose condition is statically TRUE (typically ``Always()``).
        This is what guarantees the function is well-defined for every
        time / state.

        Sketch: the check is conservative — a TimeWindow with
        start=0 and end=None is recognized as Always; deeper analysis
        (Conjunctions reducing to TRUE) is deferred to the verifier.
        """
        def _is_default(c: Condition) -> bool:
            return (
                isinstance(c, TimeWindow)
                and c.start_period == 0.0
                and c.end_period is None
            )

        def _check_function(f: Function, where: str) -> None:
            if not _is_default(f.phases[-1].condition):
                raise ValueError(
                    f"function in {where} must end with an Always() phase"
                )

        for tok in self.tokens:
            for f in tok.emission_rules:
                _check_function(f, f"token {tok.id} emission_rules")
            for f in tok.burn_rules:
                _check_function(f, f"token {tok.id} burn_rules")
        for g in self.goods:
            for f in g.supply_rules:
                _check_function(f, f"good {g.id} supply_rules")
        for ctf in self.cross_token_flows:
            _check_function(ctf.amount, f"cross_token_flow {ctf.source_token}→{ctf.target_token}")
        for r in self.redemptions:
            if not _is_default(r.exchange_rate.phases[-1].condition):
                raise ValueError(
                    f"redemption {r.id} exchange_rate must end with Always() phase"
                )
        return self


# =============================================================================
# Back-compat shim — map v1 TokenEconomy → v2 TokenEconomyV2
# =============================================================================
#
# The shim is a pure mechanical translation. Every v1 IR produces a
# valid v2 IR with identical observable behavior under the v1 FM
# checks. The shim is what makes the migration safe:
#
#   1. Adopt the v2 schema in parallel (this file → schema/te_ir_v2.py).
#   2. Convert v1 IRs on load via from_v1.
#   3. Migrate the FM checkers one at a time to consume v2 directly.
#   4. Once all checkers are v2-native, deprecate v1 schema.
#
# This block is documented but only stubbed — full implementation
# follows after the schema is approved.


def _migrate_asymptotic_class(ac_v1: Any) -> AsymptoticClass:
    """v1 AsymptoticClass → v2. Enum names match; bounds re-wrapped."""
    bounds_v1 = getattr(ac_v1, "bounds", None)
    bounds_v2 = (
        Bounds(min=bounds_v1.min, max=bounds_v1.max) if bounds_v1 is not None else None
    )
    return AsymptoticClass(
        family=AsymptoticFamily(ac_v1.family.value),
        degree=getattr(ac_v1, "degree", None),
        bounds=bounds_v2,
        parameter_ranges={
            k: NumberRange(min=r.min, max=r.max)
            for k, r in ac_v1.parameter_ranges.items()
        },
    )


def _migrate_threshold_var(var_v1: Any) -> Reference:
    """v1 ThresholdVar → v2 Reference. The 6 v1 vars map to fixed References.

    Token-specific references (M[token_id]) are not expressible via the
    v1 ThresholdVar.M (which referenced "M" as a global scalar). We
    map the v1 M to ``TokenSupplyRef`` of the *first* token, which
    matches v1's single-supply assumption.
    """
    name = var_v1.value if hasattr(var_v1, "value") else str(var_v1)
    mapping: dict[str, Reference] = {
        "t": TimeRef(),
        "M": TokenSupplyRef(token_id="__PRIMARY__"),  # caller patches this
        "Q": TransactionVolumeRef(),
        "N": ParticipantCountRef(),
        "phi": ContributorFractionRef(),
        # v1 also has K and d — these had no Reference variants in the
        # initial v2 design. We add LiteralValue passthrough by raising
        # a clear error so the migration fails loud rather than silently.
        "K": None,
        "d": None,
    }
    ref = mapping.get(name)
    if ref is None:
        raise NotImplementedError(
            f"v1 ThresholdVar={name!r} has no Reference equivalent in v2 yet"
        )
    return ref


def _migrate_condition(cond_v1: Any, primary_token: str) -> Condition:
    """v1 Condition → v2 Condition. Only ThresholdCondition / TimeWindow /
    EventOccurrence appear in v1; the rest of the v2 condition language
    (Conjunction / Disjunction / Negation / Stochastic) has no v1 source."""
    type_name = type(cond_v1).__name__
    if type_name == "ThresholdCondition":
        lhs = _migrate_threshold_var(cond_v1.var)
        if isinstance(lhs, TokenSupplyRef) and lhs.token_id == "__PRIMARY__":
            lhs = TokenSupplyRef(token_id=primary_token)
        return ThresholdCondition(
            lhs=lhs,
            op=ThresholdOp(cond_v1.op.value),
            rhs=LiteralValue(value=cond_v1.value),
        )
    if type_name == "TimeWindow":
        return TimeWindow(
            start_period=cond_v1.start_period,
            end_period=cond_v1.end_period,
        )
    if type_name == "EventOccurrence":
        # v1's EventOccurrence referenced a (source_token, source_event)
        # pair. v2 requires an Event id. Migration synthesises an event
        # id of the form "v1:{token}:{event}". Whoever consumes the v2
        # IR must create matching Event objects (currently empty).
        return EventOccurrence(
            event_id=f"v1:{cond_v1.source_token}:{cond_v1.source_event}",
        )
    raise NotImplementedError(f"unknown v1 condition type: {type_name}")


def _migrate_schedule(sched_v1: Any) -> ScheduleModifiers | None:
    if sched_v1 is None:
        return None
    return ScheduleModifiers(
        supply_cap=sched_v1.supply_cap,
        halving_period=sched_v1.halving_period,
        halving_factor=sched_v1.halving_factor,
        halving_offset=getattr(sched_v1, "halving_offset", 0),
        vesting_periods=sched_v1.vesting_periods,
    )


def _migrate_function_shape(fn_v1: Any) -> FunctionShape:
    return FunctionShape(
        sign=FunctionSign(fn_v1.sign.value),
        asymptotic_class=_migrate_asymptotic_class(fn_v1.asymptotic_class),
        distribution=None,  # v1 had no stochastic shape declarations
    )


def _v1_trigger_to_driver(
    kind_v1: Any, is_burn: bool
) -> tuple[FunctionDriver, TriggerKind | None]:
    """Map v1 RuleTrigger.kind to (v2 driver, v2 trigger_kind)."""
    name = kind_v1.value if hasattr(kind_v1, "value") else str(kind_v1)
    if is_burn:
        burn_kind = BurnTriggerKind(name)
        if burn_kind in (BurnTriggerKind.DEMAND_DRIVEN, BurnTriggerKind.RULE_DRIVEN):
            return FunctionDriver.EVENT, burn_kind
        if burn_kind == BurnTriggerKind.THRESHOLD_DRIVEN:
            return FunctionDriver.STATE, burn_kind
        if burn_kind == BurnTriggerKind.EXPIRY:
            return FunctionDriver.TIME, burn_kind
        return FunctionDriver.TIME, burn_kind  # COUPON_LAYER_ONLY / NONE
    else:
        emit_kind = EmissionTriggerKind(name)
        if emit_kind == EmissionTriggerKind.TIME_BASED:
            return FunctionDriver.TIME, emit_kind
        if emit_kind in (
            EmissionTriggerKind.BEHAVIORAL_EVENT,
            EmissionTriggerKind.PHYSICAL_RESOURCE_FLOW,
        ):
            return FunctionDriver.EVENT, emit_kind
        if emit_kind == EmissionTriggerKind.ALGORITHMIC:
            return FunctionDriver.STATE, emit_kind
        return FunctionDriver.TIME, emit_kind  # NONE fallback


def _migrate_rule(rule_v1: Any, *, is_burn: bool, primary_token: str) -> Function:
    driver, trigger_kind = _v1_trigger_to_driver(rule_v1.trigger.kind, is_burn=is_burn)
    event_freq = (
        _migrate_asymptotic_class(rule_v1.trigger.event_frequency)
        if rule_v1.trigger.event_frequency is not None
        else None
    )
    shape = _migrate_function_shape(rule_v1.function)

    # v1 rule.trigger.conditions become a precondition on the default
    # phase. If non-empty, wrap them in a Conjunction with the Always()
    # tail kept for well-definedness.
    v1_conditions = list(getattr(rule_v1.trigger, "conditions", []))
    if v1_conditions:
        migrated = [_migrate_condition(c, primary_token) for c in v1_conditions]
        guard: Condition = (
            migrated[0] if len(migrated) == 1 else Conjunction(children=migrated)
        )
        # Zero-shape for the Always() tail when conditions don't hold:
        # an emit/burn rate of 0. Use constant 0.
        zero_shape = FunctionShape(
            sign=shape.sign,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(0.0)},
            ),
        )
        phases = [
            Phase(condition=guard, shape=shape),
            Phase(condition=Always(), shape=zero_shape),
        ]
    else:
        phases = [Phase(condition=Always(), shape=shape)]

    # v1 RegimeSwitch.predicate is free text — we cannot parse it
    # reliably without a grammar. If regimes are present we surface a
    # clear error so the migration is loud rather than silently lossy.
    if getattr(rule_v1, "regimes", None):
        raise NotImplementedError(
            "v1 Rule.regimes is free-text predicates; no automatic v2 "
            "migration. Encode multi-phase behavior directly in v2 "
            "Function.phases for this rule."
        )

    return Function(
        driver=driver,
        trigger_kind=trigger_kind,
        event_predicate=rule_v1.trigger.event_predicate,
        event_frequency=event_freq,
        phases=phases,
        schedule=_migrate_schedule(rule_v1.schedule),
    )


def _migrate_token(token_v1: Any, primary_token: str) -> Token:
    return Token(
        id=token_v1.id,
        function=[TokenFunction(f.value) for f in token_v1.function],
        value_anchor=ValueAnchor(token_v1.value_anchor.value),
        transferable=token_v1.transferable,
        holding_incentives=[
            HoldingIncentiveMechanism(hi.value) for hi in token_v1.holding_incentives
        ],
        earning_mechanisms=[
            TokenEarningMechanism(em.value) for em in token_v1.earning_mechanisms
        ],
        contribution_verification=(
            ContributionVerification(token_v1.contribution_verification.value)
            if token_v1.contribution_verification is not None
            else None
        ),
        emission_rules=[
            _migrate_rule(r, is_burn=False, primary_token=primary_token)
            for r in token_v1.emission_rules
        ],
        burn_rules=[
            _migrate_rule(r, is_burn=True, primary_token=primary_token)
            for r in token_v1.burn_rules
        ],
        initial_distribution=InitialDistribution(
            kind=InitialDistributionKind(token_v1.initial_distribution.kind.value),
            amount=(
                NumberRange(
                    min=token_v1.initial_distribution.amount.min,
                    max=token_v1.initial_distribution.amount.max,
                )
                if token_v1.initial_distribution.amount is not None
                else None
            ),
            notes=token_v1.initial_distribution.notes,
        ),
        offer_variety_K_override=(
            NumberRange(min=token_v1.offer_variety_K.min, max=token_v1.offer_variety_K.max)
            if token_v1.offer_variety_K is not None
            else None
        ),
        redemption_mechanism_override=(
            RedemptionMechanism(token_v1.redemption_mechanism.value)
            if token_v1.redemption_mechanism is not None
            else None
        ),
    )


def _migrate_agent_type(at_v1: Any) -> AgentType:
    return AgentType(
        id=at_v1.id,
        fraction=at_v1.fraction,
        expected_holding_time=HoldingTimeDistribution(
            expected_periods=NumberRange(
                min=at_v1.expected_holding_time.expected_periods.min,
                max=at_v1.expected_holding_time.expected_periods.max,
            )
        ),
        balance_share=at_v1.balance_share,
        role=AgentRole(at_v1.role.value) if at_v1.role is not None else None,
        utility=None,  # derived from role at simulation time
    )


def _migrate_cross_token_flow(ctf_v1: Any) -> CrossTokenFlow:
    amount_ac = _migrate_asymptotic_class(ctf_v1.amount)
    amount_fn = Function(
        driver=FunctionDriver.TIME,
        phases=[
            Phase(
                condition=Always(),
                shape=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=amount_ac,
                ),
            )
        ],
    )
    return CrossTokenFlow(
        source_token=ctf_v1.source_token,
        source_event=ctf_v1.source_event,
        target_token=ctf_v1.target_token,
        target_action=CrossTokenAction(ctf_v1.target_action.value),
        amount=amount_fn,
        coupling=FlowCoupling(ctf_v1.coupling.value),
        coupling_ratio=(
            NumberRange(min=ctf_v1.coupling_ratio.min, max=ctf_v1.coupling_ratio.max)
            if ctf_v1.coupling_ratio is not None
            else None
        ),
    )


def from_v1(te_v1: Any) -> TokenEconomyV2:
    """Mechanical migration from v1 TokenEconomy to v2 TokenEconomyV2.

    See the module docstring for the full mapping rule set. The
    function is intentionally strict: any v1 IR feature with no v2
    equivalent (free-text RegimeSwitch predicates, unsupported
    ThresholdVar values) raises ``NotImplementedError`` rather than
    silently dropping data.
    """
    primary_token = te_v1.tokens[0].id if te_v1.tokens else "PRIMARY"

    return TokenEconomyV2(
        meta=Meta(
            name=te_v1.meta.name,
            description=te_v1.meta.description,
            archetype=Archetype(te_v1.meta.archetype.value),
            nfrs=NFRs(
                resilience=te_v1.meta.nfrs.resilience,
                adaptability=te_v1.meta.nfrs.adaptability,
                accessibility=te_v1.meta.nfrs.accessibility,
                transparency=te_v1.meta.nfrs.transparency,
                proportionality=te_v1.meta.nfrs.proportionality,
                circulation_speed=CirculationSpeed(
                    te_v1.meta.nfrs.circulation_speed.value
                ),
                governance_maturity=GovernanceMaturity(
                    te_v1.meta.nfrs.governance_maturity.value
                ),
            ),
            simulation_horizon=getattr(te_v1.meta, "simulation_horizon", None),
        ),
        tokens=[_migrate_token(t, primary_token) for t in te_v1.tokens],
        goods=[],
        redemptions=[],
        participants=ParticipantsSpec(
            count_N=NumberRange(
                min=te_v1.participants.count_N.min,
                max=te_v1.participants.count_N.max,
            ),
            average_demand_d=NumberRange(
                min=te_v1.participants.average_demand_d.min,
                max=te_v1.participants.average_demand_d.max,
            ),
            growth_g=_migrate_asymptotic_class(te_v1.participants.growth_g),
            topology=Topology(te_v1.participants.topology.value),
            agent_types=[
                _migrate_agent_type(a) for a in te_v1.participants.agent_types
            ],
            average_activity_frequency=(
                NumberRange(
                    min=te_v1.participants.average_activity_frequency.min,
                    max=te_v1.participants.average_activity_frequency.max,
                )
                if te_v1.participants.average_activity_frequency is not None
                else None
            ),
            topology_params={
                k: NumberRange(min=r.min, max=r.max)
                for k, r in te_v1.participants.topology_params.items()
            },
            expected_Q_override=NumberRange(
                min=te_v1.participants.expected_Q.min,
                max=te_v1.participants.expected_Q.max,
            ),
        ),
        governance=GovernanceSpec(
            type=GovernanceType(te_v1.governance.type.value),
            rule_structure={
                k: ControllingActor(v.value)
                for k, v in te_v1.governance.rule_structure.items()
            },
            monitoring_capacity_gamma=NumberRange(
                min=te_v1.governance.monitoring_capacity_gamma.min,
                max=te_v1.governance.monitoring_capacity_gamma.max,
            ),
            sanction_structure=SanctionStructure(
                kind=SanctionKind(te_v1.governance.sanction_structure.kind.value),
                S_normalized=(
                    NumberRange(
                        min=te_v1.governance.sanction_structure.S_normalized.min,
                        max=te_v1.governance.sanction_structure.S_normalized.max,
                    )
                    if te_v1.governance.sanction_structure.S_normalized is not None
                    else None
                ),
            ),
            token_balance_gini=(
                NumberRange(
                    min=te_v1.governance.token_balance_gini.min,
                    max=te_v1.governance.token_balance_gini.max,
                )
                if te_v1.governance.token_balance_gini is not None
                else None
            ),
            vote_weighting=VoteWeighting(te_v1.governance.vote_weighting.value),
            vote_weighting_params={
                k: NumberRange(min=r.min, max=r.max)
                for k, r in te_v1.governance.vote_weighting_params.items()
            },
        ),
        cross_token_flows=[
            _migrate_cross_token_flow(c) for c in te_v1.cross_token_flows
        ],
        events=[],
    )


# =============================================================================
# Native v2 YAML loader
# =============================================================================


def load_te_v2(path: str | Path) -> TokenEconomyV2:
    """Load a native v2 TokenEconomy from a YAML file.

    Mirrors v1's ``load_te`` shape — the YAML structure follows the
    Pydantic models field-for-field. Validation errors include the
    full field path. v1 YAMLs *will not* load via this function (their
    shape differs); use ``from_v1(load_te(path))`` for v1 inputs.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    return TokenEconomyV2.model_validate(raw)


# =============================================================================
# Design notes (not enforced by schema; captured for the next step)
# =============================================================================
#
# 1. Verifier semantics around coupled state.
#    State-driven Functions and ExchangeRates can reference variables
#    that themselves depend on the function's output (price ↔ supply ↔
#    redemption ↔ price). The verifier decouples at the FM level — see
#    docs/redesign/decoupling.md (to be written).
#
# 2. Stochastic semantics.
#    Any DistributionSpec the verifier encounters is interpreted as its
#    support. The simulator uses the distribution proper.
#
# 3. Reference-language scope.
#    The current References cover what the five case studies need plus
#    bonding-curve self-references. If a real economy needs more (e.g.
#    "Gini of agent balances"), add new Reference variants — do not
#    smuggle them into LiteralValue.
#
# 4. Event reachability and verifier complexity.
#    With DAG-validated events + bounded cooldowns, the reachable event
#    sequences over a finite horizon form a finite set. The verifier
#    encodes "did event X ever fire by period T?" as a Boolean per
#    (event, T) cell. Quadratic in the worst case; small in practice
#    because most economies have ≤10 events.
#
# 5. What this schema cannot express, even after v2.
#    Per-position state (e.g. each veCRV lock's individual decay
#    schedule). Oracle delays as continuous external signals with
#    derivative bounds. Memoryful agents (history-dependent utility).
#    These are deferred to v3 or simply left to the ABM layer where
#    they belong.
