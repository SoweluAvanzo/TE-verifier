## =============================================================================
## te_platform/reports/plain.py — the report's words for people outside the field
## =============================================================================
## GUIDE STEP   none yet (report-as-design-document extension of phase 10)
## PURPOSE      The report is read by designers who know their community, not
##              the paper's six failure modes, its symbols or the verifier's
##              vocabulary. This file holds the plain words the main part of
##              the report uses, all derived from the verifier's own data:
##                CHECKS       each failure mode as a plain name and question;
##                result words for verdicts (worst case), risk bands (typical
##                case) and triage;
##                describe()   a design value in words, never JSON;
##                jargon()     the specialist terms an agent text still uses,
##                             with the plain word to use instead (the report
##                             tool refuses such text, as it refuses invented
##                             numbers).
##              The technical names, formulas and codes stay available in the
##              report's technical appendix.
## USED BY      reports/design.py, reports/method.py, reports/render.py,
##              tools/report_render_pdf.py.
## =============================================================================

import re
from typing import Any

## The six checks (verifier/paper.py ALL_CONDITIONS), in plain words. The
## question is what the check asks of THIS design; "why" says what goes wrong
## in real life when the answer is no.
CHECKS: dict[str, dict[str, str]] = {
    "FM1": {
        "name": "Too many tokens for the activity",
        "question": "Could more tokens be created than members' activity can absorb?",
        "why": "If tokens pile up faster than they are used, each one buys less and "
        "members lose trust in them.",
    },
    "FM2": {
        "name": "Tokens passed on too fast",
        "question": "Do members keep tokens long enough for them to hold their value?",
        "why": "If everyone gets rid of tokens at once, they work only as short-lived "
        "receipts and any surplus is felt immediately.",
    },
    "FM3": {
        "name": "More tokens created than removed",
        "question": "Are tokens removed (spent and cancelled, expired, charged as fees) at "
        "least as fast as they are created?",
        "why": "If creation keeps outrunning removal, the number of tokens grows without limit.",
    },
    "FM4": {
        "name": "Taking without contributing",
        "question": "Are there enough contributors for what members want to get, and is "
        "taking without contributing likely to be noticed and sanctioned?",
        "why": "If contributing does not pay, or taking without giving goes unnoticed, "
        "contributors drop out and the system empties.",
    },
    "FM5": {
        "name": "Too few members for trades to happen",
        "question": "Are there enough members for people to find what they need often enough?",
        "why": "With too few members for the variety of things on offer, trades rarely "
        "match and people stop using the token.",
    },
    "FM6": {
        "name": "Control in too few hands",
        "question": "Can one person or a small group change the rules on their own?",
        "why": "If a few people control the rules or most of the tokens, they can steer "
        "the system for themselves, and problems are not corrected.",
    },
}


def check_name(failure_mode: str) -> str:
    """Plain name of a check, from its id or full verifier name ("FM3: Burn / ...")."""
    return CHECKS.get(str(failure_mode)[:3], {}).get("name", str(failure_mode))


## Worst case = the formal verdict over every value in the ranges.
VERDICT_WORDS = {
    "pass": "Holds in every case",
    "pass_as_intended": "Accepted by design",
    "fail": "Can fail",
    "inconclusive": "Not decided",
    "not_applicable": "Does not apply",
}
## Typical case = the risk band at the middle of the ranges.
BAND_WORDS = {
    "green": "Fine",
    "green_borderline": "Fine, near the limit",
    "amber": "Under strain",
    "red": "Failing",
    "red_critical": "Failing badly",
    "not_applicable": "—",
}
## Triage = whether a failing check can be fixed by adjusting numbers.
TRIAGE_WORDS = {
    "sound": "holds with room to spare",
    "fragile": "fixable by adjusting the numbers",
    "broken": "needs a change to the design itself",
    "inconclusive": "could not be determined",
    "not_applicable": "",
}


# --- Values in words -----------------------------------------------------------------

_ENUM_WORDS = {
    "medium_of_exchange": "paying for things",
    "unit_of_account": "measuring value",
    "governance_right": "voting on decisions",
    "access_right": "access to a service",
    "store_of_value": "saving",
    "reputation_marker": "showing reputation",
    "resource_contribution": "contributing work or resources",
    "behavioral_reward": "rewards for activities",
    "airdrop": "free distribution",
    "exchange_purchase": "buying them",
    "algorithmic_issuance": "created automatically by the rules",
    "specific_goods_or_services": "specific goods or services",
    "time_based_borrowing": "borrowing for a time",
    "fungible_access": "general access",
    "open_market_exchange": "selling on an open market",
    "peer_to_peer_transfer": "passing them to other members",
    "physical_presence": "checked in person",
    "peer_verification": "confirmed by other members",
    "smart_contract_automation": "checked automatically by software",
    "self_reporting": "reported by the members themselves",
    "third_party_certification": "certified by an outside party",
    "community_reward": "community reward for contribution",
    "native_protocol_asset": "the native coin of a blockchain",
    "stablecoin": "a token tied to a currency",
    "governance_utility_pair": "a governance token paired with a usage token",
    "play_to_earn_dual": "a game economy",
    "centralized": "one person or organisation decides",
    "committee": "an elected group decides",
    "dao": "members vote",
    "algorithmic": "fixed software rules decide",
    "hybrid": "a mix of these",
    "single_entity": "one person or organisation",
    "committee_trusted": "a trusted small group",
    "token_holder_vote": "a members' vote",
    "smart_contract": "automatic rules",
    "not_adjustable": "nobody (fixed)",
    "well_mixed": "anyone trades with anyone",
    "spatial": "mostly with people nearby",
    "network": "through a network of contacts",
    "circulate_fast": "spent quickly",
    "balanced": "balanced",
    "retain_value": "kept as savings",
    "immediate": "from the start",
    "short_term": "within the first year",
    "medium_term": "in a few years",
    "indefinite": "never (founders keep control)",
    "none": "none",
}

_SANCTIONS = {
    "none": "no sanction",
    "warning": "a warning",
    "token_penalty": "a token penalty",
    "exclusion": "exclusion",
    "graduated": "escalating steps: warning, penalty, then exclusion",
    "economic": "losing a deposit or stake",
}


def _num(x: Any) -> str:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return f"{int(x):,}" if float(x).is_integer() else f"{x:,.4g}"
    return str(x)


def range_words(r: Any) -> str:
    """{"min": 2, "max": 7} -> "2 to 7"; a point -> "2"."""
    if isinstance(r, dict) and {"min", "max"} <= r.keys():
        lo, hi = r["min"], r["max"]
        return _num(lo) if lo == hi else f"{_num(lo)} to {_num(hi)}"
    return _num(r)


def amount_words(ac: dict[str, Any] | None) -> str:
    """Describe a per-occurrence amount or a frequency (an asymptotic class) in words."""
    if not ac:
        return "an unspecified amount"
    fam = ac.get("family")
    p = ac.get("parameter_ranges") or {}
    if fam == "constant" and "c" in p:
        return range_words(p["c"])
    if fam == "linear":
        a = p.get("a")
        base = range_words(p["b"]) if "b" in p else "0"
        if a is None or (a.get("min", 0) == 0 and a.get("max", 0) == 0):
            return base
        return f"{base}, changing by {range_words(a)} per week"
    if fam == "unspecified":
        return "an amount not yet known"
    return f"an amount that changes over time ({str(fam).replace('_', ' ')})"


def rule_words(rule: dict[str, Any], events: dict[str, dict[str, Any]], token: str) -> str:
    """One creation or removal rule as a sentence."""
    fn = rule.get("function") or {}
    amount = (
        "an amount given by a formula"
        if fn.get("expression")
        else amount_words(fn.get("asymptotic_class"))
    )
    event_id = (rule.get("trigger") or {}).get("event_id")
    ev = events.get(event_id or "")
    if ev is None:
        return f"{amount} {token} per week"
    freq = amount_words(ev.get("frequency")) if ev.get("frequency") else "an unknown number of"
    return f"{amount} {token} each time: {ev.get('label', event_id)} ({freq} times a week)"


def _rules_words(value: Any, events: dict[str, Any], tok: str) -> str:
    if not value:
        return "none"
    return "; ".join(rule_words(r, events, tok) for r in value if isinstance(r, dict))


def _events_words(value: Any, _events: dict[str, Any], _tok: str) -> str:
    return (
        "; ".join(
            f"{e.get('label', e.get('id'))} ({amount_words(e.get('frequency'))} times a week)"
            for e in value
            if isinstance(e, dict)
        )
        or "none"
    )


def _launch_words(value: Any, _events: dict[str, Any], tok: str) -> str:
    if value.get("kind") in (None, "none"):
        return "none at launch"
    amount = range_words(value["amount"]) if value.get("amount") else "an amount"
    return f"{amount} {tok} at launch ({str(value['kind']).replace('_', ' ')})"


def _sanction_words(value: Any, _events: dict[str, Any], _tok: str) -> str:
    return _SANCTIONS.get(value.get("kind", ""), str(value.get("kind")))


def _growth_words(value: Any, _events: dict[str, Any], _tok: str) -> str:
    if value.get("family") == "constant":
        return "stable"
    p = value.get("parameter_ranges") or {}
    if "value" in p:
        return f"changes by {range_words(p['value'])} per week (as a share)"
    return amount_words(value)


def _deciders_words(value: Any, _events: dict[str, Any], _tok: str) -> str:
    by_actor: dict[str, list[str]] = {}
    for decision, actor in value.items():
        who = _ENUM_WORDS.get(str(actor), str(actor))
        by_actor.setdefault(who, []).append(str(decision).replace("_", " "))
    return "; ".join(f"{who}: {', '.join(ds)}" for who, ds in by_actor.items())


def _members_words(value: Any, _events: dict[str, Any], _tok: str) -> str:
    parts = []
    for a in value:
        if isinstance(a, dict):
            weeks = range_words((a.get("expected_holding_time") or {}).get("expected_periods"))
            name = str(a.get("id", "")).replace("_", " ")
            parts.append(f"{round(a.get('fraction', 0) * 100)}% {name} (keep tokens {weeks} weeks)")
    return "; ".join(parts)


## Structured answers, by slot: (expected Python type, describer).
_DESCRIBERS: dict[str, tuple[type, Any]] = {
    "tokens.emission": (list, _rules_words),
    "tokens.burn": (list, _rules_words),
    "events": (list, _events_words),
    "tokens.initial_distribution": (dict, _launch_words),
    "governance.sanction": (dict, _sanction_words),
    "participants.growth_g": (dict, _growth_words),
    "governance.rule_structure": (dict, _deciders_words),
    "participants.agent_types": (list, _members_words),
}


def _simple_words(value: Any) -> str:
    if isinstance(value, dict) and {"min", "max"} <= value.keys():
        return range_words(value)
    if isinstance(value, list):
        return ", ".join(_ENUM_WORDS.get(str(v), str(v).replace("_", " ")) for v in value)
    if isinstance(value, str):
        return _ENUM_WORDS.get(value, value.replace("_", " "))
    if isinstance(value, (int, float)):
        return _num(value)
    return "see the design description"


def describe(slot_id: str, value: Any, spec: dict[str, Any], token: str | None = None) -> str:
    """Describe a recorded answer in words, for the specification table (never JSON)."""
    if value is None:
        return "not set"
    events = {e.get("id"): e for e in spec.get("events") or [] if isinstance(e, dict)}
    kind, words = _DESCRIBERS.get(slot_id, (type(None), None))
    if words is not None and isinstance(value, kind):
        return str(words(value, events, token or "tokens"))
    return _simple_words(value)


# --- Jargon guard ----------------------------------------------------------------------

## Specialist terms the main text must not use, with the plain word to use. The
## failure-mode codes and Greek symbols are caught by pattern.
JARGON: dict[str, str] = {
    "triage": "say whether adjusting the numbers would fix it",
    "fragile": "fixable by adjusting the numbers",
    "counterexample": "the case where it fails",
    "monte carlo": "simulation",
    "agent-based": "simulation of individual members",
    "emission": "creation of tokens",
    "minting": "creation of tokens",
    "burn": "removal of tokens",
    "velocity": "how fast tokens change hands",
    "gini": "how unequal balances are",
    "centralization index": "share of decisions one person or group controls",
    "fisher": "(omit)",
    "asymptotic": "(omit)",
    "well-mixed": "if anyone could trade with anyone",
    "parameter box": "the ranges you gave",
    "verifier": "the checks",
    "solver": "the mathematical check",
    "risk band": "typical case",
}
_CODES = re.compile(r"\bFM ?[1-6]\b")
_GREEK = re.compile(r"[ΓγρτφΣΔδλμσεκ]|τ̄")


def jargon(text: str) -> list[str]:
    """Return the specialist terms in `text` (empty when it reads plainly)."""
    found = []
    if _CODES.search(text):
        found.append("failure-mode codes (FM1-FM6): use the check's plain name")
    if _GREEK.search(text):
        found.append("Greek symbols: say what the quantity is in words")
    low = text.lower()
    for term, plain in JARGON.items():
        if re.search(r"\b" + re.escape(term) + r"(s|ed|ing)?\b", low):
            found.append(f"“{term}”: write {plain}")
    return found


# --- The assessment: is the design sustainable, and why ----------------------------------

## The four things a sustainable design needs (paper §3.7), each with the
## questions that test it. All four must hold.
AREAS: list[tuple[str, str, list[str]]] = [
    (
        "Is the number of tokens under control?",
        (
            "Tokens must be created no faster than they are used and removed, and be held long "
            "enough to keep their value."
        ),
        ["FM1", "FM3", "FM2"],
    ),
    (
        "Do members contribute fairly?",
        (
            "There must be enough contributors for what members want, and taking without giving "
            "must be noticed and sanctioned."
        ),
        ["FM4"],
    ),
    (
        "Are there enough members?",
        "There must be enough members for people to find what they need.",
        ["FM5"],
    ),
    (
        "Who controls the rules?",
        "No single person or small group should be able to change the rules alone.",
        ["FM6"],
    ),
]

_OK = {"pass", "pass_as_intended", "not_applicable"}


def _sim_words(r: dict[str, Any]) -> str:
    n = r.get("n_runs") or 0
    k = r.get("n_violations")
    if k is None:
        k = round(float(r.get("p_violation", 0)) * n)
    return f"appeared in {k} of {n} simulated runs"


def assessment(verification: dict[str, Any], simulation: dict[str, Any] | None) -> dict[str, Any]:
    """Return the overall answer and, per area and question, the results in plain words."""
    by_fm: dict[str, list[dict[str, Any]]] = {}
    for v in verification.get("verdicts", []):
        by_fm.setdefault(str(v.get("failure_mode", ""))[:3], []).append(v)
    sims = {
        (str(r.get("failure_mode", ""))[:3], r.get("subject")): r
        for r in (simulation or {}).get("per_fm_results") or []
        if r.get("simulated")
    }
    areas = []
    failing, undecided = [], []
    for title, need, fms in AREAS:
        questions = []
        for fm in fms:
            rows = []
            for v in by_fm.get(fm, []):
                status = str(v.get("status"))
                sim = sims.get((fm, v.get("subject")))
                rows.append(
                    {
                        "subject": "" if v.get("subject") == "system" else str(v.get("subject")),
                        "status": status,
                        "worst": VERDICT_WORDS.get(status, status),
                        "typical": BAND_WORDS.get(str(v.get("risk_level")), ""),
                        "fixable": TRIAGE_WORDS.get(str(v.get("structural_status") or ""), "")
                        if status == "fail"
                        else "",
                        "simulation": _sim_words(sim) if sim else "",
                    }
                )
                if status == "fail":
                    failing.append(fm)
                elif status not in _OK:
                    undecided.append(fm)
            questions.append({"id": fm, **CHECKS[fm], "rows": rows})
        areas.append({"title": title, "need": need, "questions": questions})
    n_fail, n_open = len(set(failing)), len(set(undecided))
    if n_fail:
        overall = f"Not yet sustainable: {n_fail} of the six questions can fail" + (
            f", and {n_open} could not be decided." if n_open else "."
        )
    elif n_open:
        overall = f"Not proven sustainable: no question fails, but {n_open} could not be decided."
    else:
        overall = "Sustainable on all six questions, for every value within your ranges."
    return {"overall": overall, "areas": areas, "failing": sorted(set(failing))}
