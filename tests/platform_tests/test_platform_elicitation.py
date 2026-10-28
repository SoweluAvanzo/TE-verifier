## =============================================================================
## tests/platform_tests/test_platform_elicitation.py — tests for te_platform/elicitation/
## =============================================================================
## GUIDE STEP   7.1-7.5 (7.1 single-commented; 7.2-7.5 in labelled
##              twice-commented blocks: activate each with the code it tests)
## PURPOSE      Specifies, as executable checks, what the interview machinery
##              must do: the protocol file loads and is strict; IR paths are
##              read and written correctly; the protocol covers every
##              parameter the six failure modes need (and a COMPLETE protocol
##              provably does); every case study in examples/ is reproduced
##              by answering the protocol with its values (7.3); answers are
##              written in the shape of their
##              field ("unknown" -> swept range); the ranking puts the most
##              verdict-relevant question first and stops when nothing
##              unknown can change a verdict.
## FIXTURE      _complete_protocol() (guide 7.2 block) is a test-only protocol
##              with every stage the interview needs (1-5, 7-9; Stage 6 is out
##              of scope, see the protocol file's header). It proves that the
##              coverage mechanism passes on a complete protocol and drives
##              an end-to-end interview with the real verifier. It is NOT the
##              protocol: writing policy/elicitation_protocol.yaml stage by
##              stage is guide 7.2's work.
## DATA         case_study_differences.yaml (next to this file, guide 7.3):
##              the fields of the case studies that no slot asks, each with
##              its reason; the 7.3 replay may differ from an example there
##              and nowhere else.
## RUN          uv run pytest tests/platform_tests/test_platform_elicitation.py -v
## WHY          Guide §0.3 "write the test first": each test below is the
##              specification of one behaviour. Uncomment a test BEFORE the
##              code it checks, watch it fail, then activate the code.
## NOTE         While everything is commented out pytest collects 0 tests from
##              this file; that is expected and harmless.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, GUIDE STEP).
## Write each test BEFORE the code it checks and watch it fail (header WHY).
##
## Guide 7.1
## [ ] 1. Imports: Path, pytest, field_type, get_value, has_value,
##        index_combos and set_value (elicitation.paths), Slot and
##        load_protocol (elicitation.protocol), InvalidInput. Constants
##        PROTOCOL_PATH = Path("policy/elicitation_protocol.yaml") and
##        EXAMPLES = Path("examples").
## [ ] 2. test_real_protocol_loads: load_protocol(PROTOCOL_PATH).version
##        is set.
## [ ] 3. test_unknown_key_is_rejected(tmp_path): a small protocol file
##        with an extra "typo: 1" key makes load_protocol raise.
## [ ] 4. Helper `_slot(**kw) -> Slot`: a decisive "range" slot
##        participants.N -> participants.count_N with allow_unknown=True
##        and unknown_range=(2, 1000); keyword arguments override fields.
##        test_allow_unknown_requires_a_meaning (also for a table slot),
##        test_slot_shapes_are_checked (enum without choices, a list slot
##        whose path has no "[]." field, unknown_range on a table slot).
## [ ] 5. Paths: test_field_type_follows_the_schema (lists need "[]", dict
##        keys are free, unknown fields give None),
##        test_index_combos_and_values (one combo per token; get/has_value
##        with explicit null, missing key, missing index),
##        test_set_value_never_creates_list_elements.
## [ ] 6. Check:
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -v
##
## Guide 7.2 (twice-commented, labelled)
## [ ] 7. Imports: `coverage, routing` from te_platform.elicitation and
##        Protocol (elicitation.protocol).
## [ ] 8. test_every_ir_path_exists, test_routing_rules_only_read_earlier_
##        slots, test_paper_variable_sources_match_paper_and_schema: each
##        coverage function returns [].
## [ ] 9. test_every_failure_mode_parameter_is_asked:
##        coverage.missing_paper_parameters(protocol) is [], marked
##          | @pytest.mark.xfail(strict=True, reason="...")
##        while the protocol is incomplete (the solution's `##` note says
##        why, and when to delete the marker).
## [ ] 10. The fixture `_complete_protocol()` (copy it from the SOLUTION)
##        and test_a_complete_protocol_covers_every_parameter: the three
##        coverage functions return [] on it — the proof that finishing the
##        protocol makes the xfail test pass.
## [ ] 11. Routing: test_routing_reads_the_spec (network_topology,
##        multi_token from the archetype or from two token ids,
##        pegged_or_external_anchor from an anchor), on whole specs with no
##        answers recorded.
## [ ] 12. Check: the step 6 command; to list the missing questions, run
##        the `-k parameter_is_asked --runxfail` command from that note.
##
## Guide 7.3 (twice-commented, labelled)
## [ ] 13. Imports under 7.3 labels: `yaml`, and `service` from
##        te_platform (7.4 and 7.5 use them too). Constants DIFFERENCES_PATH (case_study_differences.yaml next to
##        this file) and CASE_STUDIES (the stems of examples/*.yaml).
## [ ] 14. Helpers: `_record_phase73(spec, slot, value, indices)` writes one
##        answer with set_value (a `list` slot creates the list, one element
##        per value) and `_record = _record_phase73`; `_replay(protocol,
##        example)` walks protocol.ordered_slots() on an empty spec, skips a
##        slot whose stage or slot routing rule is false ON THE SPEC BUILT
##        SO FAR, and records the example's value at the slot's ir_path for
##        every index combo of the replayed spec:
##          | for combo in index_combos(spec, slot.ir_path):
##          |     if has_value(example, slot.ir_path, combo): ...
##        `_differences(example, replayed)`: the generalised paths
##        ("tokens[].transferable") where the replay lacks or changes a
##        value; `_with_documented_fields`: copy the documented paths from
##        the example into the replay.
## [ ] 15. test_case_study_is_reproduced_by_the_protocol, for every example
##        and two protocols (the complete fixture, and the real file marked
##        xfail(strict=True) while it is incomplete, as in step 9): no
##        undocumented difference, and with the documented fields filled in
##        the replay has the example's spec_hash (service.validate).
##        test_every_documented_difference_is_needed: every entry has a
##        kind and a reason, and is a difference of at least one example.
## [ ] 16. Write case_study_differences.yaml (its own TO-DO list).
## [ ] 17. Check:
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -k case_study -v
##        At 7.4, `_record` is rebound to apply_answer (step 19): every
##        case-study value must then also pass the answer checks.
##
## Guide 7.4 (twice-commented, labelled)
## [ ] 18. Import apply_answer.
## [ ] 19. `_record_phase74` (apply_answer with status "committed") and
##          | _record = _record_phase74
##        so the 7.3 replay records answers as elicit.record_answer.v1 will.
##        test_point_answer_becomes_point_range,
##        test_unknown_becomes_swept_range, test_per_token_path_uses_indices,
##        test_input_spec_is_not_modified (apply_answer returns a NEW dict).
## [ ] 20. Shapes: test_answers_take_the_shape_of_their_field (an enum
##        into tokens[].function becomes a list, a number into an NFR
##        rating an int, a non-whole number is refused, a wrong value or a
##        wrong table is refused), test_list_slot_creates_and_names_tokens,
##        test_unknown_needs_permission.
## [ ] 21. test_every_unknown_meaning_fits_the_schema (real protocol and
##        fixture) and test_swept_complete_protocol_is_a_valid_spec
##        (service.validate on the fixture answered "unknown" everywhere
##        it may be, plus the required answers).
## [ ] 22. Check: the step 6 command.
##
## Guide 7.5 (twice-commented, labelled)
## [ ] 23. Imports under their labels: copy, re, and from ranking
##        next_questions, open_decisive_slots and _shift_key_to_path.
## [ ] 24. test_whole_spec_has_no_open_decisive_slots (bitcoin,
##        axie_infinity, time_bank), test_removed_decisive_slot_is_asked_
##        first (for each example and each decisive slot it fills: remove
##        the value, it is asked first), test_complete_spec_is_complete
##        (every open item answered -> complete, nothing asked),
##        test_invalid_partial_spec_falls_back_to_protocol_order,
##        test_every_verifier_shift_key_is_mapped and
##        test_an_interview_on_the_complete_protocol_finishes (answer what
##        is asked until complete; the spec is then valid).
## [ ] 25. Check: the step 6 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Phase 7.5: copies of example specs, the shift-key scan.
import copy
import re
from pathlib import Path

import pytest

## Phase 7.3: example specs and the documented differences (7.5 reads examples too).
import yaml

## Phase 7.3: spec hashes of the replayed case studies (7.4: swept specs).
from te_platform import service

## Phase 7.2: coverage checks and routing rules.
from te_platform.elicitation import coverage, routing

## Phase 7.4: writing answers.
from te_platform.elicitation.answers import apply_answer
from te_platform.elicitation.paths import (
    field_type,
    get_value,
    has_value,
    index_combos,
    set_value,
)
from te_platform.elicitation.protocol import Slot, load_protocol

## Phase 7.2: the complete fixture is built as a Protocol.
from te_platform.elicitation.protocol import Protocol

## Phase 7.5: the verifier-driven ranking.
from te_platform.elicitation.ranking import (
    _shift_key_to_path,
    _value_schema,
    next_questions,
    open_decisive_slots,
)
from te_platform.errors import InvalidInput

PROTOCOL_PATH = Path("policy/elicitation_protocol.yaml")
EXAMPLES = Path("examples")


## --- 7.1 protocol schema --------------------------------------------------------


def test_real_protocol_loads():
    # The committed protocol must always be valid: a broken file would stop
    # the interview for every user.
    protocol = load_protocol(PROTOCOL_PATH)
    assert protocol.version


def test_unknown_key_is_rejected(tmp_path):
    # extra="forbid": a typo such as "critcality" must fail loudly instead of
    # silently dropping the field.
    bad = tmp_path / "p.yaml"
    bad.write_text("protocol: x\nversion: '0'\nstages: []\ntypo: 1\n")
    with pytest.raises(ValueError, match="typo"):
        load_protocol(bad)


def _slot(**kw) -> Slot:
    base = dict(
        id="participants.N",
        ir_path="participants.count_N",
        criticality="decisive",
        answer_type="range",
        allow_unknown=True,
        unknown_range=(2, 1000),
        intent="i",
        why_we_ask="FM5",
    )
    return Slot(**{**base, **kw})


def test_allow_unknown_requires_a_meaning():
    # A slot that allows "I don't know" must say what it is written as.
    with pytest.raises(ValueError, match="allow_unknown"):
        _slot(unknown_range=None)
    with pytest.raises(ValueError, match="allow_unknown"):
        _slot(answer_type="table", ir_path="participants.agent_types", unknown_range=None)


def test_slot_shapes_are_checked():
    with pytest.raises(ValueError, match="choices"):
        _slot(
            answer_type="enum",
            ir_path="participants.topology",
            unknown_range=None,
            unknown_value="well_mixed",
        )
    with pytest.raises(ValueError, match="list slot"):
        _slot(answer_type="list", ir_path="tokens", allow_unknown=False, unknown_range=None)
    with pytest.raises(ValueError, match="unknown_range"):
        _slot(answer_type="table", ir_path="participants.agent_types")


## --- 7.1 paths --------------------------------------------------------------------


def test_field_type_follows_the_schema():
    assert field_type("participants.count_N") is not None
    assert field_type("tokens[].offer_variety_K") is not None
    assert field_type("tokens.offer_variety_K") is None  # tokens is a list: "[]" needed
    assert field_type("participants.topology_params.average_degree") is not None  # dict key
    assert field_type("participants.no_such_field") is None
    assert field_type("meta.nfrs.resilience") is int


def test_index_combos_and_values():
    spec = {
        "participants": {"count_N": {"min": 10, "max": 10}, "topology": None},
        "tokens": [{"offer_variety_K": 3}, {"id": "B"}],
    }
    assert index_combos(spec, "participants.count_N") == [()]
    assert index_combos(spec, "tokens[].offer_variety_K") == [(0,), (1,)]
    assert index_combos({}, "tokens[].offer_variety_K") == []  # no tokens yet
    assert has_value(spec, "participants.count_N")
    assert not has_value(spec, "participants.topology")  # explicit null
    assert not has_value(spec, "participants.average_demand_d")  # missing key
    assert get_value(spec, "tokens[].offer_variety_K", (0,)) == 3
    assert not has_value(spec, "tokens[].offer_variety_K", (1,))  # field missing
    assert not has_value(spec, "tokens[].offer_variety_K", (2,))  # no third token


def test_set_value_never_creates_list_elements():
    doc = {"tokens": [{"id": "A"}]}
    set_value(doc, "participants.count_N", 5)
    set_value(doc, "tokens[].offer_variety_K", 7, (0,))
    assert doc == {"tokens": [{"id": "A", "offer_variety_K": 7}], "participants": {"count_N": 5}}
    with pytest.raises(InvalidInput):
        set_value(doc, "tokens[].offer_variety_K", 7, (1,))  # there is no second token
    with pytest.raises(InvalidInput):
        set_value(doc, "tokens[].offer_variety_K", 7)  # which token?


## --- 7.2 coverage -----------------------------------------------------------------


## Phase 7.2: the protocol's coverage tests (guide 7.2 "Done when").
def test_every_ir_path_exists():
    assert coverage.unknown_ir_paths(load_protocol(PROTOCOL_PATH)) == []


## Phase 7.2
def test_routing_rules_only_read_earlier_slots():
    assert coverage.routing_reads_later_slots(load_protocol(PROTOCOL_PATH)) == []


## Phase 7.2: the derivation table agrees with verifier/paper.py and the schema.
def test_paper_variable_sources_match_paper_and_schema():
    assert coverage.paper_source_problems() == []


## Phase 7.2. The protocol is complete (all stages of guide 7.2), so every
## failure-mode variable is asked by an always-applying slot. (While the
## protocol had only stages 1 and 8 this test carried
## xfail(strict=True); the marker was deleted when the protocol was
## completed. To list missing questions after a change, run
##   uv run pytest tests/platform_tests/test_platform_elicitation.py -k parameter_is_asked)
def test_every_failure_mode_parameter_is_asked():
    assert coverage.missing_paper_parameters(load_protocol(PROTOCOL_PATH)) == []


## Phase 7.2: the test-only complete protocol (header, FIXTURE). Each slot is
## (id, ir_path, criticality, answer_type, extra fields); intent and
## why_we_ask are filled in by _complete_protocol.
_UNKNOWN_EMISSION = [
    {"trigger": {"kind": "time_based"}, "function": {"asymptotic_class": {"family": "unspecified"}}}
]
_UNKNOWN_BURN = [
    {
        "trigger": {"kind": "rule_driven"},
        "function": {"asymptotic_class": {"family": "unspecified"}},
    }
]
_NO_UNKNOWN = {"allow_unknown": False}
_STAGES = [
    (
        "S1_archetype",
        1,
        None,
        [
            ("meta.name", "meta.name", "bookkeeping", "text", {"unknown_value": "Unnamed"}),
            (
                "meta.archetype",
                "meta.archetype",
                "decisive",
                "enum",
                {
                    "choices": [
                        "native_protocol_asset",
                        "stablecoin",
                        "governance_utility_pair",
                        "play_to_earn_dual",
                        "community_reward",
                        "other",
                    ],
                    "unknown_value": "other",
                    "feeds": ["FM1", "FM2", "FM3", "FM4", "FM5", "FM6"],
                },
            ),
        ],
    ),
    (
        "S2_tokens",
        2,
        None,
        [
            ("tokens.ids", "tokens[].id", "decisive", "list", _NO_UNKNOWN),
            (
                "tokens.function",
                "tokens[].function",
                "decisive",
                "enum",
                {
                    "choices": [
                        "medium_of_exchange",
                        "unit_of_account",
                        "governance_right",
                        "access_right",
                        "store_of_value",
                        "reputation_marker",
                    ],
                    "allow_unknown": False,
                    "feeds": ["FM1", "FM2", "FM3"],
                },
            ),
            (
                "tokens.value_anchor",
                "tokens[].value_anchor",
                "important",
                "enum",
                {
                    "choices": [
                        "none",
                        "physical_quantity",
                        "market_price",
                        "pegged",
                        "service_or_access_unit",
                    ],
                    "allow_unknown": False,
                },
            ),
            (
                "tokens.earning",
                "tokens[].earning_mechanisms",
                "bookkeeping",
                "enum",
                {
                    "choices": [
                        "airdrop",
                        "behavioral_reward",
                        "resource_contribution",
                        "exchange_purchase",
                        "algorithmic_issuance",
                    ],
                    "allow_unknown": False,
                },
            ),
            (
                "tokens.holding",
                "tokens[].holding_incentives",
                "important",
                "enum",
                {
                    "choices": [
                        "none",
                        "tiered_redemption",
                        "governance_rights",
                        "staking",
                        "reputation",
                        "time_locked_rewards",
                    ],
                    "allow_unknown": False,
                    "feeds": ["FM2"],
                },
            ),
            (
                "tokens.verification",
                "tokens[].contribution_verification",
                "important",
                "enum",
                {
                    "choices": [
                        "physical_presence",
                        "peer_verification",
                        "smart_contract_automation",
                        "self_reporting",
                        "third_party_certification",
                        "unspecified",
                    ],
                    "unknown_value": "unspecified",
                    "feeds": ["FM4"],
                },
            ),
            (
                "tokens.redemption",
                "tokens[].redemption_mechanism",
                "important",
                "enum",
                {
                    "choices": [
                        "specific_goods_or_services",
                        "time_based_borrowing",
                        "fungible_access",
                        "open_market_exchange",
                        "peer_to_peer_transfer",
                        "unspecified",
                    ],
                    "unknown_value": "unspecified",
                    "feeds": ["FM4"],
                },
            ),
        ],
    ),
    (
        "S3_emission",
        3,
        None,
        [
            ("events", "events", "important", "table", _NO_UNKNOWN),
            (
                "tokens.emission",
                "tokens[].emission_rules",
                "decisive",
                "dsl_expression",
                {"unknown_value": _UNKNOWN_EMISSION, "feeds": ["FM1", "FM3"]},
            ),
            (
                "tokens.initial_distribution",
                "tokens[].initial_distribution",
                "bookkeeping",
                "table",
                _NO_UNKNOWN,
            ),
        ],
    ),
    (
        "S4_burn",
        4,
        None,
        [
            (
                "tokens.burn",
                "tokens[].burn_rules",
                "decisive",
                "dsl_expression",
                {"unknown_value": _UNKNOWN_BURN, "feeds": ["FM1", "FM3"]},
            ),
        ],
    ),
    (
        "S5_flows",
        5,
        "multi_token",
        [
            ("cross_token_flows", "cross_token_flows", "important", "table", _NO_UNKNOWN),
        ],
    ),
    (
        "S7_governance",
        7,
        None,
        [
            (
                "governance.type",
                "governance.type",
                "decisive",
                "enum",
                {
                    "choices": ["centralized", "committee", "dao", "algorithmic", "hybrid"],
                    "allow_unknown": False,
                    "feeds": ["FM6"],
                },
            ),
            # No levers declared: FM6 reports "inconclusive", the honest "unknown".
            (
                "governance.rule_structure",
                "governance.rule_structure",
                "decisive",
                "table",
                {"unknown_value": {}, "feeds": ["FM6"]},
            ),
            (
                "governance.gamma",
                "governance.monitoring_capacity_gamma",
                "important",
                "range",
                {"unknown_range": (0, 1), "feeds": ["FM4"]},
            ),
            (
                "governance.sanction",
                "governance.sanction_structure",
                "important",
                "table",
                {"allow_unknown": False, "feeds": ["FM4"]},
            ),
            (
                "governance.gini",
                "governance.token_balance_gini",
                "bookkeeping",
                "range",
                {"unknown_range": (0, 1), "feeds": ["FM6"]},
            ),
        ],
    ),
    (
        "S8_participants",
        8,
        None,
        [
            (
                "participants.N",
                "participants.count_N",
                "decisive",
                "range",
                {"unknown_range": (2, 100000), "feeds": ["FM5"]},
            ),
            (
                "participants.d",
                "participants.average_demand_d",
                "decisive",
                "range",
                {"unknown_range": (0.1, 20), "feeds": ["FM4", "FM5"]},
            ),
            (
                "participants.topology",
                "participants.topology",
                "important",
                "enum",
                {
                    "choices": ["well_mixed", "spatial", "network"],
                    "unknown_value": "well_mixed",
                    "feeds": ["FM5"],
                },
            ),
            (
                "participants.network_degree",
                "participants.topology_params.average_degree",
                "bookkeeping",
                "range",
                {"unknown_range": (1, 50), "feeds": ["FM5"], "applies_when": "network_topology"},
            ),
            (
                "tokens.K",
                "tokens[].offer_variety_K",
                "decisive",
                "range",
                {"unknown_range": (1, 100), "feeds": ["FM4", "FM5"]},
            ),
            (
                "participants.Q",
                "participants.expected_Q",
                "important",
                "range",
                {"unknown_range": (0, 1e9), "feeds": ["FM1"]},
            ),
            (
                "participants.growth_g",
                "participants.growth_g",
                "important",
                "table",
                {
                    "unknown_value": {
                        "family": "unspecified",
                        "parameter_ranges": {"value": {"min": -0.5, "max": 1.0}},
                    },
                    "feeds": ["FM3"],
                },
            ),
            (
                "participants.agent_types",
                "participants.agent_types",
                "important",
                "table",
                {"allow_unknown": False, "feeds": ["FM2", "FM4"]},
            ),
        ],
    ),
    (
        "S9_nfrs",
        9,
        None,
        [
            # One slot per declaration; "unknown" = the schema's neutral default.
            *(
                (f"meta.nfrs.{n}", f"meta.nfrs.{n}", "bookkeeping", "number", {"unknown_value": 3})
                for n in (
                    "resilience",
                    "adaptability",
                    "accessibility",
                    "transparency",
                    "proportionality",
                )
            ),
            (
                "meta.nfrs.circulation_speed",
                "meta.nfrs.circulation_speed",
                "bookkeeping",
                "enum",
                {
                    "unknown_value": "balanced",
                    "choices": ["circulate_fast", "balanced", "retain_value"],
                },
            ),
            (
                "meta.nfrs.governance_maturity",
                "meta.nfrs.governance_maturity",
                "bookkeeping",
                "enum",
                {
                    "unknown_value": "medium_term",
                    "choices": ["immediate", "short_term", "medium_term", "indefinite"],
                },
            ),
        ],
    ),
]


## Phase 7.2: build the fixture as a validated Protocol.
def _complete_protocol() -> Protocol:
    stages = [
        {
            "id": sid,
            "title": sid,
            "order": order,
            "applies_when": when,
            "slots": [
                {
                    "id": i,
                    "ir_path": p,
                    "criticality": c,
                    "answer_type": t,
                    "intent": i,
                    "why_we_ask": "FM1",
                    **extra,
                }
                for i, p, c, t, extra in slots
            ],
        }
        for sid, order, when, slots in _STAGES
    ]
    return Protocol.model_validate(
        {"protocol": "complete-fixture", "version": "0", "stages": stages}
    )


## Phase 7.2: the proof that a complete protocol passes the coverage tests.
def test_a_complete_protocol_covers_every_parameter():
    complete = _complete_protocol()
    assert coverage.missing_paper_parameters(complete) == []
    assert coverage.unknown_ir_paths(complete) == []
    assert coverage.routing_reads_later_slots(complete) == []


## Phase 7.2: a slot that applies only to some designs does not count as asked.
def test_conditional_slots_do_not_count_as_asked():
    complete = _complete_protocol().model_dump()
    for stage in complete["stages"]:
        if stage["id"] == "S8_participants":
            stage["applies_when"] = "network_topology"
    missing = coverage.missing_paper_parameters(Protocol.model_validate(complete))
    assert any("variable N " in m for m in missing)


## Phase 7.2: rules read the SPEC, so a spec loaded whole routes correctly.
def test_routing_reads_the_spec():
    p = _complete_protocol()
    network = {"participants": {"topology": "network"}}
    assert routing.applies("network_topology", network, p)
    assert not routing.applies("network_topology", {}, p)  # waits for the answer
    assert routing.applies("multi_token", {"meta": {"archetype": "play_to_earn_dual"}}, p)
    assert routing.applies("multi_token", {"tokens": [{"id": "A"}, {"id": "B"}]}, p)
    assert not routing.applies("multi_token", {"tokens": [{"id": "A"}]}, p)
    pegged = {
        "tokens": [{"id": "A", "value_anchor": "none"}, {"id": "B", "value_anchor": "pegged"}]
    }
    assert routing.applies("pegged_or_external_anchor", pegged, p)
    assert routing.applies("pegged_or_external_anchor", {"meta": {"archetype": "stablecoin"}}, p)
    assert not routing.applies("pegged_or_external_anchor", {"tokens": [{"id": "A"}]}, p)


## --- 7.3 case studies ---------------------------------------------------------------

## Phase 7.3: guide 7.3 "Done when". Replaying a case study is the interview
## its designer would give: walk the protocol in order and answer every slot
## that applies with the value the example file has at the slot's ir_path
## (once per token for "tokens[]..." paths). Fields no slot asks cannot come
## out of an interview; they are listed, each with its reason, in
## DIFFERENCES_PATH. The replay may differ from the example there and nowhere
## else, which the spec hash proves.
DIFFERENCES_PATH = Path("tests/platform_tests/case_study_differences.yaml")
CASE_STUDIES = sorted(p.stem for p in EXAMPLES.glob("*.yaml"))


## Phase 7.3: record one answer with the 7.1 path functions (answers.py is
## step 7.4). A `list` slot ("tokens[].id" answered ["MKR", "DAI"]) creates
## the list, one element per value: the only way tokens come into existence.
def _record_phase73(spec: dict, slot: Slot, value, indices: tuple[int, ...]) -> dict:
    if slot.answer_type == "list":
        head, _, leaf = slot.ir_path.rpartition("[].")
        set_value(spec, head, [{leaf: v} for v in value])
    else:
        set_value(spec, slot.ir_path, value, indices)
    return spec


_record = _record_phase73


## Phase 7.4: from now on the replay records answers exactly as
## elicit.record_answer.v1 does, so every case-study value must also pass
## apply_answer's shape and schema checks. This line rebinds _record, so
## nothing above has to be deleted.
def _record_phase74(spec: dict, slot: Slot, value, indices: tuple[int, ...]) -> dict:
    return apply_answer(spec, slot, value, "committed", indices=indices)


_record = _record_phase74


## Phase 7.3: the replay. Routing rules read the spec built SO FAR, as in a
## real interview: e.g. the network degree is asked only once the topology
## answer says "network", and per-token slots only for the tokens the
## tokens.ids answer created.
def _replay(protocol: Protocol, example: dict) -> dict:
    spec: dict = {}
    for stage, slot in protocol.ordered_slots():
        if not (
            routing.applies(stage.applies_when, spec, protocol)
            and routing.applies(slot.applies_when, spec, protocol)
        ):
            continue
        if slot.answer_type == "list":
            combos = index_combos(example, slot.ir_path)
            if combos:
                values = [get_value(example, slot.ir_path, c) for c in combos]
                spec = _record(spec, slot, values, ())
            continue
        for combo in index_combos(spec, slot.ir_path):
            if has_value(example, slot.ir_path, combo):
                value = get_value(example, slot.ir_path, combo)
                spec = _record(spec, slot, value, combo)
    return spec


## Phase 7.3: where the replay lacks or changes a value of the example, as
## generalised paths ("tokens[].transferable"). A missing subtree is reported
## once, at its top ("non_tokenized_assets"); an explicit null in the example
## means "no value", as in paths.has_value.
def _differences(example, replayed, path: str = "") -> set[str]:
    if isinstance(example, dict) and isinstance(replayed, dict):
        found: set[str] = set()
        for key, value in example.items():
            sub = f"{path}.{key}" if path else key
            if value is None:
                continue
            if replayed.get(key) is None:
                found.add(sub)
            else:
                found |= _differences(value, replayed[key], sub)
        return found
    if (
        isinstance(example, list)
        and isinstance(replayed, list)
        and len(example) == len(replayed)
        and all(isinstance(e, dict) for e in example)
    ):
        return set().union(
            *(_differences(e, r, path + "[]") for e, r in zip(example, replayed, strict=True))
        )
    return set() if example == replayed else {path}


## Phase 7.3: the documented differences (case_study_differences.yaml) and
## the example's values copied at exactly those paths.
def _documented() -> dict[str, dict]:
    return yaml.safe_load(DIFFERENCES_PATH.read_text(encoding="utf-8"))["differences"]


def _with_documented_fields(replayed: dict, example: dict, documented) -> dict:
    for path in documented:
        for combo in index_combos(example, path):
            if has_value(example, path, combo):
                set_value(replayed, path, get_value(example, path, combo), combo)
    return replayed


## Phase 7.3: guide 7.3 "Done when", for every case study. Both the complete
## fixture and the real protocol must reproduce each one. (The real cases
## were xfail(strict=True) while the protocol had stages 1 and 8 only; the
## marker was deleted when the protocol was completed.) The hash
## comparison is the formal check: the replay plus the documented fields IS
## the example, so a difference anywhere else changes the hash.
@pytest.mark.parametrize("example", CASE_STUDIES)
@pytest.mark.parametrize(
    "protocol",
    [
        pytest.param(_complete_protocol(), id="complete-fixture"),
        pytest.param(load_protocol(PROTOCOL_PATH), id="real"),
    ],
)
def test_case_study_is_reproduced_by_the_protocol(protocol, example):
    whole = yaml.safe_load((EXAMPLES / f"{example}.yaml").read_text(encoding="utf-8"))
    expected = service.validate(whole)
    assert expected.valid, expected.errors
    documented = _documented()
    replayed = _replay(protocol, whole)
    undocumented = sorted(_differences(whole, replayed) - documented.keys())
    assert not undocumented, f"no slot reproduces {undocumented}: add one, or document why"
    filled = _with_documented_fields(replayed, whole, documented)
    assert service.validate(filled).spec_hash == expected.spec_hash


## Phase 7.3: the list stays honest. Every entry says why, and is needed by
## at least one case study under the complete fixture (the reference for
## "what the interview asks"); an entry nothing needs any more (a slot was
## added) must be deleted.
def test_every_documented_difference_is_needed():
    assert CASE_STUDIES, "no examples found: run pytest from the repository root"
    documented = _documented()
    assert all(d["kind"] in ("intended", "gap") and d["reason"] for d in documented.values())
    complete = _complete_protocol()
    seen: set[str] = set()
    for example in CASE_STUDIES:
        whole = yaml.safe_load((EXAMPLES / f"{example}.yaml").read_text(encoding="utf-8"))
        seen |= _differences(whole, _replay(complete, whole))
    assert sorted(documented.keys() - seen) == []


## --- 7.4 answers ----------------------------------------------------------------------


## Phase 7.4
def test_point_answer_becomes_point_range():
    spec = apply_answer({}, _slot(answer_type="number"), 50, "committed")
    assert spec["participants"]["count_N"] == {"min": 50.0, "max": 50.0}


## Phase 7.4
def test_unknown_becomes_swept_range():
    spec = apply_answer({}, _slot(), None, "unknown")
    assert spec["participants"]["count_N"] == {"min": 2, "max": 1000}


## Phase 7.4
def test_per_token_path_uses_indices():
    slot = _slot(id="tokens.K", ir_path="tokens[].offer_variety_K")
    spec = apply_answer({"tokens": [{}, {}]}, slot, {"min": 3, "max": 5}, "committed", indices=(1,))
    assert spec["tokens"][1]["offer_variety_K"] == {"min": 3.0, "max": 5.0}
    assert "offer_variety_K" not in spec["tokens"][0]


## Phase 7.4
def test_input_spec_is_not_modified():
    # Spec versions are append-only: apply_answer must return a NEW dict.
    original = {"participants": {}}
    apply_answer(original, _slot(), None, "unknown")
    assert original == {"participants": {}}


## Phase 7.4: every answer is stored in the shape of its TE-IR field.
def test_answers_take_the_shape_of_their_field():
    slots = {s.id: s for _, s in _complete_protocol().ordered_slots()}
    one_token = {"tokens": [{"id": "A"}]}
    spec = apply_answer(
        one_token, slots["tokens.function"], "medium_of_exchange", "committed", indices=(0,)
    )
    assert spec["tokens"][0]["function"] == ["medium_of_exchange"]  # a list field
    rating = _slot(
        id="nfr",
        ir_path="meta.nfrs.resilience",
        answer_type="number",
        allow_unknown=False,
        unknown_range=None,
    )
    assert apply_answer({}, rating, 4, "committed")["meta"]["nfrs"]["resilience"] == 4
    with pytest.raises(InvalidInput):
        apply_answer({}, rating, 4.5, "committed")  # ratings are whole
    with pytest.raises(InvalidInput):
        apply_answer({}, rating, 9, "committed")  # 1-5 in the schema
    with pytest.raises(InvalidInput):
        apply_answer({}, slots["participants.topology"], "ring", "committed")
    with pytest.raises(InvalidInput):
        apply_answer({}, slots["participants.growth_g"], {"family": "wobbly"}, "committed")
    with pytest.raises(InvalidInput):
        apply_answer({}, _slot(), {"min": 5, "max": 1}, "committed")  # min above max


## Phase 7.4: the `list` slot is how tokens come into existence.
def test_list_slot_creates_and_names_tokens():
    ids = {s.id: s for _, s in _complete_protocol().ordered_slots()}["tokens.ids"]
    spec = apply_answer({}, ids, ["MKR", "DAI"], "committed")
    assert spec["tokens"] == [{"id": "MKR"}, {"id": "DAI"}]
    spec["tokens"][0]["offer_variety_K"] = {"min": 1, "max": 2}
    renamed = apply_answer(spec, ids, ["MKR2"], "committed")  # fewer tokens now
    assert renamed["tokens"] == [{"id": "MKR2", "offer_variety_K": {"min": 1, "max": 2}}]
    with pytest.raises(InvalidInput):
        apply_answer({}, ids, ["MKR"], "committed", indices=(0,))  # all items at once
    with pytest.raises(InvalidInput):
        apply_answer({}, ids, None, "unknown")  # allow_unknown false


## Phase 7.4: "unknown" is only accepted where the protocol gives it a meaning.
def test_unknown_needs_permission():
    slot = _slot(allow_unknown=False, unknown_range=None)
    with pytest.raises(InvalidInput):
        apply_answer({}, slot, None, "unknown")
    with pytest.raises(InvalidInput):
        apply_answer({}, slot, None, "default")  # no default either


## Phase 7.4: what "I don't know" is written as must be valid for the field.
@pytest.mark.parametrize(
    "protocol",
    [load_protocol(PROTOCOL_PATH), _complete_protocol()],
    ids=["real", "complete-fixture"],
)
def test_every_unknown_meaning_fits_the_schema(protocol):
    base = {"tokens": [{"id": "A"}]}
    for _, slot in protocol.ordered_slots():
        if slot.allow_unknown:
            indices = (0,) * slot.ir_path.count("[]")
            apply_answer(base, slot, None, "unknown", indices=indices)  # raises if not


## Phase 7.4: answered "unknown" wherever allowed (plus the answers that may
## not be unknown), the complete protocol yields a schema-valid spec, so the
## ranking (7.5) can always run the verifier on the swept copy.
_REQUIRED = {"tokens.ids": ["T"], "tokens.function": "medium_of_exchange", "governance.type": "dao"}


## Phase 7.4
def test_swept_complete_protocol_is_a_valid_spec():
    spec: dict = {}
    for _, slot in _complete_protocol().ordered_slots():
        indices = () if slot.answer_type == "list" else (0,) * slot.ir_path.count("[]")
        if slot.id in _REQUIRED:
            spec = apply_answer(spec, slot, _REQUIRED[slot.id], "committed", indices=indices)
        elif slot.allow_unknown:
            spec = apply_answer(spec, slot, None, "unknown", indices=indices)
    result = service.validate(spec)
    assert result.valid, result.errors


## --- 7.5 ranking --------------------------------------------------------------------------


## Phase 7.5: a spec that arrives WHOLE (form, upload, evals scenario) answers
## its own decisive questions: no answers recorded, yet nothing is open. This
## is what lets such a session leave `eliciting` (db/repo.get_session_facts).
@pytest.mark.parametrize("example", ["bitcoin", "axie_infinity", "time_bank"])
def test_whole_spec_has_no_open_decisive_slots(example):
    spec = yaml.safe_load((EXAMPLES / f"{example}.yaml").read_text(encoding="utf-8"))
    assert open_decisive_slots(spec, []) == []


## Phase 7.5: guide 7.5 "Done when": take a case study, remove ONE decisive
## value, and the ranking asks for exactly that one first.
@pytest.mark.parametrize("example", ["bitcoin", "axie_infinity", "time_bank"])
def test_removed_decisive_slot_is_asked_first(example):
    protocol = load_protocol(PROTOCOL_PATH)
    whole = yaml.safe_load((EXAMPLES / f"{example}.yaml").read_text(encoding="utf-8"))
    checked = 0
    for _, slot in protocol.ordered_slots():
        combos = index_combos(whole, slot.ir_path)
        if slot.criticality != "decisive" or slot.answer_type == "list" or not combos:
            continue
        if not has_value(whole, slot.ir_path, combos[0]):
            continue
        spec = copy.deepcopy(whole)
        set_value(spec, slot.ir_path, None, combos[0])  # null = no value
        result = next_questions(protocol, spec, [])
        # Asked slots come first among the questions; estimated ones first
        # among the estimates (the short interview splits the two).
        first = result.questions[0] if slot.approach == "ask" else result.to_estimate[0]
        assert first.slot_id == slot.id
        assert first.indices == list(combos[0])
        assert not result.complete
        checked += 1
    assert checked, "the protocol has no decisive slot this example fills"


## Phase 7.5: with every open item answered, there is nothing left to ask.
def test_complete_spec_is_complete():
    protocol = load_protocol(PROTOCOL_PATH)
    spec = yaml.safe_load((EXAMPLES / "bitcoin.yaml").read_text(encoding="utf-8"))
    answers: list[dict] = []
    # Answer every question asked ("unknown") until nothing is left.
    while not (result := next_questions(protocol, spec, answers)).complete:
        answers += [
            {"slot_id": q.slot_id, "indices": q.indices, "status": "unknown"}
            for q in result.questions + [e for e in result.to_estimate if e.matters]
        ]
    assert result.questions == []
    assert result.ranking_basis == "verifier"


## Phase 7.5: at the very start nothing validates; the ranking must still
## return the first decisive questions in protocol order.
def test_invalid_partial_spec_falls_back_to_protocol_order():
    protocol = load_protocol(PROTOCOL_PATH)
    result = next_questions(protocol, {}, [])
    assert result.ranking_basis == "protocol_order"
    assert not result.complete
    first_decisive = next(
        s.id
        for st, s in protocol.ordered_slots()
        if s.criticality == "decisive"
        and s.approach == "ask"
        and st.applies_when is None
        and s.applies_when is None
        and "[]" not in s.ir_path
    )
    assert result.questions[0].slot_id == first_decisive


## Phase 7.5: the ranking maps the verifier's minimum_param_shift keys to IR
## paths with an explicit table (ranking._SHIFT_KEY_TO_IR_PATH). This test
## reads every `parameter="..."` the failure modes can emit and fails when one
## is not mapped, so a new verifier parameter cannot be silently ignored by
## the interview ordering.
def test_every_verifier_shift_key_is_mapped():
    keys = set()
    for f in Path("verifier/failure_modes").glob("fm*.py"):
        keys |= set(re.findall(r'parameter="([^"]+)"', f.read_text(encoding="utf-8")))
    assert keys, "no parameter names found: has the verifier changed its format?"
    unmapped = sorted(k for k in keys if _shift_key_to_path(k) is None)
    assert not unmapped, f"add these to _SHIFT_KEY_TO_IR_PATH: {unmapped}"
    # tau[<agent type>] is built with an f-string in FM2; check the prefix rule.
    assert _shift_key_to_path("tau[manager]") == "participants.agent_types"


## Phase 7.5: an end-to-end interview on the complete fixture, with the real
## verifier choosing the order: answer what is asked ("unknown" where allowed,
## real values otherwise) until the ranking says complete, then record the
## not_needed questions as unknown, as the agent does. The stopping rule
## fired before every slot had to be asked, and the final spec is valid.
_ANSWERS = {
    **_REQUIRED,
    "tokens.value_anchor": "none",
    "tokens.earning": "behavioral_reward",
    "tokens.holding": "none",
    "events": [],
    "tokens.initial_distribution": {"kind": "none"},
    "cross_token_flows": [],
    "governance.sanction": {"kind": "warning"},
    "participants.agent_types": [
        {
            "id": "member",
            "fraction": 1.0,
            "role": "contributor",
            "expected_holding_time": {"expected_periods": {"min": 1, "max": 4}},
        }
    ],
}


## Phase 7.5
def test_an_interview_on_the_complete_protocol_finishes():
    protocol = _complete_protocol()
    slots = {s.id: s for _, s in protocol.ordered_slots()}
    spec: dict = {}
    answers: list[dict] = []
    for _ in range(60):  # far more than needed
        result = next_questions(protocol, spec, answers)
        if result.complete:
            break
        for q in result.questions:
            slot = slots[q.slot_id]
            status = "committed" if q.slot_id in _ANSWERS else "unknown"
            spec = apply_answer(
                spec, slot, _ANSWERS.get(q.slot_id), status, indices=tuple(q.indices)
            )
            answers.append({"slot_id": q.slot_id, "indices": q.indices, "status": status})
    assert result.complete
    assert result.ranking_basis == "verifier"
    # The stopping rule fired: some questions were never asked ...
    assert result.not_needed
    # ... and, as the agent does, they are recorded as unknown where allowed.
    for q in result.not_needed:
        if q.allow_unknown:
            spec = apply_answer(spec, slots[q.slot_id], None, "unknown", indices=tuple(q.indices))
    result = service.validate(spec)
    assert result.valid, result.errors


## Extension: structured answers carry their schema; a stuck interview says why.
def test_structured_questions_carry_their_field_schema():
    protocol = load_protocol(PROTOCOL_PATH)
    result = next_questions(protocol, {}, [])
    asked = {q.slot_id: q for q in result.questions + result.to_estimate}
    assert asked["meta.archetype"].value_schema is None  # simple answers need no schema
    # A list slot is answered with one value per element.
    assert asked["tokens.ids"].value_schema == {"type": "array", "items": {"type": "string"}}
    # The emission rules: the Rule schema, so the agent can write a rule.
    rules = _value_schema("tokens[].emission_rules", "dsl_expression")
    assert rules is not None and "trigger" in str(rules) and "asymptotic_class" in str(rules)


def test_a_stuck_interview_says_why():
    protocol = load_protocol(PROTOCOL_PATH)
    result = next_questions(protocol, {}, [])
    assert result.spec_errors  # an empty design does not validate yet
    assert all(": " in e for e in result.spec_errors)


## Extension: the short interview asks a few facts and estimates the rest.
def test_only_core_facts_are_asked_and_the_rest_is_estimated():
    protocol = load_protocol(PROTOCOL_PATH)
    asked = {s.id for _, s in protocol.ordered_slots() if s.approach == "ask"}
    assert asked == {
        "participants.N",
        "participants.d",
        "tokens.emission",
        "tokens.burn",
        "governance.type",
    }
    spec = yaml.safe_load((EXAMPLES / "time_bank.yaml").read_text(encoding="utf-8"))
    for path in ("participants.count_N", "participants.expected_Q"):
        set_value(spec, path, None)
    result = next_questions(protocol, spec, [])
    assert [q.slot_id for q in result.questions] == ["participants.N"]
    # The cap on tokens outstanding is offered too, last and marked as not
    # mattering: time_bank has none, and "no cap" leaves the design as it is.
    assert [q.slot_id for q in result.to_estimate] == ["participants.Q", "tokens.outstanding_cap"]
    assert result.to_estimate[0].approach == "estimate"
    assert result.to_estimate[0].matters and not result.to_estimate[1].matters
    assert all(q.slot_id != "participants.Q" for q in result.not_needed)


def test_an_accepted_estimate_is_written_like_a_given_value():
    spec = apply_answer({}, _slot(), {"min": 20, "max": 120}, "estimated")
    assert spec["participants"]["count_N"] == {"min": 20.0, "max": 120.0}


## Outstanding supply cap: "no limit" (unknown) leaves the optional field
## empty, a known total is a range (docs/proofs/outstanding_cap.md).
def test_no_credit_limit_leaves_the_cap_empty():
    slot = load_protocol(PROTOCOL_PATH).slot("tokens.outstanding_cap")
    assert slot is not None and slot.unknown_means_absent
    spec = {"tokens": [{"id": "CR"}]}
    none = apply_answer(spec, slot, None, "unknown", indices=(0,))
    assert none["tokens"][0]["outstanding_supply_cap"] is None
    capped = apply_answer(spec, slot, {"min": 5000, "max": 8000}, "estimated", indices=(0,))
    assert capped["tokens"][0]["outstanding_supply_cap"] == {"min": 5000.0, "max": 8000.0}
