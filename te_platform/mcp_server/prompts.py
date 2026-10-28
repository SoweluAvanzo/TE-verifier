## =============================================================================
## te_platform/mcp_server/prompts.py — reusable conversation templates (MCP prompts)
## =============================================================================
## GUIDE STEP   3.2 (explain_report, design_review), 7.6 (interview_token_economy)
## PURPOSE      MCP *prompts* are ready-made instructions a client can insert
##              into a conversation, usually chosen by the user from a menu
##              (e.g. "/interview_token_economy" in Claude Desktop). We offer:
##                interview_token_economy  the interviewer method + the
##                                         elicitation protocol, so ANY MCP
##                                         client interviews the same way as
##                                         our own chat (architecture D16);
##                explain_report           turn a verification result into
##                                         plain language for a stated audience;
##                design_review            critique an existing spec against
##                                         the six failure modes.
## USED BY      mcp_server/app.py (passes on_list_prompts / on_get_prompt to the
##              low-level Server). Users of external MCP clients.
## DEPENDS ON   mcp (types, MCPError); from 7.6
##              te_platform/agent/prompts/interview.md (the same file our agent
##              uses as its interview method).
## ERRORS       A missing required argument or an unknown prompt name raises
##              MCPError(INVALID_PARAMS, message): the client receives a clean
##              JSON-RPC error that names the problem. (Any other exception
##              would reach the client only as an anonymous internal error.)
## WHY          One method, one file, every client (P3, D16). The texts here
##              are short wrappers; the substance lives in interview.md and in
##              the tool policy, which clients can also read as resources.
## NOTE         The interview prompt is a guide 7.6 block (commented twice):
##              interview.md is written with `<!-- DRAFT` markers until it has
##              been reviewed at 7.6, so the prompt must not be advertised
##              earlier. HTML comments (the file's header for developers) are
##              removed before the text is sent to a client.
## ACTIVATE     3.2: uncomment (single-commented code); the Inspector's Prompts
##              tab lists explain_report and design_review. 7.6: the
##              twice-commented interview lines.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the handler names
## (on_list_prompts, on_get_prompt) and the prompt names exactly: app.py
## and MCP clients use them.
##
## Guide 3.2
## [ ] 1. Imports at the top: Any, MCPError and `types` (from mcp),
##        INVALID_PARAMS (mcp.types), ServerRequestContext (mcp.server).
## [ ] 2. `_PROMPTS`: a list of types.Prompt (name, title, description,
##        arguments). explain_report takes verification_ref (required) and
##        audience (optional); design_review takes spec (required):
##          | types.PromptArgument(name="spec", description="...",
##          |                      required=True)
## [ ] 3. `async on_list_prompts(_ctx, _params)`: return
##        ListPromptsResult(prompts=_PROMPTS).
## [ ] 4. `_user_message(text)`: a PromptMessage with role "user" and one
##        TextContent. `_required(args, name, prompt)`: the argument's
##        value, or MCPError(INVALID_PARAMS, ...) naming what is missing.
## [ ] 5. `_explain_report(args)` and `_design_review(args)`: each returns a
##        GetPromptResult with a description and [_user_message(text)]:
##        explain_report (audience defaults to "a non-technical reader";
##        only numbers from tool results), design_review (verify first,
##        then explain; the spec text is appended).
## [ ] 6. `async on_get_prompt(_ctx, params)`: read the arguments as a dict
##        and dispatch on params.name; unknown name: MCPError(INVALID_PARAMS).
## [ ] 7. Check: toggle the 3.2 lines in app.py; the Inspector's Prompts tab
##        lists the prompts and lets you fill their arguments, and leaving
##        out a required argument shows an "invalid params" error.
##
## Guide 7.6 (the "# # " lines under the Phase/Guide 7.6 labels; only
## after the DRAFT markers in interview.md are removed, see NOTE)
## [ ] 8. Toggle the `re` and Path imports, `_INTERVIEW_MD`,
##        `_interview_method()` (the file without its HTML comments) and
##        `_interview(args)` (the method, then the language and the start
##        instructions: read te://protocol/elicitation, call
##        elicit.next_questions.v1 WITHOUT a session_id, reuse the returned
##        session_id).
## [ ] 9. Toggle the interview entry at the end of _PROMPTS and its branch
##        in on_get_prompt. Check: activate
##        test_interview_prompt_is_served in
##        tests/platform_tests/test_platform_mcp.py; the Inspector shows the
##        prompt and a manual interview through Claude Desktop works end to
##        end.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Phase 7.6: reading interview.md.
import re
from pathlib import Path
from typing import Any

from mcp import MCPError, types
from mcp.server import ServerRequestContext
from mcp.types import INVALID_PARAMS

## --- The interview method (guide 7.6) ----------------------------------------
## Phase 7.6: the same file our agent uses (agent/chat_api.py), so every client
## interviews with the same method. Its `<!-- ... -->` blocks are notes for
## developers (header, TO-DO list), never meant for the model.
_INTERVIEW_MD = Path(__file__).resolve().parents[1] / "agent" / "prompts" / "interview.md"
_HTML_COMMENT = re.compile(r"<!--.*?-->\n?", re.DOTALL)


## Phase 7.6: the method text sent to clients.
def _interview_method() -> str:
    """Return the text of interview.md without its HTML comments."""
    return _HTML_COMMENT.sub("", _INTERVIEW_MD.read_text(encoding="utf-8")).strip()


## --- The catalogue shown to clients ------------------------------------------
_PROMPTS = [
    types.Prompt(
        name="explain_report",
        title="Explain a verification report",
        description="Explain a verify.run.v1 result in plain language for a given audience.",
        arguments=[
            types.PromptArgument(
                name="verification_ref",
                description="The ref returned by verify.run.v1.",
                required=True,
            ),
            types.PromptArgument(
                name="audience",
                description="Who reads it, e.g. 'community members'.",
                required=False,
            ),
        ],
    ),
    types.Prompt(
        name="design_review",
        title="Review a design",
        description="Critique a token economy spec against the six failure modes, with remedies.",
        arguments=[
            types.PromptArgument(name="spec", description="The spec as YAML text.", required=True)
        ],
    ),
    ## Guide 7.6: the interview prompt.
    types.Prompt(
        name="interview_token_economy",
        title="Design interview",
        description="Interview me about my token economy, then verify it against "
        "the six failure modes.",
        arguments=[
            types.PromptArgument(
                name="language",
                description="Language of the interview (default English).",
                required=False,
            )
        ],
    ),
]


async def on_list_prompts(
    _ctx: ServerRequestContext[Any, Any],
    _params: types.PaginatedRequestParams | None,
) -> types.ListPromptsResult:
    """List the prompts this server offers."""
    return types.ListPromptsResult(prompts=_PROMPTS)


## --- Building one prompt -----------------------------------------------------
def _user_message(text: str) -> types.PromptMessage:
    """Wrap `text` as one message from the user."""
    return types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))


def _required(args: dict[str, str], name: str, prompt: str) -> str:
    """Return the argument `name`, or refuse the request cleanly if it is missing."""
    value = args.get(name, "")
    if not value.strip():
        raise MCPError(
            code=INVALID_PARAMS, message=f"Prompt {prompt!r} needs the argument {name!r}."
        )
    return value


def _explain_report(args: dict[str, str]) -> types.GetPromptResult:
    """Build explain_report: a plain-language reading of one verification."""
    ref = _required(args, "verification_ref", "explain_report")
    audience = args.get("audience") or "a non-technical reader"
    text = (
        f"Explain the verification {ref} for {audience}. "
        "Use only numbers present in the tool results; for each failure mode "
        "give the verdict, why, and what could be changed. Cite literature only "
        "via lit.search.v1."
    )
    return types.GetPromptResult(description="Explain a report", messages=[_user_message(text)])


def _design_review(args: dict[str, str]) -> types.GetPromptResult:
    """Build design_review: verify a spec, then critique it."""
    spec = _required(args, "spec", "design_review")
    text = (
        "Review this token economy design. First call verify.run.v1 on it, then "
        "explain each failing or inconclusive failure mode and propose changes.\n\n" + spec
    )
    return types.GetPromptResult(description="Design review", messages=[_user_message(text)])


## Phase 7.6: the interview prompt.
def _interview(args: dict[str, str]) -> types.GetPromptResult:
    """Build interview_token_economy: the method, then how to start."""
    language = args.get("language") or "English"
    # How an external client starts: next_questions WITHOUT session_id
    # creates a session and returns its id (tools/elicit_next_questions.py).
    text = (
        f"{_interview_method()}\n\nConduct the interview in {language}. Start by "
        "reading the resource te://protocol/elicitation, then call "
        "elicit.next_questions.v1 WITHOUT a session_id: it starts a new design "
        "session and returns its session_id. Pass that session_id in every later "
        "call (elicit.record_answer.v1 requires it)."
    )
    return types.GetPromptResult(description="Design interview", messages=[_user_message(text)])


async def on_get_prompt(
    _ctx: ServerRequestContext[Any, Any], params: types.GetPromptRequestParams
) -> types.GetPromptResult:
    """Build the prompt `params.name` from its arguments."""
    args = dict(params.arguments or {})
    if params.name == "explain_report":
        return _explain_report(args)
    if params.name == "design_review":
        return _design_review(args)
    ## Guide 7.6: the interview prompt.
    if params.name == "interview_token_economy":
        return _interview(args)
    raise MCPError(code=INVALID_PARAMS, message=f"Unknown prompt {params.name!r}.")
