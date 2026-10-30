## =============================================================================
## evals/run.py — run the evaluation: simulated interviews and tool-selection scenarios
## =============================================================================
## GUIDE STEP   13.2 (cases), 13.3 (scenarios), 13.4 (compare with the baseline)
## PURPOSE      Command-line entry point of the harness:
##                python -m evals.run --cases bitcoin axie_infinity --out evals/results/<date>
##                python -m evals.run --scenarios-only
##                python -m evals.run --compare <baseline_dir> <new_dir>
##              For each case it drives a full conversation between the REAL
##              agent (through its HTTP API, see HOW) and a SimulatedDesigner,
##              then computes the metrics and writes JSON + the transcript.
## USED BY      Developers; the on-demand/nightly CI job (guide 13.3).
## DEPENDS ON   evals/simulated_designer.py, evals/metrics.py,
##              httpx2 (HTTP client), a running stack (phases 8-9), API credits.
## WHY          Architecture §3.9: every change to prompts, policy, protocol or
##              model must show its evaluation delta (guide 13.4).
## ACTIVATE     After phase 8 works end to end. Uncomment, run ONE case, read
##              its transcript, then run all cases once and commit the result
##              folder as evals/results/baseline/.
## HOW        The harness drives the agent exactly like the browser does,
##              through the agent service's HTTP API (log in, create a
##              session, post messages, read the Server-Sent Events stream).
##              So it tests the DEPLOYED system end to end (Caddy, agent, MCP,
##              worker, database), not Python internals, and needs no change
##              when the agent's code is refactored.
## SETUP        A running stack (docker compose up) and an evaluation user:
##                te-platform users create --email evals@localhost
##              Environment variables (deliberately NOT TE_*, because the
##              services reject unknown TE_* variables):
##                EVALS_BASE_URL     the site's address, e.g.
##                                   http://localhost:8080 (Caddy). It must
##                                   equal the agent's
##                                   TE_PUBLIC_ORIGIN: it is sent as the
##                                   Origin header, which POSTs must carry.
##                EVALS_ACCESS_CODE  the code printed by `users create`
##              plus the Anthropic key for the simulated designer
##              (ANTHROPIC_API_KEY, read by the anthropic SDK).
## RESULTS      <out>/<case>.json (metrics), <out>/<case>.transcript.json and
##              <out>/scenarios.json. --compare prints the metric deltas of
##              every case present in both folders and the scenario results
##              that changed.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" steps at the end. Lines starting with
## "|" are short illustrations, not the full code. The endpoint paths, JSON
## fields and event types must be exactly those of the agent service
## and te_platform/agent/events.py. Activate evals/metrics.py and
## evals/simulated_designer.py first.
##
## Guide 13.2
## [ ] 1. Imports at the top: argparse, asyncio, json, os, `AsyncIterator`
##        from collections.abc, `Path`, `Any`, then
##          | import httpx2 as httpx
##        yaml, `RunRecord`, `ToolCallRecord`, `summarise` from
##        evals.metrics and `SimulatedDesigner` from evals.simulated_designer.
## [ ] 2. Module constants: EXAMPLES, PERSONAS and SCENARIOS as Paths
##        relative to the repository root, MAX_TURNS = 40, and
##        NEEDS_SIMULATION = {"inconclusive"} (the verdict statuses that
##        call for a simulation, together with structural_status "fragile").
## [ ] 3. `class AgentClient`, `__init__(self, base_url, access_code)`: keep
##        the base URL without its trailing "/" and the code, and create
##        httpx.AsyncClient(base_url=..., headers={"Origin": self.base},
##        timeout=600). The Origin header passes the CSRF check (agent/auth.py).
## [ ] 4. `async __aenter__`: POST "/agent/login" with {"access_code": ...},
##        raise_for_status(), then copy the login cookies into the client
##        as plain cookies (the SOLUTION's comment says why: the cookie is
##        Secure, and Python never sends those over http://):
##          | self.http.cookies = {c.name: c.value for c in r.cookies.jar}
##        and return self. `async __aexit__`: aclose() the client.
## [ ] 5. `async new_session(self, spec_yaml=None) -> str`: POST
##        "/agent/sessions" with json {}, raise_for_status() and take
##        "session_id"; if spec_yaml is given, POST {"yaml": spec_yaml} to
##        /agent/sessions/{sid}/spec and raise_for_status() (the form's
##        endpoint, guide 9.3).
## [ ] 6. After the class, `async def _sse_events(response)`, an async
##        generator: collect the text after "data:" of each line, and on a
##        blank line yield json.loads of the collected data and start again.
##        The "event:" lines can be ignored: each data JSON has its "type".
## [ ] 7. Back in the class, `async turn(self, sid, text, *, approve=True)`
##        returning a dict with the keys text, tools, verdicts, done,
##        declined (tool ids the user said "No" to) and tokens. `approve`
##        answers the agent's confirmation questions: True (yes), False
##        (no), None (leave them unanswered and end the turn). Start with
##        body = {"text": text}; in a loop, stream a POST of it to
##        /agent/sessions/{sid}/messages
##        and, for each event of
##          | async for event in _sse_events(r):
##        handle text_delta, tool_finished (append {tool, ok, error_code}),
##        verdict_updated, confirmation_required (keep tool_use_id -> tool)
##        and done (keep the reason, add the sum of its usage values to
##        tokens). If the reason is "awaiting_confirmation", there are
##        questions and approve is not None, send
##        {"text": "", "confirmations": {id: approve, ...}}, add the tools
##        to declined when approve is False, and loop again; otherwise
##        return.
## [ ] 8. `async session(sid)`: the JSON of GET /agent/sessions/{sid}.
##        `async spec(sid)`: GET .../spec and return yaml.safe_load of its
##        "yaml", or None when there is none. Both raise_for_status().
## [ ] 9. `async run_case(client, case)` returning (metrics, transcript):
##        a SimulatedDesigner for personas/<case>.yaml and
##        examples/<case>.yaml, a new session, and a RunRecord with the
##        example as hidden_spec. The designer writes the first message
##        (None = it refused: set record.designer_refused and skip the
##        loop); then up to MAX_TURNS times: count the turn, call
##        client.turn with approve=designer.approves_expensive_tools, append
##        {user, agent, tools} to the transcript, and fill the record from
##        the turn (`_record_turn`, step 10). Stop when the session state
##        is "verified", "simulated" or "reported" and done is
##        "final_answer"; else the designer answers the agent's text, and a
##        None answer sets designer_refused and stops the case.
##        Afterwards fill elicited_spec, open_decisive_slots and
##        designer_tokens (input + output) and return summarise(record).
## [ ] 10. `_record_turn(record, turn)` (above run_case): add
##         ToolCallRecord(**t) for each tool; keep any verdicts; add the
##         turn's tokens to agent_tokens; count the report.render_pdf.v1
##         calls refused with "validation_error" in report_rejections; and
##         for each DECLINED tool starting with "sim.", add to
##         declined_simulation_fms every failure mode of the current
##         verdicts that needs a simulation (NEEDS_SIMULATION or
##         structural_status "fragile"), without duplicates.
##
## [ ] 11. `main()`: an ArgumentParser(prog="evals.run") with --cases
##         (nargs="*", default: the stem of every persona file) and --out
##         (Path, default evals/results/latest); parse, create the out
##         folder and asyncio.run(_run_all(args)).
## [ ] 12. `async _run_all(args)`: open AgentClient(EVALS_BASE_URL,
##         EVALS_ACCESS_CODE) from os.environ (header SETUP) and, for each
##         case, write <case>.json and <case>.transcript.json and print the
##         metrics. End the file with the usual
##         `if __name__ == "__main__": main()` guard.
## [ ] 13. Check: with the stack running, run ONE case and read its
##         transcript, then run all cases and commit the folder as
##         evals/results/baseline/ (header ACTIVATE; add --out <folder>):
##           | uv run python -m evals.run --cases bitcoin
##
## Guide 13.3
## [ ] 14. `async run_scenarios(client)`: for each item of the "scenarios"
##         list in SCENARIOS, create a session (with the text of its `spec`
##         file, if any); if `preverified`, run the unscored setup turn
##         "Please verify this design."; then one turn with sc["user"] and
##         approve=None. A scenario passes when `expect` is a
##         subsequence of the called tools and no `forbid` tool was called:
##           | it = iter(called)
##           | in_order = all(any(c == e for c in it) for e in sc["expect"])
##         Append {id, called, passed, forbidden_called} for each one.
## [ ] 15. In main: the flag --scenarios-only (store_true), and after
##         parsing `if args.scenarios_only: args.cases = []` (no cases).
##         In _run_all: after the cases, still inside `async with`, run the
##         scenarios; after it, write scenarios.json and print
##         "scenarios passed: x/y".
## [ ] 16. Check: `uv run python -m evals.run --scenarios-only`. Then run
##         the cases and the scenarios again into the baseline folder.
##
## Guide 13.4
## [ ] 17. `compare(baseline: Path, new: Path)`: for each case file of the
##         baseline (*.json except scenarios.json and *.transcript.json,
##         which are lists, not metrics), print the case with the
##         differences of the numeric keys present in both (bools are not
##         numbers here), or "missing" when `new` has no such file. Then,
##         when both folders have scenarios.json, print the passed counts
##         and the ids whose result changed.
## [ ] 18. In main: --compare (nargs=2, type=Path, metavar BASELINE NEW);
##         when given, call compare(*args.compare) and return before
##         creating any folder.
## [ ] 19. Check: compare a new run with the baseline:
##           | uv run python -m evals.run --compare evals/results/baseline <new>
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import argparse
import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

## httpx2: the HTTP client the MCP SDK and the Anthropic SDK (1.x) are built on;
## using the same library everywhere means one dependency, one set of behaviours.
import httpx2 as httpx
import yaml

from evals.metrics import RunRecord, ToolCallRecord, summarise
from evals.simulated_designer import SimulatedDesigner, answer_forms, correct_forms

## Paths are relative to the repository root (run from there).
EXAMPLES = Path("examples")
PERSONAS = Path("evals/personas")
SCENARIOS = Path("evals/scenarios/tool_selection.yaml")
## Safety net: an interview that has not finished after this many user turns
## counts as failed (and stops spending credits).
MAX_TURNS = 40
REPORT_TURNS = 8  # turns allowed after the interview to get the report written
## Verdict statuses that call for a simulation (with structural_status
## "fragile"), as in evals/metrics.py missed_simulations().
NEEDS_SIMULATION = {"inconclusive"}


## --- A tiny client for the agent service ------------------------------------------------------
class FormRejected(Exception):
    """The agent refused the form answers (HTTP 422, agent/forms.py)."""

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.detail = detail


class AgentClient:
    """Logs in once, then plays the role of the chat page."""

    def __init__(self, base_url: str, access_code: str) -> None:
        self.base = base_url.rstrip("/")
        self.access_code = access_code
        # The Origin header must equal the site's address: the agent
        # service rejects POSTs from other origins (CSRF defence, agent/auth.py).
        self.http = httpx.AsyncClient(
            base_url=self.base, headers={"Origin": self.base}, timeout=600
        )

    async def __aenter__(self) -> "AgentClient":
        r = await self.http.post("/agent/login", json={"access_code": self.access_code})
        r.raise_for_status()
        # The agent sets the login cookie with the Secure flag. Browsers
        # accept Secure cookies on http://localhost, but Python's cookie jar
        # (used by httpx) never sends them over plain http://, so every
        # later call would get 401. Copying the cookies into the client as
        # plain cookies works with http:// and https:// alike.
        self.http.cookies = {c.name: c.value for c in r.cookies.jar if c.value is not None}
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.http.aclose()

    async def new_session(self, spec_yaml: str | None = None) -> str:
        r = await self.http.post("/agent/sessions", json={})
        r.raise_for_status()
        sid: str = r.json()["session_id"]
        if spec_yaml is not None:
            # The same endpoint the form uses to hand a spec to the chat (guide 9.3).
            (
                await self.http.post(f"/agent/sessions/{sid}/spec", json={"yaml": spec_yaml})
            ).raise_for_status()
        return sid

    async def turn(
        self,
        sid: str,
        text: str,
        *,
        approve: bool | None = True,
        form_answers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one user message; read the event stream until `done`.

        Expensive tools ask for confirmation first (confirmation_required).
        `approve` is the user's answer: True approves, False declines (the
        agent is told and continues), None leaves the questions open and
        ends the turn (scenarios score only the tools chosen in the turn).
        """
        out: dict[str, Any] = {
            "text": "",
            "tools": [],
            "verdicts": None,
            "done": None,
            "declined": [],
            "tokens": 0,
            "forms": {},  # tool_use_id -> form, for form_requested events
            "seconds": 0.0,  # wall-clock time until `done`, confirmations included
        }
        body: dict[str, Any] = {"text": text}
        if form_answers:
            body["form_answers"] = form_answers
        started = time.monotonic()
        while True:
            to_confirm: dict[str, str] = {}  # tool_use_id -> tool id
            async with self.http.stream("POST", f"/agent/sessions/{sid}/messages", json=body) as r:
                if r.status_code == 422:  # noqa: PLR2004 - form answers refused
                    await r.aread()
                    raise FormRejected(r.json().get("detail", {}))
                r.raise_for_status()
                async for event in _sse_events(r):
                    kind = event.get("type")
                    if kind == "text_delta":
                        out["text"] += event["text"]
                    elif kind == "tool_finished":
                        out["tools"].append(
                            {
                                "tool": event["tool"],
                                "ok": event["ok"],
                                "error_code": event.get("error_code"),
                            }
                        )
                    elif kind == "verdict_updated":
                        out["verdicts"] = event["verdicts"]
                    elif kind == "confirmation_required":
                        to_confirm[event["tool_use_id"]] = event["tool"]
                    elif kind == "form_requested":
                        out["forms"][event["tool_use_id"]] = event["form"]
                    elif kind == "done":
                        out["done"] = event["reason"]
                        out["tokens"] += sum(event.get("usage", {}).values())
            if out["done"] == "awaiting_confirmation" and to_confirm and approve is not None:
                if not approve:
                    out["declined"] += list(to_confirm.values())
                body = {"text": "", "confirmations": dict.fromkeys(to_confirm, approve)}
                continue
            out["seconds"] = time.monotonic() - started
            return out

    async def session(self, sid: str) -> dict[str, Any]:
        r = await self.http.get(f"/agent/sessions/{sid}")
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    async def spec(self, sid: str) -> dict[str, Any] | None:
        r = await self.http.get(f"/agent/sessions/{sid}/spec")
        if r.status_code >= 500:  # noqa: PLR2004 - seen once, transient: retry once
            await asyncio.sleep(5)
            r = await self.http.get(f"/agent/sessions/{sid}/spec")
        r.raise_for_status()
        text = r.json().get("yaml")
        return yaml.safe_load(text) if text else None


async def _sse_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse a text/event-stream: blocks of "event: ..." / "data: ..." lines
    separated by a blank line (the format agent/events.py writes). Each
    data JSON includes its own "type", so the `event:` line can be ignored."""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            yield json.loads("\n".join(data_lines))
            data_lines = []


## --- One simulated interview ----------------------------------------------------------------------
def _record_turn(record: RunRecord, turn: dict[str, Any]) -> None:
    """Add what one turn's events tell the metrics to the run record."""
    record.tool_calls += [ToolCallRecord(**t) for t in turn["tools"]]
    if turn["verdicts"] is not None:
        record.verdicts = turn["verdicts"]
    record.agent_tokens += turn["tokens"]
    # The report tool refuses a narrative with numbers not found in the
    # results as invalid input (guide 10.2; evals/README.md).
    record.report_rejections += sum(
        1
        for t in turn["tools"]
        if t["tool"] == "report.render_pdf.v1" and t["error_code"] == "validation_error"
    )
    # A declined simulation is an explicit user decision for the failure
    # modes that needed one at that moment: they are not "missed".
    if any(tool.startswith("sim.") for tool in turn["declined"]):
        for v in record.verdicts:
            needs = v.get("status") in NEEDS_SIMULATION or v.get("structural_status") == "fragile"
            if needs and v["failure_mode"] not in record.declined_simulation_fms:
                record.declined_simulation_fms.append(v["failure_mode"])


def _said(turn: dict[str, Any]) -> str:
    """The interviewer's words for the designer (an empty turn still needs a reply)."""
    return turn["text"].strip() or "(The interviewer sent an empty message.)"


async def _send(
    client: AgentClient,
    designer: SimulatedDesigner,
    sid: str,
    message: str,
    forms_seen: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any] | None:
    """Send the designer's next input: its form answers if forms are open, else its text.

    Returns the agent's turn, or None when the designer refused. Answers the
    page refuses are corrected by the designer, at most twice, as a person
    would after the error message. If no valid answers come out of that, the
    designer carries on in words (counted as a form fallback).
    """
    if not forms_seen:
        return await client.turn(sid, message, approve=designer.approves_expensive_tools)
    answers = await answer_forms(designer, message, forms_seen)
    for _ in range(3):
        if answers is None:
            break
        try:
            return await client.turn(
                sid, "", approve=designer.approves_expensive_tools, form_answers=answers
            )
        except FormRejected as exc:
            stats["form_rejections"] += 1
            answers = await correct_forms(designer, exc.detail)
    if designer.refused:
        return None
    # Still refused: carry on in words, as a person would give up on the form.
    stats["form_fallbacks"] += 1
    return await client.turn(
        sid, "I could not fill in the form; please ask me in words.",
        approve=designer.approves_expensive_tools,
    )


async def run_case(client: AgentClient, case: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns (metrics, transcript)."""
    designer = SimulatedDesigner(PERSONAS / f"{case}.yaml", EXAMPLES / f"{case}.yaml")
    sid = await client.new_session()
    transcript: list[dict[str, Any]] = []
    record = RunRecord(
        case=case,
        elicited_spec=None,
        hidden_spec=yaml.safe_load((EXAMPLES / f"{case}.yaml").read_text()),
        user_turns=0,
    )
    stats: dict[str, Any] = {
        "form_rejections": 0,
        "form_fallbacks": 0,
        "forms": 0,
        "seconds": [],
        "tool_errors": 0,
    }

    async def step(message: str, forms: dict[str, Any]) -> dict[str, Any] | None:
        record.user_turns += 1
        turn = await _send(client, designer, sid, message, forms, stats)
        if turn is None:
            record.designer_refused = True
            return None
        stats["seconds"].append(turn["seconds"])
        stats["forms"] += len(turn["forms"])
        stats["tool_errors"] += sum(1 for t in turn["tools"] if not t["ok"])
        transcript.append({
            "user": "(form answers)" if forms else message,
            "agent": turn["text"],
            "forms": turn["forms"],
            "tools": turn["tools"],
            "seconds": round(turn["seconds"], 1),
            "done": turn["done"],
        })
        _record_turn(record, turn)
        return turn

    # The designer opens the conversation, as a real user would.
    opening = await designer.answer(
        "Hello! I'd like help designing a token economy. Please introduce yourself briefly."
    )
    turn = await step(opening, {}) if opening is not None else None
    for _ in range(MAX_TURNS - 1):
        if turn is None:
            break
        state = (await client.session(sid))["state"]
        if state in {"verified", "simulated", "reported"} and turn["done"] == "final_answer":
            break
        reply = turn["text"] if turn["forms"] else await designer.answer(_said(turn))
        if reply is None:
            record.designer_refused = True
            break
        turn = await step(reply, turn["forms"])
    interview_turns = record.user_turns

    # Then the report, which tests explanations, simulations and the number check.
    message: str | None = "Thank you. Please run what you recommend and write the final report."
    forms: dict[str, Any] = {}
    for _ in range(REPORT_TURNS):
        if turn is None or message is None or (await client.session(sid))["state"] == "reported":
            break
        turn = await step(message, forms)
        if turn is None:
            break
        forms = turn["forms"]
        message = turn["text"] if forms else await designer.answer(_said(turn))

    session = await client.session(sid)
    record.elicited_spec = await client.spec(sid)
    record.open_decisive_slots = session["open_decisive_slots"]
    record.designer_tokens = designer.usage_input_tokens + designer.usage_output_tokens
    metrics = summarise(record)
    seconds = stats["seconds"]
    metrics.update({
        "interview_turns": interview_turns,
        "final_state": session["state"],
        "reported": session["state"] == "reported",
        "forms_shown": stats["forms"],
        "form_rejections": stats["form_rejections"],
        "form_fallbacks": stats["form_fallbacks"],
        "tool_errors": stats["tool_errors"],
        "agent_seconds_total": round(sum(seconds), 1),
        "agent_seconds_mean_turn": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "agent_seconds_max_turn": round(max(seconds), 1) if seconds else None,
        "session_id": sid,
    })
    return metrics, transcript


def main() -> None:
    p = argparse.ArgumentParser(prog="evals.run")
    p.add_argument("--cases", nargs="*", default=[f.stem for f in PERSONAS.glob("*.yaml")])
    p.add_argument("--out", type=Path, default=Path("evals/results/latest"))
    ## Guide 13.3: run only the scenarios (= no cases).
    p.add_argument("--scenarios-only", action="store_true")
    ## Guide 13.4: compare two result folders instead of running anything.
    p.add_argument("--compare", nargs=2, type=Path, metavar=("BASELINE", "NEW"))
    args = p.parse_args()

    ## Guide 13.3: --scenarios-only simply means "no cases".
    if args.scenarios_only:
        args.cases = []
    ## Guide 13.4: --compare runs nothing.
    if args.compare:
        compare(*args.compare)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run_all(args))


async def _run_all(args: argparse.Namespace) -> None:
    async with AgentClient(os.environ["EVALS_BASE_URL"], os.environ["EVALS_ACCESS_CODE"]) as client:
        for case in args.cases:
            metrics, transcript = await run_case(client, case)
            (args.out / f"{case}.json").write_text(json.dumps(metrics, indent=2))
            (args.out / f"{case}.transcript.json").write_text(json.dumps(transcript, indent=2))
            print(case, metrics)
        ## Guide 13.3: the scenarios always run, after the cases.
        scen = await run_scenarios(client)
    ## Guide 13.3: their results.
    (args.out / "scenarios.json").write_text(json.dumps(scen, indent=2))
    print(f"scenarios passed: {sum(r['passed'] for r in scen)}/{len(scen)}")


## --- Tool-selection scenarios ------------------------------------------------------------------------
## Guide 13.3: the scenarios (commented twice until then).
async def run_scenarios(client: AgentClient) -> list[dict[str, Any]]:
    """Each scenario: prepared session + one user message -> compare the
    tools the agent called with `expect` (in this order, other calls may be
    interleaved) and `forbid` (must not be called)."""
    results = []
    for sc in yaml.safe_load(SCENARIOS.read_text())["scenarios"]:
        spec_yaml = Path(sc["spec"]).read_text() if sc.get("spec") else None
        sid = await client.new_session(spec_yaml)
        # The agent is not told when a spec arrives from the form (only the
        # session stores it), so the user says it, as after "Open in form".
        loaded = "My design is already loaded in this session (I filled it in with the form). "
        user = sc["user"]
        if sc.get("preverified"):
            # Setup turns, NOT scored: bring the session to `verified`. A
            # model may stop after validating, so ask again (at most twice).
            setup = loaded + "Please verify this design."
            for _ in range(3):
                await client.turn(sid, setup)
                if (await client.session(sid))["state"] in {"verified", "simulated", "reported"}:
                    break
                setup = "Please run the verification (verify.run.v1) on the loaded design now."
        elif spec_yaml is not None:
            user = loaded + user
        turn = await client.turn(sid, user, approve=None)
        called = [t["tool"] for t in turn["tools"]]
        seconds = round(turn["seconds"], 1)
        it = iter(called)
        in_order = all(any(c == e for c in it) for e in sc["expect"])
        forbidden = sorted(set(called) & set(sc.get("forbid", [])))
        results.append(
            {
                "id": sc["id"],
                "called": called,
                "passed": in_order and not forbidden,
                "forbidden_called": forbidden,
                "seconds": seconds,
                "reply": turn["text"][:2000],
            }
        )
    return results


## --- Comparing with the baseline -------------------------------------------------------------------------
## Guide 13.4: the comparison (commented twice until then).
def compare(baseline: Path, new: Path) -> None:
    """Print metric deltas per case and scenario changes; paste the output into the PR."""
    for f in sorted(baseline.glob("*.json")):
        # Only the per-case metric files hold numbers to compare; the
        # transcripts and scenarios.json are lists.
        if f.name == "scenarios.json" or f.name.endswith(".transcript.json"):
            continue
        other = new / f.name
        if not other.exists():
            print(f.stem, "missing")
            continue
        b, n = json.loads(f.read_text()), json.loads(other.read_text())
        # bool is a subclass of int in Python: keep flags out of the deltas.
        deltas = {
            k: n[k] - b[k]
            for k in b
            if isinstance(b[k], (int, float))
            and not isinstance(b[k], bool)
            and isinstance(n.get(k), (int, float))
        }
        print(f.stem, json.dumps(deltas))
    bs, ns = baseline / "scenarios.json", new / "scenarios.json"
    if bs.exists() and ns.exists():
        old = {r["id"]: r["passed"] for r in json.loads(bs.read_text())}
        cur = {r["id"]: r["passed"] for r in json.loads(ns.read_text())}
        print(f"scenarios passed: {sum(old.values())}/{len(old)} -> {sum(cur.values())}/{len(cur)}")
        for sid in sorted(set(old) | set(cur)):
            if old.get(sid) != cur.get(sid):
                print(f"  {sid}: {old.get(sid)} -> {cur.get(sid)}")


if __name__ == "__main__":
    main()
