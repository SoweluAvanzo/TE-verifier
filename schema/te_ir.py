"""Token Economy Intermediate Representation (TE-IR).

Pydantic v2 models implementing the schema sketched in docs/architecture.md.
This is the single canonical data structure shared between the questionnaire
frontend, the verifier backends, and the simulation fallback.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

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


class RuleTrigger(_Frozen):
    """When a Rule fires."""

    kind: EmissionTriggerKind | BurnTriggerKind
    event_predicate: str | None = None
    event_frequency: AsymptoticClass | None = None


class FunctionShape(_Frozen):
    """The (sign, asymptotic_class) classification of a Rule's function."""

    sign: FunctionSign
    asymptotic_class: AsymptoticClass


class RegimeSwitch(_Frozen):
    """A piecewise change in function behavior above a threshold."""

    predicate: str
    function: FunctionShape


class Rule(_Frozen):
    """A mint or burn rule. Used for both emission and burn."""

    trigger: RuleTrigger
    function: FunctionShape
    regimes: list[RegimeSwitch] = Field(default_factory=list)


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


class CrossTokenFlow(_Frozen):
    source_token: str
    source_event: str
    target_token: str
    target_action: CrossTokenAction
    amount: AsymptoticClass


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
    expected_Q: NumberRange  # transactions per period
    average_demand_d: NumberRange  # redemption events per participant per period
    growth_g: AsymptoticClass  # population growth class
    topology: Topology
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
    SINGLE_ENTITY = "single_entity"
    COMMITTEE = "committee"
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


class GovernanceSpec(_Frozen):
    type: GovernanceType
    rule_structure: dict[str, ControllingActor] = Field(default_factory=dict)
    monitoring_capacity_gamma: NumberRange = NumberRange.point(0.5)
    sanction_structure: SanctionStructure = SanctionStructure(
        kind=SanctionKind.WARNING
    )
    token_balance_gini: NumberRange | None = None  # secondary FM6 signal


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
