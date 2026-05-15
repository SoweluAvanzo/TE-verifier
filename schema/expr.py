"""State-dependent expression AST (Phase K1).

Routes rule magnitudes from "function of time only" to "function of
state + event payload + parameters". Single canonical form (a Pydantic
tree) shared by all three verification layers:

* Z3 encoder         (formal)
* Monte Carlo eval   (likelihood)
* ABM eval           (trajectory)

Surface DSL is parsed into this AST; loader auto-synthesizes the AST
from the legacy ``AsymptoticClass`` shorthand when the user hasn't
opted into the expression form. Pydantic guards the AST shape so
downstream consumers never have to defensively check every node.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Variable references
# ---------------------------------------------------------------------------


class VarNamespace(str, Enum):
    """Closed set of variable namespaces the DSL can read.

    Each namespace has a fixed set of resolvable paths — anything else
    is a parse / validation error. Keeping the set closed lets every
    evaluator (Z3, MC, ABM) implement variable resolution exhaustively.
    """

    STATE = "state"      # per-period system state (M, E, B, Q, N, t, phi, gini, events_realized, assets)
    EVENT = "event"      # per-event payload — only meaningful inside event-driven rules
    AGENT = "agent"      # agent firing the event (balance, reputation, type, tenure)
    ASSET = "asset"      # non-tokenized asset state
    PARAM = "param"      # rule-local named constants (declared inline)
    CONST = "const"      # global constants (horizon, max_lock_duration, etc.)


class VarRef(BaseModel):
    """A variable reference.

    ``path`` is a list of identifiers and string index keys interleaved.
    For example ``state.M['BTC']`` parses to ``ns=state, path=['M', 'BTC']``;
    ``event.agent.reputation`` parses to ``ns=event, path=['agent', 'reputation']``.
    The evaluator decides how to resolve based on the namespace.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ns: VarNamespace
    path: list[str]

    def path_str(self) -> str:
        return f"{self.ns.value}." + ".".join(self.path)


# ---------------------------------------------------------------------------
# Aggregation specification
# ---------------------------------------------------------------------------


class AggregatorKind(str, Enum):
    SUM_OVER = "sum_over"
    MEAN_OVER = "mean_over"
    COUNT_OF = "count_of"
    FRACTION_OF = "fraction_of"


class CollectionRef(str, Enum):
    """Static collections the DSL can aggregate over. The verifier and
    ABM both need to know how to enumerate these at parse time, so we
    restrict to a closed set."""

    AGENTS = "agents"                              # all agents
    AGENTS_OF_TYPE = "agents_of_type"              # filtered by agent_type id (argument)
    TOKENS = "tokens"
    EVENTS = "events"
    ASSETS = "assets"


class AggregatorSpec(BaseModel):
    """Bounded aggregation over a statically-known collection.

    ``body`` is an Expr evaluated with a loop-bound ``item`` variable
    pushed into the environment. ``filter_arg`` carries an optional
    string argument (e.g. agent-type id for AGENTS_OF_TYPE).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AggregatorKind
    collection: CollectionRef
    filter_arg: str | None = None
    body: "Expr"
    # Name bound inside body for each item.
    bind_name: str = "item"


# ---------------------------------------------------------------------------
# Expression
# ---------------------------------------------------------------------------


class BinaryOp(str, Enum):
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    POW = "pow"            # base ** integer_exponent
    GT = "gt"              # used inside `if` predicates
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    AND = "and"
    OR  = "or"


class CallOp(str, Enum):
    IF = "if"               # if(pred, then_expr, else_expr)
    MIN = "min"
    MAX = "max"
    ABS = "abs"
    CLAMP = "clamp"         # clamp(x, lo, hi)
    LOG = "log"             # transcendental — non-decidable for formal
    EXP = "exp"             # transcendental — non-decidable for formal


class Expr(BaseModel):
    """One AST node.

    Exactly one of the leaf / composite fields is non-null per node;
    the validator enforces this. Recursive via ``args``.

    Leaves:
      * ``const`` — float literal
      * ``var``   — variable reference
      * ``param`` — name of a rule-local parameter

    Composites:
      * ``binary_op`` + 2-arg ``args`` — arithmetic / comparison / boolean
      * ``call_op`` + n-arg ``args`` — bounded calls (if, min, max, clamp, log, exp)
      * ``aggregator`` — bounded aggregation over a static collection
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    const: float | None = None
    var: VarRef | None = None
    param: str | None = None

    binary_op: BinaryOp | None = None
    call_op: CallOp | None = None

    args: list["Expr"] = Field(default_factory=list)

    aggregator: AggregatorSpec | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Expr":
        kinds = [
            self.const is not None,
            self.var is not None,
            self.param is not None,
            self.binary_op is not None,
            self.call_op is not None,
            self.aggregator is not None,
        ]
        if sum(kinds) != 1:
            raise ValueError(
                "Expr node must have exactly one of {const, var, param, "
                "binary_op, call_op, aggregator} set"
            )
        # Arity checks
        if self.binary_op is not None:
            if len(self.args) != 2:
                raise ValueError(
                    f"binary_op {self.binary_op.value} requires exactly 2 args, got {len(self.args)}"
                )
        if self.call_op is not None:
            expected = {
                CallOp.IF: 3,
                CallOp.MIN: 2,
                CallOp.MAX: 2,
                CallOp.ABS: 1,
                CallOp.CLAMP: 3,
                CallOp.LOG: 1,
                CallOp.EXP: 1,
            }[self.call_op]
            if len(self.args) != expected:
                raise ValueError(
                    f"call_op {self.call_op.value} requires {expected} args, got {len(self.args)}"
                )
        return self


# Resolve the forward reference inside AggregatorSpec.body
AggregatorSpec.model_rebuild()
Expr.model_rebuild()


# ---------------------------------------------------------------------------
# Parameter declarations
# ---------------------------------------------------------------------------


class ParamDecl(BaseModel):
    """Rule-local named constant + its bounds for the verifier.

    Each rule's expression sees these names under the ``param.*``
    namespace. Bounds are required so Z3 has something to constrain.
    ``distribution`` is optional — if present, MC samples from it per
    replicate; otherwise treated as the midpoint of ``range``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    range: "NumberRangeRef"
    # Forward-declared placeholder; concrete DistributionSpec import
    # happens in the consumer modules to avoid a circular import here.
    distribution: dict | None = None


# Tiny inline mirror of NumberRange so this module stays import-free
# of the full schema. The full schema's NumberRange is structurally
# identical; consumers can pass either.
class NumberRangeRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    min: float
    max: float

    @model_validator(mode="after")
    def _ordering(self) -> "NumberRangeRef":
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) > max ({self.max})")
        return self


ParamDecl.model_rebuild()


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------


class PayloadFieldType(str, Enum):
    SCALAR = "scalar"
    STRING = "string"


class EventPayloadField(BaseModel):
    """A typed payload field declared on an EventDefinition.

    Inside a rule's expression, this field becomes addressable as
    ``event.<name>``. The verifier reasons over ``range`` (required for
    SCALAR fields); MC samples from ``distribution`` (when set) per
    replicate; ABM samples per event-firing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: PayloadFieldType = PayloadFieldType.SCALAR
    range: NumberRangeRef | None = None
    distribution: dict | None = None

    @model_validator(mode="after")
    def _scalar_needs_range(self) -> "EventPayloadField":
        if self.type == PayloadFieldType.SCALAR and self.range is None:
            raise ValueError(
                f"EventPayloadField '{self.name}' of type=scalar requires a range"
            )
        return self
