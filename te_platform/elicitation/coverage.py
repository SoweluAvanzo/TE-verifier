## =============================================================================
## te_platform/elicitation/coverage.py — checks behind the protocol's coverage tests
## =============================================================================
## GUIDE STEP   7.2
## PURPOSE      Functions returning a list of problems (empty = OK), used by
##              tests/platform_tests/test_platform_elicitation.py:
##              - paper_source_problems: the table PAPER_VARIABLE_SOURCES
##                below agrees with verifier/paper.py and with the schema;
##              - missing_paper_parameters: every variable of the six failure
##                modes can be computed from fields the protocol asks;
##              - unknown_ir_paths: every slot's ir_path exists in the TE-IR
##                schema (schema.TokenEconomy);
##              - routing_reads_later_slots: every applies_when rule only
##                reads slots asked BEFORE the slot/stage that uses it.
##              ("Coverage" here means the questions cover every needed
##              parameter; it is unrelated to the test coverage of code.)
## HOW A VARIABLE COUNTS AS ASKED
##              verifier/paper.py gives some variables a direct field
##              (PaperVariable.elicitation_field, e.g. N ->
##              participants.count_N) and others only a free-text
##              derivation_source (M(t), V, tau_bar, phi, T - R), which no
##              ir_path
##              can equal. So the IR fields each variable is COMPUTED from are
##              written down here, explicitly, in PAPER_VARIABLE_SOURCES: a
##              tuple of alternatives, each a tuple of IR paths that must ALL
##              be asked (tau_bar needs every agent type's holding time AND
##              balance share; gamma is asked directly OR derived from the contribution
##              verification). The table is itself checked: it must name
##              every paper variable, contain each variable's
##              elicitation_field, and use only paths that exist in the
##              schema. A path counts as asked when a slot that ALWAYS applies
##              (no applies_when on the slot or its stage) fills it or one of
##              its parents (a `table` slot for participants.agent_types
##              fills every agent type's fields); "[]" is ignored in the
##              comparison. Slots that apply only to some designs do not
##              count: for the other designs the variable would never be
##              asked.
## USED BY      tests only (and optionally a startup check in mcp_server).
## DEPENDS ON   protocol.py, routing.py, paths.py (field_type),
##              verifier.paper.ALL_CONDITIONS.
## WHY          The project's rigour requirement (CLAUDE.md): the interview is
##              PROVEN to collect everything the verifier needs, the same way
##              the "field coverage matrix" of docs/specification-flow.md
##              claims it — but checked by code. The derivations follow
##              verifier/elicitation.py (gamma_range_from, temptation_gap_from,
##              contributor_fraction_from) and the failure modes.
## ACTIVATE     Uncomment with guide 7.2, together with the tests.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the public names exactly:
## the tests call them. Activate protocol.py, paths.py and routing.py first.
##
## Guide 7.2
## [ ] 1. Imports at the top: `ALL_CONDITIONS` from verifier.paper,
##        `routing` from te_platform.elicitation, `field_type` from
##        elicitation.paths, `Protocol` from elicitation.protocol.
## [ ] 2. `PAPER_VARIABLE_SOURCES: dict[str, tuple[tuple[str, ...], ...]]`:
##        copy the table of the SOLUTION (one entry per paper symbol; the
##        comments say where each derivation comes from).
##          | "N": (("participants.count_N",),),
## [ ] 3. `paper_source_problems() -> list[str]`: a problem for every paper
##        symbol missing from the table and every table symbol the paper
##        does not have; for every variable whose elicitation_field is not
##        a one-path alternative of its entry; for every table path where
##        field_type(path) is None.
## [ ] 4. `_plain(path)`: the path without spaces and without "[]".
##        `_always_asked(protocol)`: the plain ir_paths of the slots whose
##        slot AND stage have applies_when None.
## [ ] 5. `missing_paper_parameters(protocol)`: a path is asked when it
##        equals an asked path or lies below one (asked + "."); a variable
##        is covered when ALL paths of SOME alternative are asked; otherwise
##        add "FMx: variable <symbol> needs <paths> (none asked)".
## [ ] 6. `unknown_ir_paths(protocol)`: one problem string per slot whose
##        ir_path has no field_type.
## [ ] 7. `routing_reads_later_slots(protocol)`: number every slot by its
##        position in ordered_slots(). For each slot, check the stage's and
##        the slot's applies_when: report an unknown rule name, and every
##        slot id in the rule's `reads` that is not at an earlier position.
## [ ] 8. Check: activate the 7.2 coverage tests in
##        tests/platform_tests/test_platform_elicitation.py, then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##        test_every_failure_mode_parameter_is_asked stays xfail until the
##        protocol is complete; run it with --runxfail to see what is missing.
##        test_a_complete_protocol_covers_every_parameter shows that a
##        complete protocol (a test fixture) passes these checks.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from verifier.paper import ALL_CONDITIONS

from te_platform.elicitation import routing
from te_platform.elicitation.paths import field_type
from te_platform.elicitation.protocol import Protocol

## Paper symbol -> alternatives -> IR paths that must all be asked.
## Keys are PaperVariable.symbol values of verifier/paper.py.
PAPER_VARIABLE_SOURCES: dict[str, tuple[tuple[str, ...], ...]] = {
    # FM1, FM3: E(t) = rule function x trigger frequency (the triggers are
    # part of each rule; event-catalog triggers also need `events`).
    "E(t)": (("tokens[].emission_rules",),),
    "B(t)": (("tokens[].burn_rules",),),
    # M(t) = initial distribution + cumulative E(t) - B(t).
    "M(t)": (("tokens[].initial_distribution", "tokens[].emission_rules", "tokens[].burn_rules"),),
    "g(t)": (("participants.growth_g",),),
    # FM2: V >= 1/tau_bar, tau_bar = sum over agent types of (M_i/M) E_i[tau].
    "V": (
        (
            "participants.agent_types[].expected_holding_time",
            "participants.agent_types[].balance_share",
        ),
    ),
    "τ̄": (
        (
            "participants.agent_types[].expected_holding_time",
            "participants.agent_types[].balance_share",
        ),
    ),
    "Q": (("participants.expected_Q",),),
    "N": (("participants.count_N",),),
    "K": (("tokens[].offer_variety_K",),),
    "d": (("participants.average_demand_d",),),
    # FM4: phi = share of agent types whose role is contributor
    # (verifier.elicitation.contributor_fraction_from).
    "φ": (("participants.agent_types[].role", "participants.agent_types[].fraction"),),
    # gamma directly, or derived from the verification mechanism
    # (verifier.elicitation.gamma_range_from).
    "γ": (  # noqa: RUF001  the paper's symbol
        ("governance.monitoring_capacity_gamma",),
        ("tokens[].contribution_verification",),
    ),
    "S": (("governance.sanction_structure",),),
    # T - R from (verification, redemption) (verifier.elicitation.temptation_gap_from).
    "T − R": (  # noqa: RUF001  the paper's symbol
        (
            "tokens[].contribution_verification",
            "tokens[].redemption_mechanism",
        ),
    ),
    "Γ": (("governance.rule_structure",),),
    "G": (("governance.token_balance_gini",),),
}


def paper_source_problems() -> list[str]:
    """Check PAPER_VARIABLE_SOURCES against verifier/paper.py and the schema."""
    variables = {v.symbol: v for c in ALL_CONDITIONS.values() for v in c.variables}
    table = PAPER_VARIABLE_SOURCES
    return [
        *(
            f"paper variable {s} has no entry in PAPER_VARIABLE_SOURCES"
            for s in sorted(set(variables) - set(table))
        ),
        *(
            f"PAPER_VARIABLE_SOURCES names {s}, unknown to the paper"
            for s in sorted(set(table) - set(variables))
        ),
        # The paper's own field must be one of the alternatives.
        *(
            f"{s}: the paper's field {v.elicitation_field} is not an alternative"
            for s, v in variables.items()
            if v.elicitation_field and (v.elicitation_field,) not in table.get(s, ())
        ),
        *(
            f"{s}: {path} is not a TE-IR field"
            for s, alternatives in table.items()
            for alt in alternatives
            for path in alt
            if field_type(path) is None
        ),
    ]


def _plain(path: str) -> str:
    """Compare paths without spaces and without list markers."""
    return path.replace(" ", "").replace("[]", "")


def _always_asked(protocol: Protocol) -> set[str]:
    """Return the plain ir_paths of the slots that apply to every design."""
    return {
        _plain(sl.ir_path)
        for st, sl in protocol.ordered_slots()
        if st.applies_when is None and sl.applies_when is None
    }


def missing_paper_parameters(protocol: Protocol) -> list[str]:
    """List the failure-mode variables that no always-asked slot provides."""
    asked = _always_asked(protocol)

    def is_asked(path: str) -> bool:
        p = _plain(path)
        return any(p == a or p.startswith(a + ".") for a in asked)

    problems = []
    for fm, cond in ALL_CONDITIONS.items():
        for var in cond.variables:
            alternatives = PAPER_VARIABLE_SOURCES.get(var.symbol, ())
            if not any(all(is_asked(p) for p in alt) for alt in alternatives):
                needs = " or ".join(" + ".join(alt) for alt in alternatives)
                problems.append(f"{fm}: variable {var.symbol} needs {needs} (none asked)")
    return problems


def unknown_ir_paths(protocol: Protocol) -> list[str]:
    """List the slots whose ir_path is not a TE-IR field."""
    return [
        f"slot {sl.id}: {sl.ir_path} is not a TE-IR field"
        for _, sl in protocol.ordered_slots()
        if field_type(sl.ir_path) is None
    ]


def routing_reads_later_slots(protocol: Protocol) -> list[str]:
    """List the routing rules that read a slot not asked before them."""
    position = {sl.id: n for n, (_, sl) in enumerate(protocol.ordered_slots())}
    problems = []
    for n, (stage, slot) in enumerate(protocol.ordered_slots()):
        for rule_name in (stage.applies_when, slot.applies_when):
            if rule_name is None:
                continue
            if rule_name not in routing.ROUTING_RULES:
                problems.append(f"slot {slot.id}: unknown routing rule {rule_name}")
                continue
            problems += [
                f"slot {slot.id}: rule {rule_name} reads {read}, which is not asked earlier"
                for read in routing.ROUTING_RULES[rule_name].reads
                if position.get(read, n) >= n
            ]
    return problems
