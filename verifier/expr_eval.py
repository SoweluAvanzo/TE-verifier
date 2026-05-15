"""Three evaluator implementations sharing one Expr AST (Phase K3+).

ABMEvaluator   — numeric Python evaluation against concrete state + agent + event
MCEvaluator    — same shape, but sampled scalars per replicate (lighter env)
Z3Evaluator    — produces a Z3 expression for the formal verifier (Phase K4)

The three share the recursion logic via :func:`_walk`; they differ only
in the leaf resolution + operator implementation (lambda dispatch tables).
This keeps the AST as a single source of truth — any new expression
node added to ``schema/expr.py`` only needs three small implementations
(numeric, MC, Z3) and the FM checks see it automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from schema.expr import (
    AggregatorKind,
    AggregatorSpec,
    BinaryOp,
    CallOp,
    CollectionRef,
    Expr,
    VarNamespace,
    VarRef,
)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@dataclass
class EvalEnv:
    """Mutable evaluation context. Each evaluator constructs one of these
    before calling :func:`evaluate`. Mutation is local: aggregator
    iteration temporarily pushes ``loop_agent`` / ``loop_token`` /
    ``loop_event`` / ``loop_asset`` into the env and restores on exit.
    """

    state: Mapping[str, Any]                     # state.M[id], state.E[id], etc.
    params: Mapping[str, float] = field(default_factory=dict)
    consts: Mapping[str, float] = field(default_factory=dict)
    event: Mapping[str, Any] | None = None       # event payload + 'agent' sub-dict
    agent: Mapping[str, Any] | None = None       # currently-firing agent (or aggregator iter)
    # Static enumeration sources for aggregators:
    agents: list[Mapping[str, Any]] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Numeric (ABM + MC) evaluator
# ---------------------------------------------------------------------------


class EvalError(RuntimeError):
    """Raised when an expression cannot be evaluated in the given env."""


def evaluate(node: Expr, env: EvalEnv) -> float:
    """Evaluate an Expr AST to a single float against the supplied env.

    Used by both ABM (concrete state + per-event payload) and Monte
    Carlo (sampled scalars; same env contract). For Z3 see
    :func:`encode_z3`.
    """
    return _walk(node, env)


def _walk(node: Expr, env: EvalEnv) -> float:
    if node.const is not None:
        return float(node.const)
    if node.param is not None:
        try:
            return float(env.params[node.param])
        except KeyError as exc:
            raise EvalError(f"unbound parameter '{node.param}'") from exc
    if node.var is not None:
        return _resolve_var(node.var, env)
    if node.aggregator is not None:
        return _eval_aggregator(node.aggregator, env)
    if node.binary_op is not None:
        return _eval_binary(node, env)
    if node.call_op is not None:
        return _eval_call(node, env)
    raise EvalError(f"empty Expr node: {node!r}")


def _resolve_var(ref: VarRef, env: EvalEnv) -> float:
    ns = ref.ns
    path = ref.path
    if ns == VarNamespace.STATE:
        cur: Any = env.state
        for seg in path:
            cur = _get_one(cur, seg)
        return float(cur)
    if ns == VarNamespace.CONST:
        try:
            cur = env.consts[path[0]]
        except KeyError as exc:
            raise EvalError(f"unbound const.{path[0]}") from exc
        for seg in path[1:]:
            cur = _get_one(cur, seg)
        return float(cur)
    if ns == VarNamespace.EVENT:
        if env.event is None:
            raise EvalError(
                "event.* variable referenced but no event payload bound "
                "(rule must be event-driven)"
            )
        cur = env.event
        for seg in path:
            cur = _get_one(cur, seg)
        return float(cur)
    if ns == VarNamespace.AGENT:
        if env.agent is None:
            raise EvalError(
                "agent.* variable referenced but no agent bound "
                "(use inside an event-driven rule or aggregator body)"
            )
        cur = env.agent
        for seg in path:
            cur = _get_one(cur, seg)
        return float(cur)
    if ns == VarNamespace.ASSET:
        try:
            asset = env.state["assets"][path[0]]
        except (KeyError, TypeError) as exc:
            raise EvalError(f"asset.{path[0]} not in state") from exc
        cur = asset
        for seg in path[1:]:
            cur = _get_one(cur, seg)
        return float(cur)
    if ns == VarNamespace.PARAM:
        # Parsed param refs go through Expr(param=...). Bare param.NAME
        # via the variable path is technically reachable; treat the same.
        try:
            return float(env.params[path[0]])
        except KeyError as exc:
            raise EvalError(f"unbound param.{path[0]}") from exc
    raise EvalError(f"unsupported namespace {ns!r}")


def _get_one(container: Any, key: str) -> Any:
    """Tolerant attribute / item lookup."""
    if isinstance(container, Mapping):
        if key in container:
            return container[key]
        raise EvalError(f"key {key!r} not found in {type(container).__name__}")
    if hasattr(container, key):
        return getattr(container, key)
    raise EvalError(f"cannot resolve {key!r} on {container!r}")


_BINARY_NUMERIC: dict[BinaryOp, Callable[[float, float], float]] = {
    BinaryOp.ADD: lambda a, b: a + b,
    BinaryOp.SUB: lambda a, b: a - b,
    BinaryOp.MUL: lambda a, b: a * b,
    BinaryOp.DIV: lambda a, b: a / b if b != 0.0 else float("nan"),
    BinaryOp.POW: lambda a, b: a ** b,
    BinaryOp.GT:  lambda a, b: 1.0 if a > b else 0.0,
    BinaryOp.GTE: lambda a, b: 1.0 if a >= b else 0.0,
    BinaryOp.LT:  lambda a, b: 1.0 if a < b else 0.0,
    BinaryOp.LTE: lambda a, b: 1.0 if a <= b else 0.0,
    BinaryOp.EQ:  lambda a, b: 1.0 if a == b else 0.0,
    BinaryOp.NEQ: lambda a, b: 1.0 if a != b else 0.0,
    BinaryOp.AND: lambda a, b: 1.0 if (a != 0.0 and b != 0.0) else 0.0,
    BinaryOp.OR:  lambda a, b: 1.0 if (a != 0.0 or b != 0.0) else 0.0,
}


def _eval_binary(node: Expr, env: EvalEnv) -> float:
    op = _BINARY_NUMERIC[node.binary_op]
    return op(_walk(node.args[0], env), _walk(node.args[1], env))


def _eval_call(node: Expr, env: EvalEnv) -> float:
    if node.call_op == CallOp.IF:
        pred = _walk(node.args[0], env)
        return _walk(node.args[1] if pred != 0.0 else node.args[2], env)
    if node.call_op == CallOp.MIN:
        return min(_walk(node.args[0], env), _walk(node.args[1], env))
    if node.call_op == CallOp.MAX:
        return max(_walk(node.args[0], env), _walk(node.args[1], env))
    if node.call_op == CallOp.ABS:
        return abs(_walk(node.args[0], env))
    if node.call_op == CallOp.CLAMP:
        x = _walk(node.args[0], env)
        lo = _walk(node.args[1], env)
        hi = _walk(node.args[2], env)
        return max(lo, min(hi, x))
    if node.call_op == CallOp.LOG:
        x = _walk(node.args[0], env)
        return math.log(x) if x > 0 else float("-inf")
    if node.call_op == CallOp.EXP:
        return math.exp(_walk(node.args[0], env))
    raise EvalError(f"unsupported call_op {node.call_op!r}")


def _eval_aggregator(spec: AggregatorSpec, env: EvalEnv) -> float:
    """Enumerate the collection, push the iteration variable into env,
    evaluate body, combine. Aggregators are ALWAYS bounded — the
    collections are statically enumerable at parse time."""
    items = _collection_items(spec, env)
    if not items:
        return 0.0
    saved_agent = env.agent
    saved_event = env.event
    try:
        values: list[float] = []
        for item in items:
            # The aggregator iteration binds to the right namespace
            # depending on the collection kind. For AGENTS / AGENTS_OF_TYPE
            # the loop var becomes the current agent; for TOKENS / EVENTS /
            # ASSETS it becomes a string identifier accessible via state.
            if spec.collection in (CollectionRef.AGENTS, CollectionRef.AGENTS_OF_TYPE):
                env.agent = item
            elif spec.collection == CollectionRef.ASSETS:
                # asset.<id> resolution; loop body references asset.*
                env.event = {"asset_id": item}   # informational only
            values.append(_walk(spec.body, env))
        if spec.kind == AggregatorKind.SUM_OVER:
            return sum(values)
        if spec.kind == AggregatorKind.MEAN_OVER:
            return sum(values) / len(values)
        if spec.kind == AggregatorKind.COUNT_OF:
            return float(sum(1 for v in values if v != 0.0))
        if spec.kind == AggregatorKind.FRACTION_OF:
            n_true = sum(1 for v in values if v != 0.0)
            return n_true / len(values)
        raise EvalError(f"unknown aggregator kind {spec.kind!r}")
    finally:
        env.agent = saved_agent
        env.event = saved_event


def _collection_items(spec: AggregatorSpec, env: EvalEnv) -> list[Any]:
    if spec.collection == CollectionRef.AGENTS:
        return list(env.agents)
    if spec.collection == CollectionRef.AGENTS_OF_TYPE:
        if spec.filter_arg is None:
            return list(env.agents)
        return [a for a in env.agents if _get_one(a, "type") == spec.filter_arg]
    if spec.collection == CollectionRef.TOKENS:
        return list(env.tokens)
    if spec.collection == CollectionRef.EVENTS:
        return list(env.events)
    if spec.collection == CollectionRef.ASSETS:
        return list(env.assets)
    return []


# ---------------------------------------------------------------------------
# Z3 evaluator (Phase K4)
# ---------------------------------------------------------------------------
#
# Encodes an Expr into a Z3 expression that the failure-mode checks can
# embed in their per-period rate equation. The decidable subset matches
# what is_decidable() approves. For non-decidable nodes (log/exp of
# variable, etc.) the encoder returns None — caller marks the FM
# verdict 'inconclusive'.

import z3
from schema import NumberRange


@dataclass
class Z3Env:
    """Binding environment for Z3 encoding.

    ``state_vars`` map dotted state-paths ("M.BTC", "Q", "t", etc.) to
    bound Z3 reals declared by the caller (FM module). ``param_vars``
    map parameter names to bound reals (declared from ParamDecl).
    ``event_payload_vars`` are bound reals declared per event payload
    field. ``agent_vars`` is the iter-binding for aggregator loops over
    agents (populated transiently by the aggregator encoder).
    ``const_values`` are scalar Python floats (no bounds needed).
    """

    solver: z3.Solver
    state_vars: dict[str, z3.ArithRef]
    param_vars: dict[str, z3.ArithRef]
    event_payload_vars: dict[str, z3.ArithRef]
    const_values: dict[str, float]
    agents: list[Mapping[str, Any]]
    tokens: list[str]
    events: list[str]
    assets: list[str]
    agent_vars: dict[str, z3.ArithRef] = field(default_factory=dict)


class Z3EncodingError(RuntimeError):
    """Raised when an Expr cannot be encoded for the formal layer."""


def encode_z3(node: Expr, env: Z3Env) -> z3.ArithRef:
    """Encode an Expr tree as a Z3 real expression.

    Caller asserts is_decidable beforehand. If the analyzer flags
    non-decidable nodes, this raises Z3EncodingError; the FM module
    catches it and marks the verdict inconclusive."""
    return _z3_walk(node, env)


def _z3_walk(node: Expr, env: Z3Env) -> z3.ArithRef:
    if node.const is not None:
        return z3.RealVal(node.const)
    if node.param is not None:
        try:
            return env.param_vars[node.param]
        except KeyError as exc:
            raise Z3EncodingError(f"unbound parameter '{node.param}'") from exc
    if node.var is not None:
        return _z3_resolve_var(node.var, env)
    if node.aggregator is not None:
        return _z3_aggregator(node.aggregator, env)
    if node.binary_op is not None:
        return _z3_binary(node, env)
    if node.call_op is not None:
        return _z3_call(node, env)
    raise Z3EncodingError(f"empty Expr node: {node!r}")


def _z3_resolve_var(ref: VarRef, env: Z3Env) -> z3.ArithRef:
    if ref.ns == VarNamespace.PARAM:
        key = ref.path[0]
        if key in env.param_vars:
            return env.param_vars[key]
        raise Z3EncodingError(f"unbound param.{key}")
    if ref.ns == VarNamespace.CONST:
        # Const namespace is a scalar lookup.
        key = ref.path[0]
        if key in env.const_values:
            return z3.RealVal(env.const_values[key])
        raise Z3EncodingError(f"unbound const.{key}")
    if ref.ns == VarNamespace.EVENT:
        # Event payload field.
        key = ".".join(ref.path)
        if key in env.event_payload_vars:
            return env.event_payload_vars[key]
        raise Z3EncodingError(
            f"event.{key} not bound — declare the payload field on the EventDefinition"
        )
    if ref.ns in (VarNamespace.STATE, VarNamespace.ASSET):
        key = ".".join(ref.path)
        if key in env.state_vars:
            return env.state_vars[key]
        raise Z3EncodingError(
            f"state variable {ref.ns.value}.{key} not bound — the FM module must "
            f"declare it before encoding"
        )
    if ref.ns == VarNamespace.AGENT:
        # Inside an aggregator body the loop has pushed agent fields
        # into agent_vars under their leaf names (e.g. ``balance``).
        # Outside aggregators, the formal layer can't reason per-agent
        # — caller must wrap with a sum_over / mean_over.
        key = ".".join(ref.path)
        if key in env.agent_vars:
            return env.agent_vars[key]
        raise Z3EncodingError(
            "agent.* references outside an aggregator aren't supported "
            "in the Z3 encoder — the verifier reasons aggregately, "
            "not per-agent. Wrap with sum_over(agents, ...)."
        )
    raise Z3EncodingError(f"unsupported namespace {ref.ns!r}")


def _z3_binary(node: Expr, env: Z3Env) -> z3.ArithRef:
    op = node.binary_op
    a = _z3_walk(node.args[0], env)
    b = _z3_walk(node.args[1], env)
    if op == BinaryOp.ADD: return a + b
    if op == BinaryOp.SUB: return a - b
    if op == BinaryOp.MUL: return a * b
    if op == BinaryOp.DIV: return a / b
    if op == BinaryOp.POW:
        # Exponent must be a positive integer literal (parser enforces).
        k = int(node.args[1].const)
        result = z3.RealVal(1)
        for _ in range(k):
            result = result * a
        return result
    # Comparisons → Z3 If(bool, 1, 0) so the result stays Real-typed.
    bool_map = {
        BinaryOp.GT:  a > b,    BinaryOp.GTE: a >= b,
        BinaryOp.LT:  a < b,    BinaryOp.LTE: a <= b,
        BinaryOp.EQ:  a == b,   BinaryOp.NEQ: a != b,
        BinaryOp.AND: z3.And(a != 0, b != 0),
        BinaryOp.OR:  z3.Or(a != 0, b != 0),
    }
    if op in bool_map:
        return z3.If(bool_map[op], z3.RealVal(1), z3.RealVal(0))
    raise Z3EncodingError(f"unsupported binary_op {op!r}")


def _z3_call(node: Expr, env: Z3Env) -> z3.ArithRef:
    op = node.call_op
    if op == CallOp.IF:
        pred = _z3_walk(node.args[0], env)
        return z3.If(
            pred != 0,
            _z3_walk(node.args[1], env),
            _z3_walk(node.args[2], env),
        )
    if op == CallOp.MIN:
        a = _z3_walk(node.args[0], env)
        b = _z3_walk(node.args[1], env)
        return z3.If(a <= b, a, b)
    if op == CallOp.MAX:
        a = _z3_walk(node.args[0], env)
        b = _z3_walk(node.args[1], env)
        return z3.If(a >= b, a, b)
    if op == CallOp.ABS:
        a = _z3_walk(node.args[0], env)
        return z3.If(a >= 0, a, -a)
    if op == CallOp.CLAMP:
        x = _z3_walk(node.args[0], env)
        lo = _z3_walk(node.args[1], env)
        hi = _z3_walk(node.args[2], env)
        return z3.If(x < lo, lo, z3.If(x > hi, hi, x))
    if op in (CallOp.LOG, CallOp.EXP):
        # Constant arguments: collapse to a numeric Z3 value.
        if node.args[0].const is not None:
            import math
            val = math.log(node.args[0].const) if op == CallOp.LOG else math.exp(node.args[0].const)
            return z3.RealVal(val)
        raise Z3EncodingError(
            f"{op.value} of non-constant argument is not Z3-decidable; "
            f"the verifier marks the FM inconclusive."
        )
    raise Z3EncodingError(f"unsupported call_op {op!r}")


def _z3_aggregator(spec: AggregatorSpec, env: Z3Env) -> z3.ArithRef:
    """Unroll the collection into an additive Z3 expression.

    Iterations bind the loop variable into a temporary state map so the
    body can reference it via the appropriate namespace. Aggregators
    are bounded by construction — the verifier reasons over a
    declared-size population, not an unbounded one.
    """
    items = _z3_collection_items(spec, env)
    if not items:
        return z3.RealVal(0)
    body_values: list[z3.ArithRef] = []
    saved_agent_vars = dict(env.agent_vars)
    try:
        for item in items:
            if spec.collection in (CollectionRef.AGENTS, CollectionRef.AGENTS_OF_TYPE):
                # Push agent fields into agent_vars; resolver reads them
                # when it sees a VarRef(ns=AGENT, path=[...]).
                env.agent_vars = {}
                for fname, fval in item.items():
                    if isinstance(fval, (int, float)):
                        env.agent_vars[fname] = z3.RealVal(float(fval))
            body_values.append(_z3_walk(spec.body, env))
        if spec.kind == AggregatorKind.SUM_OVER:
            return sum(body_values[1:], body_values[0])
        if spec.kind == AggregatorKind.MEAN_OVER:
            total = sum(body_values[1:], body_values[0])
            return total / z3.RealVal(len(body_values))
        if spec.kind == AggregatorKind.COUNT_OF:
            # Treat any non-zero body as 1.
            ones = [z3.If(v != 0, z3.RealVal(1), z3.RealVal(0)) for v in body_values]
            return sum(ones[1:], ones[0]) if ones else z3.RealVal(0)
        if spec.kind == AggregatorKind.FRACTION_OF:
            ones = [z3.If(v != 0, z3.RealVal(1), z3.RealVal(0)) for v in body_values]
            return (sum(ones[1:], ones[0]) if ones else z3.RealVal(0)) / z3.RealVal(len(body_values))
        raise Z3EncodingError(f"unknown aggregator kind {spec.kind!r}")
    finally:
        env.agent_vars = saved_agent_vars


def _z3_collection_items(spec: AggregatorSpec, env: Z3Env) -> list[Any]:
    if spec.collection == CollectionRef.AGENTS:
        return list(env.agents)
    if spec.collection == CollectionRef.AGENTS_OF_TYPE:
        if spec.filter_arg is None:
            return list(env.agents)
        return [a for a in env.agents if a.get("type") == spec.filter_arg]
    if spec.collection == CollectionRef.TOKENS:
        return list(env.tokens)
    if spec.collection == CollectionRef.EVENTS:
        return list(env.events)
    if spec.collection == CollectionRef.ASSETS:
        return list(env.assets)
    return []


# ---------------------------------------------------------------------------
# Convenience: bind a NumberRange-typed parameter and add it as a Z3 real
# ---------------------------------------------------------------------------


def bind_param(solver: z3.Solver, name: str, rng) -> z3.ArithRef:
    """Declare a fresh Z3 Real bounded to ``[rng.min, rng.max]`` and
    return the handle. ``rng`` may be a ``schema.NumberRange`` or
    anything with ``min``/``max`` attributes."""
    v = z3.Real(f"param__{name}")
    solver.add(v >= rng.min, v <= rng.max)
    return v


# ---------------------------------------------------------------------------
# Engine shim — unified FunctionShape evaluation (Phase K5)
# ---------------------------------------------------------------------------
#
# Goal: every engine call site reads a rule's magnitude through ONE
# function, regardless of whether the user wrote a legacy
# ``asymptotic_class`` shorthand or a Phase-K1 ``expression``. The
# shim resolves to the right backend transparently. Legacy code
# downstream (rate_per_period, _sample_rule_rate, etc.) keeps working.


def sample_params(parameters, sampler) -> dict[str, float]:
    """Draw one numeric value per declared rule parameter using the
    same sampler the engine uses elsewhere (so determinism by seed is
    preserved). For ``distribution`` (when present) we still draw from
    the range — distribution-aware MC sampling lives in MCEvaluator
    proper. ABM treats parameters as once-per-run draws."""
    if not parameters:
        return {}
    out: dict[str, float] = {}
    for p in parameters:
        if p.range.min == p.range.max:
            out[p.name] = p.range.min
        else:
            out[p.name] = sampler.rng.uniform(p.range.min, p.range.max)
    return out


def sample_event_payload(event_def, sampler) -> dict[str, float]:
    """Draw one numeric value per declared scalar payload field."""
    if not event_def or not event_def.payload:
        return {}
    out: dict[str, float] = {}
    for field in event_def.payload:
        if field.type.value != "scalar" or field.range is None:
            continue
        if field.range.min == field.range.max:
            out[field.name] = field.range.min
        else:
            out[field.name] = sampler.rng.uniform(field.range.min, field.range.max)
    return out


def evaluate_function_shape(
    function_shape,
    *,
    state: Mapping[str, Any] | None = None,
    event: Mapping[str, Any] | None = None,
    agent: Mapping[str, Any] | None = None,
    params: Mapping[str, float] | None = None,
    consts: Mapping[str, float] | None = None,
    agents: list[Mapping[str, Any]] | None = None,
    tokens: list[str] | None = None,
    events: list[str] | None = None,
    assets: list[str] | None = None,
    sampler=None,
    legacy_fallback=None,
) -> float:
    """Numeric value of a Rule's FunctionShape against the supplied
    context. Auto-dispatches:

    * ``expression`` set → evaluate the AST (Phase K1+ path)
    * ``asymptotic_class`` set → delegate to ``legacy_fallback(ac,
      sampler)`` which the engine supplies (typically
      ``_sample_ac``).

    Keeps every call site in the engine schema-version-agnostic.
    """
    if function_shape is None:
        return 0.0
    if function_shape.expression is not None:
        env = EvalEnv(
            state=state or {},
            params=dict(params or {}),
            consts=consts or {},
            event=event,
            agent=agent,
            agents=list(agents or []),
            tokens=list(tokens or []),
            events=list(events or []),
            assets=list(assets or []),
        )
        # Sampler-supplied parameter values may live in ``params``;
        # if not, fill from declared ParamDecls.
        if sampler is not None and function_shape.parameters:
            for name, val in sample_params(function_shape.parameters, sampler).items():
                env.params.setdefault(name, val)
        return float(evaluate(function_shape.expression, env))
    if function_shape.asymptotic_class is not None and legacy_fallback is not None:
        return float(legacy_fallback(function_shape.asymptotic_class, sampler))
    return 0.0

