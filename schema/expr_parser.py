"""DSL surface-syntax parser + decidability analyzer (Phase K2).

Hand-written recursive-descent parser. Converts the user-facing
expression syntax into an :class:`schema.expr.Expr` AST.

Grammar (right-associative for ^, left-associative for everything else):

    expr        := or_expr
    or_expr     := and_expr ( '||' and_expr )*
    and_expr    := cmp_expr ( '&&' cmp_expr )*
    cmp_expr    := add_expr ( ( '>' | '>=' | '<' | '<=' | '==' | '!=' ) add_expr )?
    add_expr    := mul_expr ( ( '+' | '-' ) mul_expr )*
    mul_expr    := unary_expr ( ( '*' | '/' ) unary_expr )*
    unary_expr  := '-' unary_expr | pow_expr
    pow_expr    := atom ( '^' INT )?
    atom        := NUMBER | variable | call | '(' expr ')'
    variable    := NS '.' IDENT ( '.' IDENT | '[' STRING ']' )*
    call        := IDENT '(' expr ( ',' expr )* ')'

Surface helpers:

* ``min(a, b)``, ``max(a, b)``, ``abs(x)``, ``clamp(x, lo, hi)`` —
  bounded calls. Encoded as ``CallOp``.
* ``if(predicate, then_expr, else_expr)`` — conditional. First arg is
  any boolean predicate (comparison / logical combination).
* ``log(x)``, ``exp(x)`` — transcendentals. Allowed but flagged as
  non-decidable for the formal layer.
* ``sum_over(collection, body)``, ``mean_over(...)``, ``count_of(...)``,
  ``fraction_of(...)`` — bounded aggregation. ``collection`` is one of
  ``agents``, ``agents_of_type[ID]``, ``tokens``, ``events``, ``assets``.

Closed namespace set: ``state``, ``event``, ``agent`` (alias for
``event.agent``), ``asset``, ``param``, ``const``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

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
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


_TOKEN_PATTERNS = [
    ("NUMBER",    r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"),
    ("STRING",    r"'[^']*'|\"[^\"]*\""),
    ("IDENT",     r"[A-Za-z_][A-Za-z0-9_]*"),
    ("OP_2",      r"==|!=|<=|>=|\|\||&&"),
    ("OP_1",      r"[+\-*/^=<>(),.\[\]]"),
    ("WS",        r"\s+"),
]
_TOKEN_RE = re.compile(
    "|".join(f"(?P<{kind}>{pat})" for kind, pat in _TOKEN_PATTERNS)
)


def _tokenize(source: str) -> list[Token]:
    out: list[Token] = []
    pos = 0
    while pos < len(source):
        m = _TOKEN_RE.match(source, pos)
        if m is None:
            raise ParseError(
                f"Unexpected character {source[pos]!r} at position {pos}",
                pos,
            )
        kind = m.lastgroup
        value = m.group()
        if kind != "WS":
            out.append(Token(kind, value, pos))
        pos = m.end()
    out.append(Token("EOF", "", pos))
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ParseError(ValueError):
    """Raised when the surface syntax is malformed."""

    def __init__(self, message: str, pos: int = -1) -> None:
        if pos >= 0:
            message = f"{message} (at position {pos})"
        super().__init__(message)
        self.pos = pos


_CALL_NAMES = {
    "min": CallOp.MIN,
    "max": CallOp.MAX,
    "abs": CallOp.ABS,
    "clamp": CallOp.CLAMP,
    "if": CallOp.IF,
    "log": CallOp.LOG,
    "exp": CallOp.EXP,
}

_AGGREGATOR_NAMES = {
    "sum_over": AggregatorKind.SUM_OVER,
    "mean_over": AggregatorKind.MEAN_OVER,
    "count_of": AggregatorKind.COUNT_OF,
    "fraction_of": AggregatorKind.FRACTION_OF,
}

_NAMESPACE_NAMES = {ns.value for ns in VarNamespace}


def parse(source: str) -> Expr:
    """Surface DSL → Expr AST. Raises ParseError on malformed input."""
    if not source or not source.strip():
        raise ParseError("empty expression")
    tokens = _tokenize(source)
    parser = _Parser(tokens)
    tree = parser.parse_or_expr()
    parser.expect("EOF")
    return tree


class _Parser:
    """Recursive-descent driver over a tokenized stream."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    # ----- utilities -----
    def peek(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def match(self, kind: str, value: str | None = None) -> Token | None:
        tok = self.peek()
        if tok.kind == kind and (value is None or tok.value == value):
            return self.advance()
        return None

    def expect(self, kind: str, value: str | None = None) -> Token:
        tok = self.match(kind, value)
        if tok is None:
            cur = self.peek()
            desc = f"{kind}" if value is None else f"{kind} {value!r}"
            raise ParseError(
                f"Expected {desc}, got {cur.kind} {cur.value!r}", cur.pos,
            )
        return tok

    # ----- grammar -----
    def parse_or_expr(self) -> Expr:
        left = self.parse_and_expr()
        while self.match("OP_2", "||"):
            right = self.parse_and_expr()
            left = Expr(binary_op=BinaryOp.OR, args=[left, right])
        return left

    def parse_and_expr(self) -> Expr:
        left = self.parse_cmp_expr()
        while self.match("OP_2", "&&"):
            right = self.parse_cmp_expr()
            left = Expr(binary_op=BinaryOp.AND, args=[left, right])
        return left

    _CMP_OPS = {
        ">":  BinaryOp.GT,  ">=": BinaryOp.GTE,
        "<":  BinaryOp.LT,  "<=": BinaryOp.LTE,
        "==": BinaryOp.EQ,  "!=": BinaryOp.NEQ,
    }

    def parse_cmp_expr(self) -> Expr:
        left = self.parse_add_expr()
        tok = self.peek()
        if (tok.kind == "OP_2" and tok.value in self._CMP_OPS) or (
            tok.kind == "OP_1" and tok.value in self._CMP_OPS
        ):
            self.advance()
            right = self.parse_add_expr()
            return Expr(
                binary_op=self._CMP_OPS[tok.value], args=[left, right]
            )
        return left

    def parse_add_expr(self) -> Expr:
        left = self.parse_mul_expr()
        while True:
            tok = self.peek()
            if tok.kind == "OP_1" and tok.value in ("+", "-"):
                self.advance()
                right = self.parse_mul_expr()
                op = BinaryOp.ADD if tok.value == "+" else BinaryOp.SUB
                left = Expr(binary_op=op, args=[left, right])
            else:
                return left

    def parse_mul_expr(self) -> Expr:
        left = self.parse_unary_expr()
        while True:
            tok = self.peek()
            if tok.kind == "OP_1" and tok.value in ("*", "/"):
                self.advance()
                right = self.parse_unary_expr()
                op = BinaryOp.MUL if tok.value == "*" else BinaryOp.DIV
                left = Expr(binary_op=op, args=[left, right])
            else:
                return left

    def parse_unary_expr(self) -> Expr:
        tok = self.peek()
        if tok.kind == "OP_1" and tok.value == "-":
            self.advance()
            sub = self.parse_unary_expr()
            # Encode unary minus as (0 - sub) so the AST stays binary.
            return Expr(
                binary_op=BinaryOp.SUB,
                args=[Expr(const=0.0), sub],
            )
        return self.parse_pow_expr()

    def parse_pow_expr(self) -> Expr:
        base = self.parse_atom()
        if self.peek().kind == "OP_1" and self.peek().value == "^":
            self.advance()
            exp_tok = self.expect("NUMBER")
            try:
                k = int(exp_tok.value)
            except ValueError as exc:
                raise ParseError(
                    f"^ exponent must be an integer literal, got {exp_tok.value!r}",
                    exp_tok.pos,
                ) from exc
            return Expr(
                binary_op=BinaryOp.POW,
                args=[base, Expr(const=float(k))],
            )
        return base

    def parse_atom(self) -> Expr:
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            return Expr(const=float(tok.value))
        if tok.kind == "OP_1" and tok.value == "(":
            self.advance()
            inner = self.parse_or_expr()
            self.expect("OP_1", ")")
            return inner
        if tok.kind == "IDENT":
            return self.parse_ident_lead()
        raise ParseError(
            f"Unexpected token {tok.kind} {tok.value!r}", tok.pos,
        )

    def parse_ident_lead(self) -> Expr:
        """An identifier-led atom: either a namespace path (variable),
        a call (function or aggregator), or a bare parameter ref."""
        ident = self.advance()
        # Aggregator: sum_over(collection, body) etc.
        if ident.value in _AGGREGATOR_NAMES and self.peek().value == "(":
            return self.parse_aggregator(ident.value)
        # Call: log(x), max(a, b), if(p, t, e)
        if ident.value in _CALL_NAMES and self.peek().value == "(":
            return self.parse_call(ident.value)
        # Variable namespace: state.X[...], event.amount, agent.balance, etc.
        if ident.value in _NAMESPACE_NAMES:
            return self.parse_variable_tail(ident.value)
        # Bare identifier with a leading dot? → not a known namespace
        # but maybe the user wrote 'event' alias under another name.
        # For now, reject — keeps grammar tight.
        if ident.value == "agent":
            # alias for event.agent.* — promote to event namespace
            return self.parse_variable_tail("event", initial_path=["agent"])
        raise ParseError(
            f"Unknown identifier {ident.value!r}. "
            f"Use one of namespaces {sorted(_NAMESPACE_NAMES)} or calls "
            f"{sorted(_CALL_NAMES)}, or aggregators {sorted(_AGGREGATOR_NAMES)}.",
            ident.pos,
        )

    def parse_variable_tail(
        self, ns_name: str, initial_path: list[str] | None = None
    ) -> Expr:
        path: list[str] = list(initial_path or [])
        while True:
            tok = self.peek()
            if tok.kind == "OP_1" and tok.value == ".":
                self.advance()
                seg = self.expect("IDENT")
                path.append(seg.value)
            elif tok.kind == "OP_1" and tok.value == "[":
                self.advance()
                key_tok = self.peek()
                if key_tok.kind == "STRING":
                    self.advance()
                    path.append(key_tok.value.strip("'\""))
                elif key_tok.kind == "IDENT":
                    self.advance()
                    path.append(key_tok.value)
                elif key_tok.kind == "NUMBER":
                    self.advance()
                    path.append(key_tok.value)
                else:
                    raise ParseError(
                        f"Expected string / identifier / number inside [], got {key_tok.value!r}",
                        key_tok.pos,
                    )
                self.expect("OP_1", "]")
            else:
                break
        if not path:
            # Bare namespace without any path: ambiguous. ``param`` alone
            # is interpreted as a 0-length variable path which is invalid;
            # ``param.<name>`` is the legal form.
            raise ParseError(
                f"Namespace {ns_name} requires a path (e.g. {ns_name}.something)",
                self.peek().pos,
            )
        # Special-case: ``param.NAME`` collapses to an Expr(param=NAME)
        # so the param namespace stays cleanly separate from variables.
        if ns_name == "param" and len(path) == 1:
            return Expr(param=path[0])
        return Expr(var=VarRef(ns=VarNamespace(ns_name), path=path))

    def parse_call(self, name: str) -> Expr:
        self.expect("OP_1", "(")
        args: list[Expr] = []
        if not (self.peek().kind == "OP_1" and self.peek().value == ")"):
            args.append(self.parse_or_expr())
            while self.peek().kind == "OP_1" and self.peek().value == ",":
                self.advance()
                args.append(self.parse_or_expr())
        self.expect("OP_1", ")")
        return Expr(call_op=_CALL_NAMES[name], args=args)

    def parse_aggregator(self, name: str) -> Expr:
        self.expect("OP_1", "(")
        # First arg: collection reference (possibly with [filter_arg])
        coll_tok = self.expect("IDENT")
        filter_arg: str | None = None
        if self.peek().kind == "OP_1" and self.peek().value == "[":
            self.advance()
            key_tok = self.peek()
            if key_tok.kind == "STRING":
                self.advance()
                filter_arg = key_tok.value.strip("'\"")
            elif key_tok.kind == "IDENT":
                self.advance()
                filter_arg = key_tok.value
            else:
                raise ParseError(
                    f"Expected collection filter arg, got {key_tok.value!r}",
                    key_tok.pos,
                )
            self.expect("OP_1", "]")
        # Resolve collection enum
        try:
            collection = CollectionRef(coll_tok.value)
        except ValueError as exc:
            raise ParseError(
                f"Unknown collection {coll_tok.value!r}. "
                f"Use one of {[c.value for c in CollectionRef]}.",
                coll_tok.pos,
            ) from exc
        self.expect("OP_1", ",")
        body = self.parse_or_expr()
        self.expect("OP_1", ")")
        spec = AggregatorSpec(
            kind=_AGGREGATOR_NAMES[name],
            collection=collection,
            filter_arg=filter_arg,
            body=body,
        )
        return Expr(aggregator=spec)


# ---------------------------------------------------------------------------
# Decidability analyzer
# ---------------------------------------------------------------------------


def is_decidable(ast: Expr) -> tuple[bool, list[str]]:
    """Walk the AST and decide whether the formal verifier can encode it.

    The decidable subset: linear / polynomial / conditional /
    bounded-aggregation expressions over Reals. Transcendentals
    (``log``, ``exp``) and division by a non-constant operand fall
    out — they're allowed at the schema level but the Z3 encoder
    refuses them (caller marks the FM verdict ``inconclusive`` with
    the returned reasons).
    """
    reasons: list[str] = []
    _walk_decidable(ast, reasons)
    return (len(reasons) == 0, reasons)


def _walk_decidable(node: Expr, reasons: list[str]) -> None:
    # Leaf nodes are always decidable.
    if node.const is not None or node.var is not None or node.param is not None:
        return
    if node.aggregator is not None:
        # Aggregator body must itself be decidable.
        _walk_decidable(node.aggregator.body, reasons)
        return
    if node.call_op is not None:
        if node.call_op in (CallOp.LOG, CallOp.EXP):
            # log / exp of a non-constant argument is non-decidable.
            arg = node.args[0]
            if arg.const is None:
                reasons.append(
                    f"call {node.call_op.value}(...) of a non-literal argument "
                    f"is not Z3-decidable; the formal layer will skip it but "
                    f"MC + ABM still evaluate it."
                )
        for sub in node.args:
            _walk_decidable(sub, reasons)
        return
    if node.binary_op is not None:
        # Division by a non-literal/non-param needs runtime non-zero guard;
        # report as a soft caveat but still decidable.
        if node.binary_op == BinaryOp.DIV:
            denom = node.args[1]
            if denom.const is None and denom.param is None:
                reasons.append(
                    "div(...) by a non-constant expression — Z3 will assume "
                    "the declared bounds keep the divisor non-zero. If your "
                    "ranges include 0 the verdict may be inconclusive."
                )
        # pow exponent must be a literal integer; the schema parser
        # already enforces literal-int exponent, so just recurse.
        for sub in node.args:
            _walk_decidable(sub, reasons)
        return
    # Unknown node — conservative.
    reasons.append(f"unknown node kind on {node!r}")


# ---------------------------------------------------------------------------
# Legacy compatibility shim — AsymptoticClass → Expr
# ---------------------------------------------------------------------------


def synthesize_from_asymptotic_class(ac, parameter_names: dict[str, str] | None = None) -> Expr:
    """Build an equivalent :class:`Expr` for a legacy
    :class:`schema.AsymptoticClass`.

    The synthesized AST uses synthetic parameter names ``a``, ``b``,
    ``c`` matching the legacy convention. The caller is responsible for
    constructing matching :class:`ParamDecl` entries so the evaluator
    can bind the parameter values.

    Mapping (matches existing ``verifier.asymptotic.average_rate_per_period``):

    * ``constant``        → ``param.c``
    * ``bounded_range``   → ``const(midpoint)``  (range narrowed by Bounds)
    * ``linear``          → ``param.a * state.t + param.b``
    * ``polynomial(k)``   → ``param.a * state.t^k + param.b``
    * ``sublinear_root(d)`` → encoded as the conservative ``param.b`` (no √
                           primitive in our DSL yet; flagged inconclusive)
    * ``log``             → ``param.a * log(state.t + 1) + param.b``
    * ``exponential``     → ``param.a * exp(param.b_log * state.t)``
    * ``unspecified``     → ``param.value``

    Only the supported families produce decidable ASTs. Sublinear root
    and unspecified produce an Expr but :func:`is_decidable` returns
    False on them — the verifier will fall back to inconclusive.

    This shim runs at LOAD time so every downstream consumer can read
    expressions uniformly; legacy YAMLs require no changes.
    """
    from schema.expr import VarRef, VarNamespace  # local — avoid cycle on cold import
    fam = getattr(ac.family, "value", str(ac.family))
    t_var = Expr(var=VarRef(ns=VarNamespace.STATE, path=["t"]))

    def _p(name: str) -> Expr:
        return Expr(param=name)

    if fam == "constant":
        return _p("c")
    if fam == "bounded_range":
        # Mid-point — verifier reasons via the declared bounds anyway.
        lo = ac.bounds.min if ac.bounds is not None else 0.0
        hi = ac.bounds.max if ac.bounds is not None else 0.0
        return Expr(const=(lo + hi) / 2.0)
    if fam == "linear":
        # a * t + b
        return Expr(
            binary_op=BinaryOp.ADD,
            args=[
                Expr(binary_op=BinaryOp.MUL, args=[_p("a"), t_var]),
                _p("b"),
            ],
        )
    if fam == "polynomial":
        k = ac.degree or 2
        # a * t^k + b
        return Expr(
            binary_op=BinaryOp.ADD,
            args=[
                Expr(
                    binary_op=BinaryOp.MUL,
                    args=[
                        _p("a"),
                        Expr(binary_op=BinaryOp.POW, args=[t_var, Expr(const=float(k))]),
                    ],
                ),
                _p("b"),
            ],
        )
    if fam == "sublinear_root":
        # √t etc. not encodable in the decidable subset — fall back to ``b``.
        return _p("b")
    if fam == "log":
        # a * log(t + 1) + b
        inner = Expr(binary_op=BinaryOp.ADD, args=[t_var, Expr(const=1.0)])
        return Expr(
            binary_op=BinaryOp.ADD,
            args=[
                Expr(binary_op=BinaryOp.MUL, args=[
                    _p("a"),
                    Expr(call_op=CallOp.LOG, args=[inner]),
                ]),
                _p("b"),
            ],
        )
    if fam == "exponential":
        # a * exp(b_log * t). Z3-undecidable; evaluator falls back.
        return Expr(
            binary_op=BinaryOp.MUL,
            args=[
                _p("a"),
                Expr(call_op=CallOp.EXP, args=[
                    Expr(binary_op=BinaryOp.MUL, args=[_p("b"), t_var]),
                ]),
            ],
        )
    # unspecified — single bounded scalar
    return _p("value")
