## =============================================================================
## te_platform/registry/describe.py — the tool description the model reads
## =============================================================================
## GUIDE STEP   2.6
## PURPOSE      Builds each tool's description text from its policy entry,
##              with one fixed template. This text is what an LLM sees when it
##              decides which tool to call, so it is one of the most important
##              "prompts" in the system.
## USED BY      mcp_server/app.py (passes it as the MCP tool description).
## DEPENDS ON   registry/policy.py.
## WHY          The rules (policy) and the description can never drift apart,
##              because the description IS the rules, rendered. Anthropic's
##              guidance on writing tools for agents: say when to use a tool,
##              when not to, and what it returns.
## ACTIVATE     Uncomment; a snapshot test (test_platform_registry.py, its
##              Guide 2.6 section) compares the generated text of every tool
##              with tests/platform_tests/snapshots/tool_descriptions.txt and
##              fails when it changes, so every change is reviewed.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `describe` exactly as
## written (te_platform/README.md, contracts table). Activate policy.py first.
##
## Guide 2.6
## [ ] 1. Import at the top: `Policy` from te_platform.registry.policy.
## [ ] 2. `describe(tool_id: str, policy: Policy) -> str`, with a one-line
##        docstring: get the tool entry `tp` and its cost class, then build
##        a list of lines, starting with the stripped summary and an empty
##        line.
## [ ] 3. Add the sections in this fixed order: "Use when:" with one "- "
##        line per item; "Do not use when:" (only if not empty); "Requires:"
##        (only if there are preconditions); the "Cost:" line, ending with
##        "; ask the user before calling." when cost.ask_user_first, else
##        "." (compute that ending first: one line stays short);
##        "Input notes:" (if any); one "Rule: " line per usage rule;
##        "Returns:"; "Usually followed by:" (if typical_next is not empty).
##          | lines += [f"- {x}" for x in tp.use_when]
## [ ] 4. Return "\n".join(lines).
## [ ] 5. Check: run `uv run mypy te_platform`, activate the Guide 2.6
##        section of tests/platform_tests/test_platform_registry.py, then
##          | uv run pytest tests/platform_tests/test_platform_registry.py -q
##        Read each tool's text in the snapshot file aloud, as guide 2.6
##        asks. After a deliberate policy change, regenerate the snapshot:
##          | TE_UPDATE_SNAPSHOTS=1 uv run pytest \
##          |     tests/platform_tests/test_platform_registry.py -q
##        and review its diff in the pull request.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from te_platform.registry.policy import Policy


def describe(tool_id: str, policy: Policy) -> str:
    """Render the description of `tool_id` from its policy entry (fixed template)."""
    tp = policy.tools[tool_id]
    cost = policy.cost_classes[tp.cost]
    lines = [tp.summary.strip(), ""]
    lines.append("Use when:")
    lines += [f"- {x}" for x in tp.use_when]
    if tp.do_not_use_when:
        lines.append("Do not use when:")
        lines += [f"- {x}" for x in tp.do_not_use_when]
    if tp.preconditions:
        lines.append(
            "Requires: "
            + ", ".join(tp.preconditions)
            + " (the server refuses otherwise and tells you what to run first)."
        )
    ending = "; ask the user before calling." if cost.ask_user_first else "."
    lines.append(f"Cost: {tp.cost} ({cost.typical}){ending}")
    if tp.input_notes:
        lines.append("Input notes: " + tp.input_notes.strip())
    lines += [f"Rule: {r}" for r in tp.usage_rules]
    lines.append("Returns: " + tp.returns)
    if tp.typical_next:
        lines.append("Usually followed by: " + ", ".join(tp.typical_next))
    return "\n".join(lines)
