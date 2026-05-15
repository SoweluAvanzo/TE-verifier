"""Phase K1 — state-dependent expression AST schema.

Verifies:
  * Expr leaf / composite nodes enforce arity + exactly-one-kind.
  * FunctionShape rejects both modes at once and demands at least one.
  * Round-trip via JSON for veCRV / MakerDAO-shaped expressions.
  * EventDefinition payload typing — scalar fields require ranges.
  * Mutual exclusion + parameter-without-expression validators.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    BinaryOp,
    CallOp,
    EventDefinition,
    EventPayloadField,
    EventTriggerKind,
    Expr,
    FunctionShape,
    NumberRange,
    NumberRangeRef,
    ParamDecl,
    PayloadFieldType,
    VarNamespace,
    VarRef,
)


# ---------------------------------------------------------------------------
# Expr leaf + composite validators
# ---------------------------------------------------------------------------


def test_expr_const_leaf_ok() -> None:
    assert Expr(const=3.14).const == 3.14


def test_expr_var_leaf_ok() -> None:
    e = Expr(var=VarRef(ns=VarNamespace.STATE, path=["M", "BTC"]))
    assert e.var.path_str() == "state.M.BTC"


def test_expr_param_leaf_ok() -> None:
    assert Expr(param="max_lock").param == "max_lock"


def test_expr_rejects_zero_kinds() -> None:
    with pytest.raises(ValidationError):
        Expr()


def test_expr_rejects_two_kinds() -> None:
    with pytest.raises(ValidationError):
        Expr(const=1.0, param="x")


def test_expr_binary_op_requires_two_args() -> None:
    with pytest.raises(ValidationError):
        Expr(binary_op=BinaryOp.ADD, args=[Expr(const=1.0)])


def test_expr_binary_op_works_with_two_args() -> None:
    e = Expr(
        binary_op=BinaryOp.MUL,
        args=[Expr(const=2.0), Expr(var=VarRef(ns=VarNamespace.EVENT, path=["amount"]))],
    )
    assert e.binary_op == BinaryOp.MUL
    assert len(e.args) == 2


def test_expr_call_op_arity_enforced() -> None:
    # clamp(x, lo, hi) → 3 args
    with pytest.raises(ValidationError):
        Expr(call_op=CallOp.CLAMP, args=[Expr(const=1.0), Expr(const=0.0)])
    # if(pred, then, else) → 3 args
    with pytest.raises(ValidationError):
        Expr(call_op=CallOp.IF, args=[Expr(const=1.0)])


def test_expr_min_and_abs_arities() -> None:
    Expr(call_op=CallOp.MIN, args=[Expr(const=1.0), Expr(const=2.0)])
    Expr(call_op=CallOp.ABS, args=[Expr(const=-3.0)])


# ---------------------------------------------------------------------------
# FunctionShape mutual exclusion
# ---------------------------------------------------------------------------


def _ac_constant(c_min=10.0, c_max=20.0):
    return AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange(min=c_min, max=c_max)},
    )


def test_function_shape_requires_one_mode() -> None:
    with pytest.raises(ValidationError):
        FunctionShape()


def test_function_shape_rejects_both_modes() -> None:
    with pytest.raises(ValidationError):
        FunctionShape(
            asymptotic_class=_ac_constant(),
            expression=Expr(const=5.0),
        )


def test_function_shape_legacy_mode_works() -> None:
    fs = FunctionShape(asymptotic_class=_ac_constant())
    assert fs.expression is None
    assert fs.parameters == []


def test_function_shape_expression_mode_works() -> None:
    expr = Expr(binary_op=BinaryOp.MUL, args=[
        Expr(var=VarRef(ns=VarNamespace.EVENT, path=["amount"])),
        Expr(param="rate"),
    ])
    fs = FunctionShape(
        expression=expr,
        parameters=[ParamDecl(name="rate", range=NumberRangeRef(min=0.0, max=1.0))],
    )
    assert fs.expression is expr
    assert fs.parameters[0].name == "rate"


def test_function_shape_parameters_without_expression_rejected() -> None:
    with pytest.raises(ValidationError):
        FunctionShape(
            asymptotic_class=_ac_constant(),
            parameters=[ParamDecl(name="r", range=NumberRangeRef(min=0.0, max=1.0))],
        )


# ---------------------------------------------------------------------------
# EventDefinition.payload
# ---------------------------------------------------------------------------


def test_event_definition_with_payload_ok() -> None:
    ev = EventDefinition(
        id="user_locks_crv",
        label="User locks CRV → veCRV mint",
        kind=EventTriggerKind.BEHAVIORAL,
        payload=[
            EventPayloadField(
                name="amount",
                type=PayloadFieldType.SCALAR,
                range=NumberRangeRef(min=1.0, max=1e6),
            ),
            EventPayloadField(
                name="duration",
                type=PayloadFieldType.SCALAR,
                range=NumberRangeRef(min=1.0, max=208.0),
            ),
        ],
    )
    assert len(ev.payload) == 2
    assert ev.payload[0].range.max == 1e6


def test_scalar_payload_requires_range() -> None:
    with pytest.raises(ValidationError):
        EventPayloadField(name="x", type=PayloadFieldType.SCALAR)


def test_string_payload_works_without_range() -> None:
    f = EventPayloadField(name="kind", type=PayloadFieldType.STRING)
    assert f.range is None


# ---------------------------------------------------------------------------
# JSON round-trip — veCRV-shaped expression
# ---------------------------------------------------------------------------


def test_vecrv_expression_round_trips_through_json() -> None:
    expr = Expr(
        binary_op=BinaryOp.DIV,
        args=[
            Expr(binary_op=BinaryOp.MUL, args=[
                Expr(var=VarRef(ns=VarNamespace.EVENT, path=["amount"])),
                Expr(var=VarRef(ns=VarNamespace.EVENT, path=["duration"])),
            ]),
            Expr(param="max_lock_periods"),
        ],
    )
    fs = FunctionShape(
        expression=expr,
        parameters=[ParamDecl(
            name="max_lock_periods",
            range=NumberRangeRef(min=208.0, max=208.0),
        )],
    )
    dumped = fs.model_dump_json()
    restored = FunctionShape.model_validate_json(dumped)
    assert restored.expression.binary_op == BinaryOp.DIV
    assert restored.parameters[0].name == "max_lock_periods"


# ---------------------------------------------------------------------------
# Numeric range coherence
# ---------------------------------------------------------------------------


def test_number_range_ref_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError):
        NumberRangeRef(min=10.0, max=5.0)
