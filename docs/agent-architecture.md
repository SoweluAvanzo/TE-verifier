# Agent platform architecture

**Status:** proposed design, v0.1 (2026-10-19). Nothing in this document is
implemented yet except the existing verifier, simulator and web app it builds
on. The step-by-step build plan is in
[agent-implementation-guide.md](agent-implementation-guide.md). The normative
tool rules are in [`policy/tool_policy.yaml`](../policy/tool_policy.yaml).

This document specifies how to turn the Token Economy Verifier into a platform
that LLM agents can use to help people design token economies:

- an **MCP server** that exposes the verifier, the agent-based simulator, the
  literature collection and the report generator as reusable tools reachable
  from the internet;
- an **interviewing agent** that elicits the requirements in conversation
  instead of making the user fill in the form, then chooses and runs the
  right tools, explains the results, and produces a downloadable PDF report;
- a **chat interface** in the existing web app, powered by the Anthropic API
  by default, with the model provider swappable.

Every design decision is recorded in §5 with its rationale and the
alternatives that were rejected.

---

## 1. Principles

These principles carry over from [CLAUDE.md](../CLAUDE.md) and the DLT2026
paper. Every component has to respect them.

| # | Principle | Consequence |
|---|---|---|
| P1 | **The LLM never computes a verdict or a number.** | Verdicts, critical values, probabilities and counterexamples come only from tool output. The LLM interviews, chooses among the tools the policy allows, and explains. Reports are filled from data; narrative text is checked against it. |
| P2 | **Formal methods first, simulation as the fallback.** | Enforced by the server (precondition `verified_spec`), not left to the prompt. |
| P3 | **One source of truth per concern.** | Spec shape → Pydantic models in `schema/`. Paper copy → `verifier/paper.py`. Tool rules → `policy/tool_policy.yaml`. Interview rules → `policy/elicitation_protocol.yaml`. Nothing is duplicated by hand. |
| P4 | **"I don't know" is a first-class answer.** | Unknown inputs are swept by the verifier, never filled in by guessing. |
| P5 | **Reproducibility and provenance.** | Every result is tied to a content hash of the exact spec, verifier version and config. Every answer records the user's own words. Every report lists both. |
| P6 | **The tool set is extensible.** | New tools plug in through a registry. Each must declare its usage contract and ship contract tests and selection-eval scenarios. |
| P7 | **Secure by default on the public internet.** | Authentication, quotas, resource limits, least-privilege containers. Content from users, papers and tools is treated as untrusted data. |

---

## 2. System overview

```
             ┌──────────────────────────────── Internet ────────────────────────────────┐
             │ Browser (form, /explore, /chat)   MCP clients (Claude Desktop/Code, other │
             │                                   agents, partner pipelines)              │
             └───────────────┬─────────────────────────────────────┬────────────────────┘
                             │ HTTPS                               │ HTTPS (MCP, OAuth/API key)
┌─ docker compose (one host) ▼─────────────────────────────────────▼────────────────────┐
│ caddy        TLS termination, reverse proxy, security headers, coarse rate limits     │
│   ├─ /, /chat     → web      Flask (existing): form, /yaml, /explore, /chat page, API │
│   ├─ /agent/*     → agent    FastAPI: chat API, agent loop, SSE streaming             │
│   └─ /mcp         → mcp      MCP server (Streamable HTTP): tools, resources, prompts  │
│                                                                                        │
│ worker       RQ workers: simulation jobs, PDF rendering, literature ingestion         │
│ postgres     sessions, spec versions, answers, verifications, jobs, reports,          │
│              literature (metadata + chunks, full-text search, later pgvector)         │
│ redis        job queue, short-lived caches, rate-limit counters                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
      web, agent, mcp and worker are built from ONE repository and ONE Python package
      (te_platform), which imports the existing schema/ and verifier/ packages.
```

**Two ways in, one set of rules.** A browser user talks to `agent`, which is
itself an MCP client of `mcp`. An external agent talks to `mcp` directly.
Both go through the same tools, preconditions and quotas. The web app's
existing REST API calls the same service layer, so the form, the chat and
external agents can never get different answers for the same spec.

---

## 3. Components

### 3.1 `te_platform.service`: the service layer

A thin facade over the existing code. Every caller uses it: Flask routes, MCP
tools, the worker and the agent.

```python
validate(spec) -> ValidationResult                     # schema + coherence + hash + yaml
verify(spec, config=None) -> VerificationResult        # verifier.verify + verifier.minimal
minimal(spec, config=None) -> list[dict]               # the triage only
merged_verdicts(result) -> list[dict]                  # each verdict + its structural status
fm_id("FM1: Token Oversupply / Inflation") -> "FM1"    # short failure-mode id
simulate(spec, *, n_runs, horizon, seed, failure_modes=None,
         skip_non_fragile=True, record_trajectories=False) -> dict   # verifier.abm.run_simulation
trajectory(spec, *, horizon, seed, max_agents) -> dict                 # verifier.abm.run_explore
flow_graph(spec) -> dict
export_cadcad(spec, *, n_runs=500, horizon=260, seed=None) -> dict
```

`spec` is always YAML text or an already-parsed dict. Keyword arguments
make every call site readable, and the input bounds (maximum runs, horizon,
agents) are applied inside these functions, so no caller can bypass them.

- **Content addressing.** `spec_hash = sha256(canonical_json(normalised_spec))`.
  `verification_ref = sha256(spec_hash ‖ verifier_version ‖ config_hash)`.
  Canonical JSON means sorted keys, no insignificant whitespace, and a fixed
  float formatting.
- **No I/O.** The service layer doesn't touch the network or the database.
  Persistence is the caller's job, which keeps the service layer pure and
  easy to test.

### 3.2 `te_platform.registry`: tool registry and policy

- **Tool definition.** A tool is a Python module that exports a `ToolSpec`
  named `TOOL`: `ToolSpec(id, input_model, output_model, handler, title="")`.
  Its `id` is the key of its entry in `policy/tool_policy.yaml`, where its
  rules live (cost class, preconditions, when to use it); code and rules
  are kept apart on purpose (D3).
- **Discovery.** Tools are found through Python entry points
  (`[project.entry-points."te_platform.tools"]`). A third-party package can add
  tools without modifying this repository.
- **Startup checks.** The registry loads the policy and **fails at startup**
  when:
  - a tool is registered but missing from the policy, or the other way round;
  - a precondition, predicate or argument-builder name doesn't resolve to a
    function, or a registered rule is never used by the policy;
  - a tool id named in `tools_by_state`, `always_available`,
    `suggested_next`, `typical_next` or a precondition's `do_first` does not
    exist.

  Tools described in the policy but not built yet are listed under
  `planned`; the registry starts without them and never offers them, so the
  platform works at every phase of the build.
- **Execution pipeline for every call.** The steps run in this order:
  1. authenticate the caller;
  2. check the quota;
  3. validate the input model;
  4. derive the facts the rules need (the spec's hash and validity, and
     whether a presented `verification_ref` was computed from this very
     spec; no database needed, because the ref is a content hash, D5);
  5. check the preconditions;
  6. run the handler, with a timeout;
  7. validate the output model;
  8. append `suggested_next`;
  9. write an audit log entry (from phase 5.5: who called which tool, the
     outcome, the latency, any `override_reason`, and the correlation ID).

  Over MCP, every tool result carries this pipeline's whole outcome:
  `{ok, result | error, suggested_next, correlation_id}`, the same
  self-describing shape for every client.

  The transport layers (MCP, REST, agent) never bypass this pipeline.
- **Tool descriptions.** The description the model sees is **generated** from
  the policy fields (`summary`, `use_when`, `do_not_use_when`, `returns`,
  `typical_next`), so the documentation and the behaviour can't drift apart.

### 3.3 `te_platform.mcp_server`: the public tool surface

Built on the official MCP Python SDK (`mcp` ≥ 2.3), using its **low-level
server** (`mcp.server.lowlevel.Server`, with the handlers `on_list_tools`,
`on_call_tool`, `on_list_resources`, `on_read_resource`, `on_list_prompts`,
`on_get_prompt`) rather than the higher-level `MCPServer`. The reason: the
higher-level class builds each tool's input schema from a Python function
signature and validates the arguments itself, while our schemas come from
the tools' Pydantic models and the raw arguments must reach the pipeline,
which is the ONE place that validates (D4). It is served over HTTP with
`Server.streamable_http_app(...)` behind uvicorn (`mcp_server/http_app.py`),
and over stdio with
`mcp.server.stdio.stdio_server`. It exposes three kinds of MCP primitives.

**Tools.** Every registry tool, with MCP annotations (`readOnlyHint` and
similar) taken from the policy. Every result carries the pipeline's whole
outcome, `{ok, result | error, suggested_next, correlation_id}`, both as
JSON text and as structured content.

**Resources:**

| URI | Content |
|---|---|
| `te://schema/te-ir` | JSON Schema generated from `schema.TokenEconomy` |
| `te://paper/conditions` | the six failure-mode conditions and their explanations, from `verifier/paper.py` |
| `te://examples/{name}` | the case-study specs in `examples/` |
| `te://policy/tools` | this tool policy |
| `te://protocol/elicitation` | the elicitation protocol (§4) |

**Prompts:**

| Prompt | Purpose |
|---|---|
| `interview_token_economy` | the interviewer method (§4.2) plus the protocol |
| `explain_report` | turn a verification result into plain language for a stated audience |
| `design_review` | critique an existing spec against the six failure modes |

**Transport and limits.**
- Use Streamable HTTP in production and stdio for local development and
  Claude Desktop/Code.
- Turn on DNS-rebinding protection (`TransportSecuritySettings`) with an
  explicit list of allowed hosts and origins.
- Cap the request body size.

**Auth.** API keys first (guide 4.2): stored as hashes, sent as a bearer
token, checked by our own small ASGI middleware (`mcp_server/auth.py`) in
front of the MCP app. The agent service calls with its own *service* key
and names the logged-in user in an `X-TE-On-Behalf-Of` header, which the
middleware accepts only from a service key. OAuth 2.1, following the MCP
authorization specification, comes later (guide 12.6) through the SDK's
`token_verifier` and `AuthSettings`, once third parties need delegated
access.

**Correlation IDs.** A correlation ID identifies one request across
services. The agent sends one per chat turn in an `X-Correlation-ID`
header; the MCP server uses it for the call (or creates one), returns it in
every result, passes it into job payloads, and the worker binds it in its
logs, so one turn can be followed end to end (guide 12.5).

**Interviews from any client.** `elicit.next_questions.v1` called without
a `session_id` creates a new design session and returns its id, so any MCP
client (not only our chat) can run the interview with the
`interview_token_economy` prompt (D16).

**State-gated tool lists.** MCP's tool list is per server, not per session.
So the MCP server lists every tool and **enforces** the rules through
preconditions. The `agent` service *filters* the list it gives the LLM using
`tools_by_state`. External clients still get precise `precondition_failed`
errors with `do_first` hints. Per-session filtering through middleware and
`tools/list_changed` notifications can come later, without changing any tool.

**Long-running work.** Expensive tools enqueue an RQ job and return a
`job_id`. Clients call `jobs.status.v1`, which returns `retry_after_s`.
Results are stored under the `verification_ref`, so an identical seeded
request from the same user is answered from cache. Results are never shared
between users: the job id includes who asked.

### 3.4 `te_platform.agent`: the interviewing agent

A FastAPI service. People are authenticated by the login cookie (§3.5);
towards the MCP server the agent uses its own service key plus the
`X-TE-On-Behalf-Of` header (§3.3), so ownership checks and quotas apply to
the user, not to the agent.

- **Endpoints.**
  - `POST /agent/login`, `POST /agent/logout` (§3.5).
  - `POST /agent/sessions` creates a session (recording the policy and
    protocol versions in force).
  - `POST /agent/sessions/{id}/messages` sends a user message. The response is
    a Server-Sent Events stream of text, tool activity and spec-panel updates.
    Each event's JSON carries its `type` (also given on the SSE `event:`
    line), so a client can read the data alone.
  - `GET /agent/sessions/{id}` returns `{session_id, state, spec_hash,
    open_decisive_slots, messages}`.
  - `GET` / `POST /agent/sessions/{id}/spec` read and replace the session's
    spec (the form ↔ chat round trip, §3.5).
  - `GET /agent/reports/{report_id}?exp=…&sig=…` downloads a report (§3.6).
- **The loop.** We run the agent loop ourselves:
  1. Connect to `mcp` as an MCP client.
  2. Take the tools allowed in the session's state (`tools_by_state` and
     `always_available`) and convert them to the provider's tool format.
  3. Call the model.
  4. Run the requested tool calls through MCP, with the session's identity
     injected.
  5. Feed the results back to the model, and repeat until it produces a final
     answer.
- **Limits on each turn.** At most N tool calls, at most T seconds, and a
  token budget per session. When a limit is hit, the agent stops and tells
  the user plainly.
- **Provider adapter.** The interface is
  `ChatProvider.stream(system, messages, tools) -> AsyncIterator[Event]`. The
  first implementation is `AnthropicProvider` (official `anthropic` SDK, model
  `claude-opus-5-5`, streaming, adaptive thinking). Another provider is one
  more class plus a run of the evaluation suite (§3.9).
- **Prompt layout, for caching.** The order is: tools → system (interviewer
  method + protocol excerpt + tool policy summary), which never changes and
  carries the cache breakpoint → conversation. Anything that changes per
  request (time, session ID, spec state) goes *after* the cached prefix. The
  model learns the current spec and the open questions from tool results
  (`elicit.next_questions.v1`, `elicit.record_answer.v1`, `spec.validate.v1`),
  never by editing the system prompt.
- **Asking before expensive work.** Before an `expensive` tool the agent asks
  the user, for example "this simulation takes about a minute; run it?". This
  follows `cost_classes` in the policy.

### 3.5 Chat interface (`/chat` in the existing web app)

- The chat column is on the left. The **live spec panel** is on the right:
  each protocol slot shown as committed / unknown (swept) / conflicting /
  not applicable, the latest verdict per failure mode, job progress, and
  report download links.
- **The form and the chat edit the same session spec.** An "Open in form"
  button loads the session's current spec version into `/`. Edits saved from
  the form create a new spec version that the agent sees on its next turn.
  A question counts as answered when it has an answer OR the spec already
  has a value at its field, so a spec loaded whole from the form (or an
  uploaded YAML) answers its own questions and the session can move on to
  verification.
- **Login with personal access codes.** People are invited: an operator
  runs `te-platform users create --email …`, which prints a long random
  access code once and stores only its hash, as with API keys. The person
  types it on `/login`; the agent service checks it, rate-limits attempts per
  IP, and sets an `HttpOnly`, `Secure`, `SameSite=Lax` session cookie. No
  e-mail or identity-provider infrastructure is needed for a research tool
  with invited users. University single sign-on (OAuth / OpenID Connect,
  §3.3 and guide 12.6) can replace the code check later, because it only has
  to end by creating the same session.
- **Plain JavaScript, as in the rest of the web app.** It reads the event
  stream with `fetch` and a stream reader (the browser's `EventSource` only
  supports GET requests, and sending a message is a POST). Markdown from the model is rendered with `marked` and
  **always sanitised with DOMPurify** before it reaches the DOM.

### 3.6 Reports (`report.render_pdf.v1`)

- **Generation.** HTML → PDF with WeasyPrint, from Jinja2 templates. Charts
  are drawn on the server with matplotlib as SVG.
- **Fixed sections, filled from data:** cover and provenance (spec hash,
  verification_ref, verifier version, policy and protocol versions,
  overrides), the spec summary, the verdict table, per-failure-mode
  conditions with critical values, counterexamples, recommendations,
  simulation results, and cited literature.
- **Narrative sections**, such as the executive summary and the explanation
  for the stated audience, are written by the agent and visibly labelled. The
  tool extracts every number from the narrative and **rejects** the request
  if a number is missing from the referenced verification and the latest
  finished simulation of it (P1); the renderer checks again as a safety net.
- **Citations.** The agent passes the `lit.search.v1` hits it relied on as
  the report's `citations`; they are printed in the report.
- **Storage and download.** Reports are stored with their inputs, so they can
  be regenerated exactly. A download link (`/agent/reports/{id}?exp&sig`,
  served by the agent service) needs BOTH a valid, unexpired signature (an
  HMAC made with a key held by the MCP server, which signs, and the agent,
  which verifies) AND the logged-in user owning the report: a leaked link is
  useless to anyone else.

### 3.7 Literature collection (`lit.search.v1`)

- **Data model.** Each work has metadata (citation key, DOI, authors, year,
  venue, licence, full-text permission). Each work is split into chunks
  stored as `(work_id, section, page, text)`.
- **Search.** Phase 1 uses PostgreSQL full-text search (`tsvector`,
  `ts_rank_cd`). Phase 2 adds pgvector embeddings and hybrid ranking, once
  the evaluation shows keyword search is the bottleneck.
- **Licensing.** Full text is stored only where the licence allows it. The
  public endpoint returns metadata, abstracts and **short passages** only,
  never whole copyrighted documents.
- **Curation.** Papers are added through a reviewed ingestion command (§4.4
  lists the seed collection), not by uploads from end users.

### 3.8 Persistence (PostgreSQL)

| Table | Holds |
|---|---|
| `users`, `api_keys` | identity; only hashes of access codes and API keys are stored |
| `sessions` | owner, protocol_version, policy_version, pending tool confirmations, created_at (the state is derived, never stored) |
| `spec_versions` | session_id, version, spec JSONB, spec_hash, author (user/agent/form), created_at |
| `answers` | session_id, slot_id, indices (which token, for per-token questions), value JSONB, status, user_quote, spec_version |
| `verifications` | verification_ref (PK; it already encodes the verifier version and config, D5), spec_hash, result JSONB |
| `jobs` | job_id, kind, verification_ref, params, status, result JSONB, owner, session, timings |
| `reports` | report_id, verification_ref, narrative, file path/blob, expires_at |
| `messages` | session_id, role, content JSONB, tool calls, token usage |
| `audit_log` | caller, tool, input hash, outcome, latency, override_reason |
| `works`, `chunks` | the literature collection |

Spec versions and verifications are **append-only**. Every per-user query is
filtered by owner; the one exception is `verifications`, which are shared:
a row is found only by its content-addressed `verification_ref`, i.e. by
someone who already holds that exact spec, so it reveals nothing new. The
schema is managed by Alembic migrations.

### 3.9 Evaluation harness (`evals/`)

- **Simulated designers.** An LLM plays the designer of each case study in
  `examples/*.yaml`. It holds the true spec and the persona, and answers only
  what it is asked. The interviewer never sees the true spec.
- **Metrics:**
  - field accuracy against the true spec;
  - agreement with the true spec's verdicts;
  - number of turns;
  - decisive slots missed;
  - precondition violations;
  - unnecessary simulations, and simulations missed on inconclusive results;
  - narrative-number check failures;
  - designer refusals and the token usage of both models (cost).
- **Tool-selection scenarios.** A YAML file of situations paired with the
  expected tool-call sequence. Each tool's contribution must add at least
  three.
- **When it runs.** In CI, on every change to prompts, the policy, the
  protocol, tool descriptions or the model/provider. The results are the
  regression baseline.

---

## 4. Elicitation protocol

### 4.1 Rules: `policy/elicitation_protocol.yaml` (to be written in step 7 of the guide)

Each protocol **slot** is one piece of information to collect. It declares:
- `ir_path`, the field of the TE-IR it fills;
- `feeds`, the failure modes that use it;
- `criticality`: `decisive`, `important` or `bookkeeping`;
- `answer_type`;
- `allow_unknown`;
- `intent`, what the question is trying to learn;
- `why_we_ask`, a *reference* into `verifier/paper.py`;
- `probes`, follow-up questions;
- `elicitation_method` (e.g. `quartile_range` for uncertain quantities);
- `validation`, the coherence rules it takes part in;
- an `applies_when` routing predicate (archetype, token count, and so on).

Stages follow [specification-flow.md](specification-flow.md), stages 0–11.

**Tests enforce coverage:**
- every parameter in the paper's failure-mode table is fed by at least one
  slot;
- every `ir_path` exists in the schema;
- every routing predicate refers only to slots collected earlier;
- each case study in `examples/` can be fully reproduced by answering the
  protocol.

### 4.2 Method: the `interview_token_economy` prompt (Agent Skills format)

**Behaviour.** The interviewer:
- asks one or two questions per turn and says why each one matters;
- asks for ranges rather than single values;
- accepts "I don't know" every time;
- never suggests a default before the user has answered, to avoid anchoring;
- at the end of each stage, restates the answers in the user's own terms and
  asks for confirmation;
- raises contradictions as soon as `spec.validate.v1` reports them;
- never records a value the user didn't state;
- cites literature only through `lit.search.v1`.

**Language.** It adapts to the user's vocabulary, never the other way round.
Formal names (`K`, `γ`, `τ̄`) are introduced only alongside a plain
explanation.

### 4.3 Ordering: the verifier chooses the next question

`elicit.next_questions.v1` runs the minimal verifier on the partial spec, with
every open slot swept. It then ranks open slots by whether pinning them down
could **change any failure-mode verdict**, using `minimum_param_shift` and
the structural triage. Slots that can't change any verdict are returned as
`not_needed` (questions with their indices); the agent records those that
allow unknown as **unknown** (swept by the verifier) without asking. A slot counts as answered when it has an answer or the spec
already has a value at its field.

**Stopping rule.** Elicitation is complete when:
- every decisive slot is committed or explicitly unknown; and
- no remaining unknown slot can change a verdict, or the user chooses to stop
  and accept the remaining sweeps.

The stage order of the specification flow remains the default path through
the questions; the verifier reorders and prunes within it. This makes
interviews short *for the specific design*, and it is a methodological
contribution that can be evaluated with §3.9.

### 4.4 Seed literature collection

Check the bibliographic details before ingesting.

- **Requirements elicitation:**
  - Zowghi & Coulin (2005), survey of elicitation techniques;
  - Davis, Dieste, Hickey, Juristo & Moreno (2006), effectiveness of
    elicitation techniques (RE'06);
  - Hickey & Davis (2004), unified model of elicitation (JMIS);
  - van Lamsweerde (2001), goal-oriented RE (RE'01);
  - Ferrari, Spoletini & Gnesi (2016), ambiguity and tacit knowledge in
    elicitation interviews (REJ).
- **LLMs in requirements engineering:**
  - Ronanki, Berger & Horkoff (2023);
  - Görer & Aydemir (2023), LLM-generated interview scripts;
  - Arora, Grundy & Abdelrazek (2023), generative AI in RE.
- **Eliciting uncertain quantities:**
  - O'Hagan et al. (2006), *Uncertain Judgements* (and the SHELF framework);
  - Morgan (2014), expert elicitation for policy (PNAS);
  - Tversky & Kahneman (1974), heuristics and biases.
- **Interview technique:**
  - Willis (2005), *Cognitive Interviewing*;
  - Reynolds & Gutman (1988), laddering.
- **Token economy design:**
  - Oliveira et al. (2018), *To Token or not to Token* (ICIS);
  - Lesavre, Varin & Yaga (2021), NIST IR 8301;
  - Zhang, Zargham & Preciado, state-space modelling of blockchain-enabled
    economic systems;
  - Cong, Li & Wang (2021), *Tokenomics: Dynamic Adoption and Valuation*
    (RFS);
  - Ostrom (1990), *Governing the Commons*;
  - the DLT2026 six-failure-modes paper (canonical).

---

## 5. Design decisions and rationale

Each decision is listed with its alternatives and the reason for the choice.
New decisions should be added in the same format, as ADRs in
`docs/adr/NNNN-title.md`.

**D1. One repository, one Python package (`te_platform`), several container
roles.**
*Alternatives:* separate repositories or packages per service.
*Why:* the tools are thin wrappers around the verifier. If they were versioned
separately, an MCP server could serve verdicts from a different verifier than
the web app. One package built into one image (with a different command per
role) makes version skew impossible. It also reuses the 910-test suite
directly and keeps the learning curve to one codebase.

**D2. A service layer shared by Flask, MCP, the worker and the agent.**
*Alternatives:* the MCP tools call the Flask REST API, or reimplement the
logic.
*Why:* calling over HTTP adds latency, failure modes and a second
serialisation contract. Reimplementing duplicates logic that has a proof
obligation behind it. A pure function layer is the only place rules live, and
the easiest to test.

**D3. The policy is a YAML file with *named* predicates; no expression
language.**
*Alternatives:* rules hard-coded in Python; an expression DSL evaluated at
runtime.
*Why:*
- YAML can be read and reviewed by the domain experts (co-authors), is
  published to clients as a resource, and generates the tool descriptions.
- Named predicates implemented in Python stay testable and type-checked.
- Using `eval` on policy strings would be a code-injection surface on a
  public server.

**D4. Preconditions are enforced on the server, not only described in the
prompt.**
*Alternative:* rely on the system prompt ("always verify before
simulating").
*Why:*
- Prompts are advice; on a public endpoint, clients are arbitrary agents with
  their own prompts.
- Server checks make P2 hold for every caller.
- Structured `do_first` errors let any model correct itself in one step.
- An explicit `override_reason`, written to the audit log, keeps legitimate
  exceptions possible (e.g. verifying before every question is answered),
  but only for the preconditions the policy marks as overridable. "Verified
  before simulating or reporting" is never overridable (P2).

**D5. Content-addressed `verification_ref`.**
*Alternative:* server-side session state alone.
*Why:*
- It lets stateless external clients satisfy "verified first" without
  creating a session.
- It makes results cacheable: the same spec, verifier and config give the
  same ref.
- It gives every report exact provenance (P5).
- It detects automatically when the spec changed after verification.

**D6. A few coarse tools rather than many small ones.**
*Alternative:* one tool per REST endpoint, with separate coherence, YAML
conversion and triage tools.
*Why:* models choose more accurately among fewer, clearly separated tools.
Validation, coherence checks and YAML normalisation always go together, so
they form one tool. Triage is part of `verify.run.v1`; `verify.minimal.v1`
exists only for machine consumers.

**D7. Deterministic `suggested_next` in tool results.**
*Alternative:* let the model plan the analysis itself.
*Why:* the next analysis step follows from the verifier's own output
(inconclusive → simulate; swept input decisive → ask). Computing it in code
makes the plan reproducible, the same for every provider, and testable. The
model still explains it and asks for consent.

**D8. Run the agent loop ourselves, as an MCP client, behind a provider
adapter.**
*Alternatives:* Anthropic's MCP connector (Anthropic's servers call our MCP
server directly); a full agent framework.
*Why:*
- Our own loop keeps the API key on the server and filters tools by session
  state.
- It injects the session identity, enforces per-turn budgets, asks before
  expensive calls, and streams tool progress to the UI.
- It works with any provider: the connector is Anthropic-only, and
  frameworks add abstraction we don't need.
- The adapter keeps the provider choice an implementation detail that is
  validated by the evaluation suite.

**D9. Default model `claude-opus-5-5`, streaming, prompt caching on a fixed
prefix.**
*Why:*
- Eliciting requirements needs strong judgement about ambiguity and the
  user's intent, so start with the strongest generally available model and
  measure.
- Streaming gives a responsive chat.
- Caching the fixed prefix (tools, method, protocol) makes long interviews
  cheaper.
- Any cheaper model must first match it on the evaluation suite (§3.9).

**D10. Keep Flask for the web app; use FastAPI for the agent service; use the
MCP SDK's Starlette app for MCP.**
*Alternative:* rewrite everything in one framework.
*Why:* the Flask app works and is tested, and rewriting it adds risk with no
benefit. The agent service is I/O-bound and streaming (model calls, MCP
calls, SSE), which async FastAPI handles well. The MCP SDK already ships an
ASGI app. These are three small, well-documented frameworks, each used for
what it does best.

**D11. PostgreSQL as the only database (relational + JSONB + full-text search
+ pgvector).**
*Alternatives:* SQLite; MongoDB; a separate vector database.
*Why:* sessions, versions, jobs and audit logs are relational and need
transactions. Specs and results fit JSONB. Literature search starts with
built-in full-text search and grows into pgvector in the *same* engine. One
database to secure, back up and learn. SQLite doesn't handle concurrent
writers from several containers well.

**D12. Redis + RQ for background jobs.**
*Alternatives:* Celery; running simulations inside the request.
*Why:*
- Simulations exceed request timeouts (gunicorn's limit is 60 s).
- RQ is a small library on Redis with a short learning curve and covers our
  needs: queues, timeouts, results, retries. Celery's extra power (complex
  routing, many brokers) isn't needed here.
- Redis also stores the rate-limit counters, which in-process memory can't
  share across workers.

**D13. Docker Compose on one server, with Caddy at the front.**
*Alternative:* a container orchestrator such as Kubernetes.
*Why:*
- The expected load is research-scale.
- Compose already gives isolation, resource limits, health checks, internal
  networks, secrets and reproducible deployments from one file, and the repo
  already uses it.
- One base file plus small development and production override files keep
  the environments consistent.
- Caddy provides automatic HTTPS with a few lines of configuration.
- An orchestrator would add a large operational surface (cluster, ingress,
  upgrades) with no problem to solve at this scale.

*Kubernetes as an optional alternative.* Compose stays the reference
deployment. Kubernetes becomes the better choice only when at least one of
these is true, and it is worth the cost only then:

| Trigger | Why Compose stops being enough | What Kubernetes provides |
|---|---|---|
| **Availability guarantees.** External partners depend on the MCP endpoint, and downtime during a server failure or maintenance is no longer acceptable. | Compose runs on one machine; if the machine is down, everything is down. Updates restart containers in place. | Replicas spread over several machines, automatic rescheduling when a node fails, rolling updates with no downtime. |
| **Simulation load beyond one machine.** Queued simulation jobs regularly wait minutes because one server's CPUs are saturated. | Compose can run more worker containers, but only on the same machine. | Workers scheduled across a pool of machines and scaled automatically on queue length (KEDA's Redis-list scaler works with RQ's queues). |
| **The institution already runs Kubernetes.** The university or cloud provider offers a managed cluster, and policy requires deploying there. | Running a separate VM is then the extra work. | Monitoring, backups, certificates and security policies are provided by the platform team. |
| **Several environments or teams** (e.g. staging and production, or other groups deploying their own tools beside ours). | Each environment is another server to maintain by hand. | Namespaces, quotas and access control per environment and team on one cluster. |

If none of these applies, Kubernetes only adds cost: a cluster to run and
upgrade, more configuration to learn and secure, and more ways to fail.

*Why the design keeps the alternative open at no cost.* The containers
follow the rules both platforms need:
- one image for all roles (D1);
- stateless services (all state lives in PostgreSQL and Redis);
- configuration through environment variables and secrets;
- health checks on every service;
- non-root, read-only containers;
- jobs in a queue rather than in web requests (D12).

Moving to Kubernetes therefore means writing deployment manifests, not
changing application code. Every Compose concept used here has a direct
equivalent:

| Compose | Kubernetes |
|---|---|
| service (`web`, `agent`, `mcp`, `worker`) | Deployment + Service |
| `healthcheck` | readiness and liveness probes |
| `environment` / `.env` | ConfigMap |
| `secrets:` | Secret (or an external secret manager) |
| `deploy.resources.limits` | resource requests and limits |
| `internal: true` network | NetworkPolicy (default deny) |
| Caddy reverse proxy + automatic TLS | Ingress controller + cert-manager |
| one-shot `migrate` service | Job (run before each rollout) |
| `postgres` / `redis` containers | managed PostgreSQL / Redis services (recommended over running them in the cluster) |
| `docker compose up -d` with a new image tag | `helm upgrade` with a new image tag (rolling update) |

The path is described as optional phase 14 in the implementation guide.

**D14. PDF reports from templates (WeasyPrint), not generated by the LLM.**
*Alternatives:* the LLM writes the whole document; code execution in a
sandbox.
*Why:* a report is a deliverable people rely on. Templates make the structure
and every number deterministic and auditable. The LLM contributes labelled
narrative only, checked against the data (P1). WeasyPrint uses HTML/CSS,
which the project already uses.

**D15. Literature: curated ingestion, short passages, full-text search
first.**
*Why:* a curated, peer-reviewed collection is the point of the feature, so
uploads from end users are out of scope. Short passages respect copyright on
a public endpoint. Starting with full-text search avoids running an
embedding model until the evaluation proves it is needed.

**D16. Machine-readable protocol and policy, delivered to every client
through MCP.**
*Alternative:* a Markdown instructions file in the agent only.
*Why:*
- YAML can be tested for coverage against the schema and the paper, which is
  what the project's rigour requirement asks for.
- Delivering it through MCP resources and prompts means every MCP client
  interviews the same way, not just our chat.
- The behavioural method stays in a short prompt, in the Agent Skills
  format.

---

## 6. Security model

Assets to protect:
- user designs and transcripts (potentially unpublished research and personal
  data);
- the API key and credits;
- service availability;
- the integrity of verdicts and reports.

| Threat | Control |
|---|---|
| Resource exhaustion (pathological specs blowing up Z3, huge simulations) | Request size caps, input bounds in the Pydantic models, a timeout on every handler, simulations only as jobs, per-key quotas and concurrency limits, container CPU/memory/pid limits (already in `infra/compose.yml`). |
| Prompt injection through user text, uploaded YAML, paper passages or tool output | Tool output and passages are marked as data in the conversation. No tool can reach the network or the filesystem beyond its purpose (no fetch-URL tool, so no SSRF). Server-side preconditions make injected "skip verification" instructions ineffective. The narrative-number check stops fabricated figures. |
| XSS through model output in the chat | Markdown → HTML is always sanitised with DOMPurify; strict Content-Security-Policy; no inline event handlers. |
| Credential theft | Secrets only from environment variables or Docker secrets, never in images or git. API keys and access codes stored as hashes. Download links are signed, expire, and also require the owner to be logged in. |
| Unauthorised access across sessions | Every per-user row has an owner. Every per-user query is filtered by the authenticated principal, enforced in one repository layer and covered by tests. The only shared table, `verifications`, is reachable only by content hash (§3.8). |
| DNS rebinding / cross-origin abuse of MCP | MCP `TransportSecuritySettings` with allowed hosts and origins; CORS allowlist. |
| Supply-chain vulnerabilities | Pinned lockfile (`uv.lock`), `pip-audit` and Trivy image scans in CI, Dependabot, a minimal base image, non-root user, read-only filesystem. |
| Unsafe parsing | `yaml.safe_load` only (already the case); no pickle; no `eval`. |
| Data protection (EU / GDPR) | Retention period for transcripts; user deletion endpoint; data processing terms with the LLM provider; no personal data in logs. |

---

## 7. Repository layout (target)

```
policy/
  tool_policy.yaml                 # normative tool rules (this design)
  elicitation_protocol.yaml        # normative interview rules (guide step 7)
te_platform/
  __init__.py  config.py  errors.py  hashing.py  service.py  cli.py  observability.py
  registry/   (context.py, spec.py, policy.py, predicates.py, facts.py, state.py,
               loader.py, pipeline.py, describe.py)
  tools/      (one module per tool id)
  mcp_server/ (app.py, http_app.py, auth.py, resources.py, prompts.py)
  security/   (api_keys.py, quotas.py, signed_urls.py)
  elicitation/ (protocol.py, paths.py, routing.py, answers.py, ranking.py, coverage.py)
  agent/      (app.py, chat_api.py, login_api.py, spec_api.py, user_reports_api.py,
               auth.py, events.py, loop.py, mcp_bridge.py,
               providers/{base,anthropic,fake}.py, prompts/)
  jobs/       (queue.py, tasks.py, report_task.py, worker.py)
  db/         (models.py, session.py, repo.py, alembic.ini.template, migrations/)
  reports/    (render.py, charts.py, numbers_check.py, templates/)
  literature/ (ingest.py, chunking.py, search.py)
deploy/       (caddy/, postgres/)
evals/        (personas/, scenarios/, run.py, simulated_designer.py, metrics.py)
docs/adr/     (decision records)
tests/platform_tests/              # tests of te_platform (snapshots/: reviewed generated text)
schema/  verifier/  webapp/  examples/  tests/   # existing, unchanged
```

The file-by-file map with activation order is `te_platform/README.md`.

`MPC_server/` (the weather quickstart) becomes `te_platform/mcp_server/` and is
then deleted.
