## =============================================================================
## te_platform/reports/method.py — how the design was studied, in the report
## =============================================================================
## GUIDE STEP   none yet (report-as-design-document extension of phase 10)
## PURPOSE      The parts of the report that explain the methods, built from
##              data and fixed text only (no model writes them), so they are
##              correct by construction:
##                glossary(texts)      the technical terms the report uses,
##                                     each defined in plain words;
##                models(verification) per failure mode: what it means, the
##                                     paper's condition, the condition this
##                                     verification checked, its symbols;
##                steps(...)           the audit trail: what was done, in
##                                     order, read from the conversation and
##                                     the job records;
##                figures(...)         every chart with an id, a title and a
##                                     caption saying exactly what it plots
##                                     and where the data come from; the
##                                     agent adds its interpretation per id
##                                     (figure_notes, number-checked).
## USED BY      reports/render.py, tools/report_render_pdf.py (figure ids).
## DEPENDS ON   verifier/paper.py (the paper's conditions and symbols: the
##              single source the verifier also uses), reports/charts.py.
## =============================================================================

import json
import re
from typing import Any

from verifier.paper import ALL_CONDITIONS

from te_platform.agent.mcp_bridge import from_provider_name
from te_platform.agent.notes import is_platform_note
from te_platform.reports import charts

# --- Glossary ---------------------------------------------------------------------
## Term -> plain definition. A term is listed in the report only if the
## report's text uses it (glossary()). Definitions follow the verifier's
## actual semantics (verifier/minimal.py, verifier/risk.py, verifier/abm/).
GLOSSARY: dict[str, str] = {
    "token": "A digital unit of value recorded by the system, which members earn, hold and spend.",
    "supply": "The number of tokens held by participants at a given time (written M); "
    "also called tokens in circulation or outstanding.",
    "emission": "Creating new tokens and adding them to circulation (also called "
    "minting); E is the number created per period.",
    "burn": "Removing tokens from circulation for good, for example when they are "
    "spent and destroyed, expire or are charged as a fee; B is the number removed per "
    "period.",
    "period": "The time step of the models; one period corresponds to about one week.",
    "velocity": "How many times, on average, a token changes hands per period; the "
    "shorter tokens are held, the higher it is.",
    "holding time": "How long a member keeps a token before spending it, in periods.",
    "failure mode": "One of six known ways in which token economies fail, defined in "
    "the paper the verifier implements (Domenicale, Avanzo and Schifanella, DLT 2026).",
    "formal verification": "A mathematical check that a condition holds for every "
    "combination of input values within their declared ranges, done by a solver "
    "rather than by trying examples.",
    "solver": "The program (Z3, an SMT solver) that performs the formal verification "
    "by searching for any input values that break a condition; if none exist, the "
    "condition is proven for the whole range.",
    "counterexample": "A concrete set of input values, found by the solver, under "
    "which a condition fails.",
    "range": "A lowest and highest value given for an uncertain input; the checks "
    "cover every value in between.",
    "triage": "A second formal check that classifies each failure mode: sound (it "
    "cannot occur anywhere in the ranges), fragile (it occurs for some values and not "
    "for others), broken (no value in the ranges avoids it).",
    "risk band": "A rating (green, amber, red) of how severe a condition is at the "
    "middle of the input ranges, complementary to the verdict, which covers the whole "
    "range.",
    "Monte Carlo": "A simulation repeated many times with input values drawn at "
    "random within their ranges, to estimate how often a failure occurs.",
    "agent-based": "A simulation of individual members (agents) who earn, spend, hold "
    "and pass on tokens according to the behaviour of their group.",
    "confidence interval": "A range that contains the true probability with 95% "
    "confidence, given the number of simulated runs (Wilson interval).",
    "trajectory": "The values of a quantity over time in one simulated run.",
    "seed": "A number that fixes the random draws of a simulation, so that it can be "
    "repeated exactly.",
    "sensitivity": "How much a result changes when one input changes.",
    "Gini": "A measure of inequality from 0 (everyone holds the same) to 1 (one "
    "member holds everything).",
    "centralization index": "The share of governance decisions that one actor or a "
    "trusted small group can take alone (written Γ).",
    "critical mass": "The minimum number of active members needed for exchanges to "
    "find a match often enough.",
    "free rider": "A member who takes from the system without contributing in return.",
    "mutual credit": "A system in which members pay by going into debt to the "
    "network, within a credit limit, and repay by selling to other members.",
    "credit limit": "The most a member may owe the network at any time.",
    "outstanding supply cap": "A limit, enforced by the rules, on the tokens in "
    "circulation at any one time (for example the members' credit limits added up).",
    "smart contract": "A program on a blockchain that applies the rules of the token "
    "automatically.",
    "blockchain": "A shared, tamper-evident ledger maintained by many computers.",
    "DAO": "A decentralised autonomous organisation: a group governed by rules and "
    "votes recorded on a blockchain.",
    "stablecoin": "A token designed to keep a stable value against a currency or asset.",
    "crypto-asset": "A digital representation of value or rights that can be "
    "transferred and stored electronically using a blockchain or similar technology "
    "(the definition used by the EU MiCA regulation).",
    "e-money": "Electronic money: monetary value stored electronically, issued on "
    "receipt of funds and accepted for payments by others than the issuer.",
    "MiCA": "The EU Markets in Crypto-Assets Regulation (Regulation (EU) 2023/1114).",
}


## Plain terms for the main part of the report (the GLOSSARY above, with
## the paper's and the methods' vocabulary, is the technical appendix's).
PLAIN_TERMS: dict[str, str] = {
    "token": "A digital unit of value recorded by the system, which members earn, hold and spend.",
    "tokens in circulation": "All the tokens members hold at a given moment.",
    "week": "The time step of the analysis; every rate is per week.",
    "range": "A lowest and highest value given for something uncertain; the checks "
    "cover every value in between.",
    "estimate": "A value the assistant proposed from your description and you kept.",
    "worst case": "The least favourable combination of values within your ranges; a "
    "question that holds in the worst case holds in every case.",
    "typical case": "The middle of every range: how the design behaves under ordinary conditions.",
    "simulation": "A computer re-enactment of the community, member by member, week by "
    "week, repeated many times with values drawn at random within your ranges, to see "
    "how often a problem appears.",
    "variant": "A copy of the design with a few values changed, checked in the same way "
    "to test an idea.",
}


def plain_terms(texts: list[str]) -> list[tuple[str, str]]:
    """Return (term, definition) for every plain term the texts use."""
    joined = " ".join(texts).lower()
    return [
        (term, text)
        for term, text in PLAIN_TERMS.items()
        if re.search(r"\b" + re.escape(term.lower()) + r"s?\b", joined)
    ]


def glossary(texts: list[str]) -> list[tuple[str, str]]:
    """Return (term, definition) for every glossary term the texts use."""
    joined = " ".join(texts).lower()
    return [
        (term, text)
        for term, text in GLOSSARY.items()
        if re.search(r"\b" + re.escape(term.lower()) + r"s?\b", joined)
    ]


# --- Models ------------------------------------------------------------------------


def _readable(condition: str) -> str:
    """Replace a reference to the verifier's configuration by plain words."""
    return re.sub(
        r"\s*\(where [^)]*config\.[^)]*\)",
        " (the threshold is a setting of the verifier; the value used is in the condition "
        "checked below)",
        condition,
    )


def models(verification: dict[str, Any]) -> list[dict[str, Any]]:
    """Per failure mode: meaning, the paper's condition, what this run checked, symbols."""
    checked: dict[str, list[str]] = {}
    for v in verification.get("verdicts", []):
        fm = str(v.get("failure_mode", ""))[:3]
        cond = str(v.get("formal_condition") or "")
        status = str(v.get("status", "")).replace("_", " ")
        line = f"{v.get('subject')} ({status}): {cond}"
        if cond and line not in checked.setdefault(fm, []):
            checked[fm].append(line)
    out = []
    for fm, c in ALL_CONDITIONS.items():
        out.append(
            {
                "id": fm,
                "name": c.name,
                "statement": c.plain_statement,
                "why": c.why_it_matters,
                "paper_condition": _readable(c.sustainability_ascii),
                "violation": c.violation_ascii,
                "section": c.paper_section,
                "checked": checked.get(fm, []),
                "symbols": [
                    {
                        "symbol": v.symbol,
                        "name": v.name,
                        "description": v.description,
                        "units": v.units,
                    }
                    for v in c.variables
                ],
            }
        )
    return out


# --- Steps (audit trail) -----------------------------------------------------------

_STEP_TEXT = {
    "elicit.next_questions.v1": None,  # bookkeeping: not a step of the study
    "elicit.record_answer.v1": None,
    "spec.validate.v1": None,
    "jobs.status.v1": None,
    "jobs.cancel.v1": None,
    "verify.run.v1": "Mathematical check of the six questions (worst and typical case)",
    "verify.minimal.v1": "Check of whether adjusting the numbers would fix what fails",
    "graph.flow.v1": "Diagram of how tokens flow",
    "export.cadcad.v1": "Export for an external simulation tool",
    "report.render_pdf.v1": None,
}


def _describe(tool: str, args: dict[str, Any]) -> str | None:
    if tool in _STEP_TEXT:
        return _STEP_TEXT[tool]
    if tool == "lit.search.v1":
        return f"Search of the research and legal literature: “{args.get('query', '')}”"
    if tool == "sim.monte_carlo.v1":
        return (
            f"Simulation of the community: {args.get('n_runs', 200)} runs of "
            f"{args.get('horizon', 260)} weeks (random seed {args.get('seed', 'not fixed')})"
        )
    if tool == "sim.trajectory.v1":
        return (
            f"One simulated run followed week by week: {args.get('horizon', 120)} weeks "
            f"(random seed {args.get('seed', 42)})"
        )
    if tool == "sim.experiment.v1":
        return f"Test of an idea: {args.get('title', '')}"
    return None


def _blocks(row: dict[str, Any]) -> list[Any]:
    content = (row.get("content") or {}).get("content", [])
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


def _result(block: dict[str, Any]) -> dict[str, Any] | None:
    """Return a successful tool_result's result (None: declined, refused or not JSON)."""
    if block.get("is_error"):
        return None
    try:
        envelope = json.loads(block.get("content") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        return None
    result = envelope.get("result")
    return result if isinstance(result, dict) else {}


def _completed_calls(messages: list[dict[str, Any]]) -> set[str]:
    """Ids of the tool calls that produced a result.

    A call counts only if its tool_result succeeded (not declined by the
    designer, not refused by the platform) and, for a call that started a
    job, if a later jobs.status result shows that job finished. Job ids
    repeat when the same job is submitted again, so a finished status
    completes only the latest call that started that job.
    """
    names: dict[str, str] = {}  # tool_use id -> tool name
    pending: dict[str, str] = {}  # job id -> tool_use id of the latest start
    done: set[str] = set()
    for r in messages:
        for b in _blocks(r):
            if not isinstance(b, dict):
                continue
            if r.get("role") == "assistant" and b.get("type") == "tool_use":
                names[str(b.get("id"))] = from_provider_name(str(b.get("name", "")))
                continue
            if r.get("role") != "user" or b.get("type") != "tool_result":
                continue
            call = str(b.get("tool_use_id"))
            result = _result(b)
            if result is None:
                continue
            job_id = result.get("job_id")
            if names.get(call) == "jobs.status.v1":
                if job_id and result.get("status") == "finished" and str(job_id) in pending:
                    done.add(pending.pop(str(job_id)))
                done.add(call)
            elif job_id:
                pending[str(job_id)] = call
            else:
                done.add(call)
    return done


def steps(messages: list[dict[str, Any]], answers: list[dict[str, Any]]) -> dict[str, Any]:
    """List what was done, in order, from the stored conversation and answers.

    Only calls that produced a result are steps: a declined, refused or
    failed call did not happen as far as the study is concerned.
    """
    completed = _completed_calls(messages)
    user_turns = 0
    done: list[str] = []
    for r in messages:
        for b in _blocks(r):
            if not isinstance(b, dict):
                continue
            text = b.get("text", "")
            if (
                r.get("role") == "user"
                and b.get("type") == "text"
                and text.strip()
                and not is_platform_note(text)
            ):
                user_turns += 1
            if (
                r.get("role") == "assistant"
                and b.get("type") == "tool_use"
                and str(b.get("id")) in completed
            ):
                args = b.get("input")
                tool = from_provider_name(str(b.get("name", "")))
                text = _describe(tool, args if isinstance(args, dict) else {})
                if text and (not done or done[-1] != text):
                    done.append(text)
    form_answers = sum(
        1
        for r in messages
        if r.get("role") == "user"
        for b in ((r.get("content") or {}).get("content") or [])
        if isinstance(b, dict)
        and b.get("type") == "tool_result"
        and '"form": "submitted"' in str(b.get("content", ""))
    )
    counts = {"committed": 0, "estimated": 0, "unknown": 0, "default": 0}
    for a in answers:
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    return {"user_turns": user_turns, "forms": form_answers, "answers": counts, "steps": done}


# --- Figures ------------------------------------------------------------------------


def _has_monte_carlo(experiment: dict[str, Any]) -> bool:
    return any(v.get("monte_carlo") for v in experiment.get("variants", []))


def _token_ids(experiment: dict[str, Any]) -> list[str]:
    first = (experiment.get("variants") or [{}])[0]
    return list((first.get("trajectories") or {}).keys())[:3]


def figure_ids(
    design: dict[str, Any] | None,
    simulation: dict[str, Any] | None,
    experiments: list[dict[str, Any]],
) -> list[str]:
    """Return the ids of every chart the report will contain (the agent notes each one)."""
    ids = []
    if design and design.get("flow_svg"):
        ids.append("flow")
    if any(r.get("simulated") for r in (simulation or {}).get("per_fm_results") or []):
        ids.append("simulation")
    for n, exp in enumerate(experiments, start=1):
        ids += [f"experiment{n}-supply-{tok}" for tok in _token_ids(exp)]
        if _has_monte_carlo(exp):
            ids.append(f"experiment{n}-violations")
    return ids


def _sim_caption(simulation: dict[str, Any]) -> str:
    cfg = simulation.get("config") or {}
    return (
        f"The community was simulated {cfg.get('n_runs', '?')} times, each time over "
        f"{cfg.get('horizon_periods', '?')} weeks and with values drawn at random within "
        f"your ranges (random seed {cfg.get('seed')}, so the runs can be repeated exactly). "
        f"Each bar is the share of those runs in which the problem appeared: the darker "
        f"part already at launch, the lighter part later on. Questions the mathematical "
        f"check had already settled for every case are not simulated."
    )


def figures(
    design: dict[str, Any] | None,
    simulation: dict[str, Any] | None,
    experiments: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Map each chart id to {title, caption, svg}, in the order of figure_ids()."""
    out: dict[str, dict[str, str]] = {}
    for fid in figure_ids(design, simulation, experiments):
        if fid == "flow":
            out[fid] = {
                "title": "How tokens are created, held and removed",
                "caption": "Each green box is an activity that creates tokens, each red box "
                "an activity that removes them; the arrows show which way tokens flow. "
                "Drawn from the rules of the design; the table below gives the amounts.",
                "svg": (design or {})["flow_svg"],
            }
        elif fid == "simulation":
            sim = simulation or {}
            out[fid] = {
                "title": "How often each problem appeared in the simulation",
                "caption": _sim_caption(sim),
                "svg": charts.violation_probability_svg(sim.get("per_fm_results") or []),
            }
    for n, exp in enumerate(experiments, start=1):
        job = str(exp.get("job_id", ""))[:16]
        d = exp.get("design") or {}
        for tok in _token_ids(exp):
            out[f"experiment{n}-supply-{tok}"] = {
                "title": f"Test {n}: {tok} in circulation, week by week",
                "caption": f"The number of {tok} in circulation over {d.get('horizon')} weeks "
                "for each variant, in the typical case (every value at the middle of its "
                "range, no randomness): each week adds the tokens created and subtracts "
                "those removed, and the total never goes below zero. A flat line at zero "
                f"means tokens are removed as fast as they are created. Source: test {job}.",
                "svg": charts.experiment_supply_svg(exp, tok),
            }
        if _has_monte_carlo(exp):
            out[f"experiment{n}-violations"] = {
                "title": f"Test {n}: how often each problem appeared, per variant",
                "caption": f"For each variant, the share of {d.get('monte_carlo_runs')} "
                f"simulated runs (random seed {d.get('seed')}) in which each problem "
                "appeared. A missing bar means the mathematical check had already settled "
                f"that question for the variant, so it was not simulated. Source: test {job}.",
                "svg": charts.experiment_violation_svg(exp),
            }
    return out
