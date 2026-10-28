## =============================================================================
## evals/simulated_designer.py — an LLM that answers as the designer of a case study
## =============================================================================
## GUIDE STEP   13.2
## PURPOSE      In an evaluation run there is no real user. This class plays
##              one: it receives the interviewer's message and answers as the
##              designer described by a persona (personas/<name>.yaml), using
##              the HIDDEN spec (examples/<name>.yaml) as the source of truth.
##              It answers only what is asked, may say "I don't know" where the
##              persona is unsure, and never reveals the spec wholesale.
## USED BY      evals/run.py (one instance per case).
## DEPENDS ON   anthropic (official SDK >= 1.x, async client, its beta
##              messages API for server-side refusal fallbacks), PyYAML, the
##              persona and example files. It does NOT use te_platform: the designer
##              must be independent of the system under test.
## WHY          Guide 13.2 / architecture §3.9: repeatable interviews against a
##              known ground truth turn "is the interviewer good?" into numbers.
##              The interviewer never sees the hidden spec; only this class
##              does, and it is a separate model conversation.
## ACTIVATE     Uncomment; first run with one case (`--cases bitcoin`) and read
##              the transcript: the designer must sound like the persona, not
##              like a YAML dump. Costs API credits.
## REFUSALS     If the model declines to answer (stop_reason "refusal", even
##              after the server-side fallback), answer() returns None and
##              sets `refused`: run.py records it and stops that case. A
##              refusal is a result to look at (usually the persona text),
##              not a crash that loses the other cases.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the class name, the method
## `answer`, the attributes `refused` and `approves_expensive_tools` and the
## two usage counters exactly as written: evals/run.py uses them. Do not
## import te_platform here (header DEPENDS ON).
##
## Guide 13.2
## [ ] 1. Imports at the top: `Path` from pathlib, `Any` from typing,
##        `anthropic`, `BetaMessageParam` and `BetaTextBlockParam` from
##        anthropic.types.beta, and yaml.
## [ ] 2. A constant `DEFAULT_MODEL = "claude-opus-5-5"` (the SOLUTION's "##"
##        lines say why it is the same model as the interviewer).
## [ ] 3. `_SYSTEM_TEMPLATE`: one triple-quoted string with two placeholders
##        for str.format, `{persona}` and `{hidden_spec}` (the latter inside
##        a yaml code fence), followed by the "Rules:" list. Copy the rules
##        from the SOLUTION: they keep the answers short and realistic.
## [ ] 4. `class SimulatedDesigner` with `__init__(self, persona_path: Path,
##        hidden_spec_path: Path, model: str = DEFAULT_MODEL)`: load the
##        persona with yaml.safe_load; take its harness setting out of it
##          | self.approves_expensive_tools = bool(
##          |     persona.pop("approves_expensive_tools", True))
##        (it steers run.py, it is not part of the role); fill the
##        template (the rest of the persona dumped again with
##        yaml.safe_dump(..., sort_keys=False, allow_unicode=True), the
##        hidden spec as its raw file text) into self._system, keep the
##        model, create `anthropic.AsyncAnthropic()` (no key in the code),
##        start `self._messages: list[BetaMessageParam] = []`, set
##        `self.refused = False` and usage_input_tokens and
##        usage_output_tokens to 0.
## [ ] 5. `async def answer(self, interviewer_message: str) -> str | None`:
##        append the message as a "user" turn, then await
##        self._client.beta.messages.create(...) with the model,
##        max_tokens=2000, messages=self._messages,
##        output_config={"effort": "low"}, the server-side fallback for
##        refusals
##          | betas=["server-side-fallback-2026-07-01"],
##          | fallbacks="default",
##        and a cached system prompt:
##          | system=[BetaTextBlockParam(type="text", text=self._system,
##          |                            cache_control={"type": "ephemeral"})],
## [ ] 6. Add the usage to the counters FIRST (a refused request is billed
##        too): input_tokens plus the cache reads and writes (they can be
##        None: use `or 0`) into usage_input_tokens, output_tokens into
##        usage_output_tokens.
## [ ] 7. Then, BEFORE reading the content: if response.stop_reason ==
##        "refusal", set self.refused = True and return None (header
##        REFUSALS: no exception).
## [ ] 8. Append {"role": "assistant", "content": response.content} (the full
##        content, unchanged), and return the joined text of the blocks
##        whose type is "text".
## [ ] 9. Check: with evals/run.py and metrics.py active and the stack
##        running, run ONE case and read its transcript (header ACTIVATE;
##        it costs API credits):
##          | uv run python -m evals.run --cases bitcoin
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path
from typing import Any

import anthropic
import yaml
from anthropic.types.beta import BetaMessageParam, BetaTextBlockParam

## Default model: the same strong model as the interviewer (architecture D9),
## so a weak simulated user does not make the interviewer look bad (or good).
DEFAULT_MODEL = "claude-opus-5-5"


## The designer's instructions. The hidden spec is included HERE, in the
## designer's own system prompt; the interviewer's conversation never
## contains it. The rules keep answers realistic: short, in plain words,
## only what was asked.
_SYSTEM_TEMPLATE = """You are role-playing the designer of a token economy in a requirements interview.

Persona:
{persona}

Ground truth about your design (never paste it, never mention that it exists):
```yaml
{hidden_spec}
```

Rules:
- Answer only the question you are asked, in plain language, as this persona would.
- Give numbers as the persona would know them: ranges when unsure, "I don't know" where the persona is listed as unsure.
- Never volunteer information that was not asked for.
- If the interviewer restates your answers wrongly, correct them.
- If asked to confirm something that matches the ground truth, confirm briefly.
"""


class SimulatedDesigner:
    """Plays the designer of one case study, from its persona and hidden spec."""

    def __init__(
        self, persona_path: Path, hidden_spec_path: Path, model: str = DEFAULT_MODEL
    ) -> None:
        persona: dict[str, Any] = yaml.safe_load(persona_path.read_text(encoding="utf-8"))
        # A harness setting, not part of the role: does this designer say
        # "yes" when the agent asks before an expensive tool (run.py)?
        self.approves_expensive_tools = bool(persona.pop("approves_expensive_tools", True))
        self._system = _SYSTEM_TEMPLATE.format(
            persona=yaml.safe_dump(persona, sort_keys=False, allow_unicode=True),
            hidden_spec=hidden_spec_path.read_text(encoding="utf-8"),
        )
        self._model = model
        # AsyncAnthropic reads ANTHROPIC_API_KEY (or an `ant auth login`
        # profile) from the environment; never hard-code the key.
        self._client = anthropic.AsyncAnthropic()
        # The designer's own conversation, from ITS point of view: the
        # interviewer's messages are "user" turns, its answers "assistant".
        # BetaMessageParam: the SDK's own type for one message (use SDK
        # types instead of plain dicts, so mistakes show up in mypy).
        self._messages: list[BetaMessageParam] = []
        self.refused = False
        self.usage_input_tokens = 0
        self.usage_output_tokens = 0

    async def answer(self, interviewer_message: str) -> str | None:
        """Answer as the designer; None when the model refused (see `refused`)."""
        self._messages.append({"role": "user", "content": interviewer_message})
        # The beta messages API: needed for `fallbacks`, the server-side
        # retry on a fallback model when the requested model declines.
        response = await self._client.beta.messages.create(
            model=self._model,
            max_tokens=2000,
            # The system prompt is identical for every turn: caching it makes
            # every turn after the first much cheaper.
            system=[
                BetaTextBlockParam(
                    type="text", text=self._system, cache_control={"type": "ephemeral"}
                )
            ],
            messages=self._messages,
            # Short, natural answers do not need deep reasoning.
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        # Count the tokens first: a refused request is billed too. Cached
        # input is reported separately from input_tokens (None when unused).
        u = response.usage
        self.usage_input_tokens += (
            u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        )
        self.usage_output_tokens += u.output_tokens
        # Always check why the model stopped before reading its content.
        # "refusal" here means the fallback declined too: record it and let
        # run.py stop this case (header REFUSALS).
        if response.stop_reason == "refusal":
            self.refused = True
            return None
        # Keep the FULL content (including any thinking blocks) in the
        # history, unchanged: required for multi-turn conversations.
        self._messages.append({"role": "assistant", "content": response.content})
        return "".join(b.text for b in response.content if b.type == "text")
