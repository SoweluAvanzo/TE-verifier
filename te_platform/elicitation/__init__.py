## =============================================================================
## te_platform/elicitation/__init__.py — the interview ("elicitation") package
## =============================================================================
## GUIDE STEP   7.1-7.5 (protocol.py and paths.py 7.1, routing.py and coverage.py
##              7.2, answers.py 7.4, ranking.py 7.5)
## PURPOSE      Marks elicitation/ as a package. It turns the interview rules
##              in ../../policy/elicitation_protocol.yaml into code:
##
##                protocol.py  typed models of the protocol file + load_protocol()
##                paths.py     the dotted IR-path notation ("tokens[].x"):
##                             schema types, reading and writing spec dicts
##                routing.py   named `applies_when` rules (which questions apply,
##                             e.g. "only for multi-token designs"); they read
##                             the spec; no eval()
##                coverage.py  checks used by the coverage tests (guide 7.2):
##                             the protocol asks for everything the six failure
##                             modes need, and every ir_path exists in the schema
##                answers.py   writes one answer into a spec dict at the slot's
##                             ir_path, in the field's own shape ("unknown" ->
##                             a swept range or "unspecified")
##                ranking.py   chooses the next questions with the verifier and
##                             decides when the interview is complete
##
##              How the files relate (arrows = "uses"):
##
##                ranking.py ──► protocol.py, paths.py, routing.py, answers.py,
##                     │          te_platform.service.minimal (verifier triage)
##                     └──────► verifier/paper.py (why-we-ask texts)
##                answers.py ──► protocol.py, paths.py
##                routing.py ──► protocol.py, paths.py
##                coverage.py ─► protocol.py, paths.py, routing.py,
##                               verifier/paper.py
##                paths.py ────► schema.TokenEconomy
##
##              Callers outside: tools/elicit_next_questions.py (ranking),
##              tools/elicit_record_answer.py (answers), both tools
##              (protocol.current_protocol),
##              mcp_server/resources.py
##              (publishes the protocol as te://protocol/elicitation),
##              tests/platform_tests/test_platform_elicitation.py.
## WHY          Architecture §4 and D16: the interview rules are DATA (YAML),
##              reviewable by co-authors and testable for coverage; the
##              behaviour of the interviewer (how to ask) lives separately in
##              agent/prompts/interview.md.
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
