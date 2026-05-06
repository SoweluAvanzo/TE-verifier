# Webapp prototype

A Flask app that walks the user through the verifier's workflow with
two complementary modes:

- **`/` Form-driven questionnaire (default).** A guided
  walk-through covering the Roadmap docx Groups 1–5 and NFRs.
  Each section has structured controls (dropdowns, multi-selects,
  numeric ranges) and a "why we ask" expander pulling explanatory
  copy from `verifier/paper.py`. The verdict pane stays visible on
  the right after the first Verify, so the user can iteratively
  tweak a field and re-verify without losing context. **Multi-token
  systems with multiple mint/burn mechanisms per token and inter-token
  flows** are supported directly in the form; switch to the YAML
  editor only for regime switches and rare asymptotic families.
- **`/yaml` Advanced YAML editor.** For users who want full IR
  control — multi-token systems, regime switches, rare asymptotic
  families. Loads the same explanatory FM cards above the editor.

## Run

```bash
# from the repo root
pip install -e ".[webapp]"
python -m webapp.app
```

Open <http://127.0.0.1:5000> for the form, or <http://127.0.0.1:5000/yaml>
for the advanced editor.

## Form workflow (the testing-friendly default)

1. **Pick an example** at the top to pre-populate every field with
   a known case study (Bitcoin, Ethereum, MakerDAO, Curve, Axie).
   The app auto-verifies, so you immediately see a worked verdict.
2. **Tweak** any field — change a sanction kind, lower γ, swap
   `verification` to a weaker mechanism. Click **Verify** again.
   The right pane updates with the new critical values and
   mechanism mappings.
3. **Save your design.** Click **Download YAML** to grab the
   serialized TE-IR for sharing or version control.
4. **Reuse.** Click **Upload YAML…** to reload a previously
   downloaded spec.

The form is designed so a user can build a complete TE-IR in 10–20
minutes without touching YAML. For multi-token systems or
regime switches, switch to the YAML editor.

## Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Form-driven questionnaire UI. |
| `/yaml` | GET | Advanced YAML-editor UI. |
| `/api/example/<name>` | GET | Returns the YAML text of a case-study example. |
| `/api/yaml-to-ir` | POST | Validates YAML and returns a JSON IR for form hydration. |
| `/api/verify` | POST | YAML body → Report JSON (used by `/yaml`). |
| `/api/build-and-verify` | POST | JSON IR body → Report JSON + serialized YAML (used by `/`). |
| `/api/conditions` | GET | Paper-canonical FM explanations as JSON. |

## Structure

```
webapp/
  app.py                   # Flask routes + JSON endpoints
  templates/
    form.html              # Form-driven questionnaire UI (default at /)
    index.html             # Advanced YAML-editor UI (at /yaml)
  static/
    style.css              # Shared styling (FM cards, verdict cards)
    form.css               # Form-specific styling (two-column layout, ranges)
    verdict.js             # Shared verdict rendering (used by both UIs)
    form.js                # Form orchestration: build IR, verify, hydrate, agent rows
    app.js                 # YAML-editor orchestration
```

## What this prototype demonstrates

- The full pipeline from a structured form through the verifier to a
  rendered verdict report.
- "Why we ask" copy pulled from `verifier/paper.py` next to every
  question — the user understands what each failure mode is and
  why each elicitation question matters.
- Concrete recommendations with mechanism mappings — for FM4, the
  user sees γ\* and which `contribution_verification` choices satisfy
  it (color-coded safe / partially safe / unsafe).
- Coherence-issue surfacing — top-level alerts when the IR is
  internally inconsistent.
- Sensitivity marking — every verdict shows which fields were
  swept (range search) vs committed (point value), so the user
  knows which side of a counterexample to address.
- **Tight feedback loop for testing.** Load → tweak → re-verify
  is the central interaction. The verdict pane stays visible
  alongside the form so the user never loses context.

## What this prototype does not yet do

- **Live coherence validation.** Coherence issues currently surface
  on submit. A future iteration would run them client-side as the
  user types.
- **Conditional rule UI.** Structured predicates
  (`ThresholdCondition` / `TimeWindow` / `EventOccurrence`) are not
  yet exposed in the form. See `docs/redesign-plan.md` Phase B2/B3.
- **Config override loading.** The CLI `--config` flag is not yet
  exposed in the webapp.
- **Authentication / multi-user state.** Single-session, in-memory,
  suitable for local exploration only.

## Source documents the webapp consumes

The webapp does not duplicate documentation; it renders these
canonical sources:

- `verifier/paper.py` — every "why we ask" / "why it matters" /
  "real-world signal" / "design knobs" surface.
- `verifier/elicitation.py` — coherence rules and derivation tables
  used to validate IRs.
- The verifier's `Report` JSON — every verdict's status, critical
  values, recommendations, mechanism mappings, swept fields,
  coherence issues.
- `docs/api-contract.md` — the JSON shape contract.
- `docs/recommendation-shapes.md` — the per-FM rendering guide.
- `docs/error-states.md` — how to surface INCONCLUSIVE preconditions.
- `docs/elicitation-mapping.md` — the questionnaire → IR contract that
  drives the form's section structure.

When the source paper or any verifier behaviour changes, the webapp
inherits the change automatically because it reads from these
sources at request time.
