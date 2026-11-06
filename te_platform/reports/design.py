## =============================================================================
## te_platform/reports/design.py — the design half of the report
## =============================================================================
## GUIDE STEP   none yet (report-as-design-document extension of phase 10)
## PURPOSE      The report presents and discusses the token economy, not only
##              the verdicts. This file builds, from the session's stored data,
##              everything the template needs for that part:
##                description  the designer's own opening description;
##                inputs       one row per recorded input: what it is, its
##                             value, who gave it (designer / estimate kept /
##                             unknown) and the quote or the estimate's basis;
##                rules        one plain-English line per creation / removal
##                             rule (verifier/shape_summary.py);
##                flow_svg     a diagram of how tokens are created, move and
##                             are removed;
##                evidence     every number the narrative may also use: the
##                             spec, the answers, the designer's messages, the
##                             estimates shown in forms (numbers_check.py).
##              It also turns the verifier's internal counterexample names
##              (HOUR_burn_0__state_t) into readable labels (humanize_name).
## USED BY      jobs/report_task.py (design_context), tools/report_render_pdf.py
##              (design_evidence), reports/render.py (humanize_name, fmt_value).
## DEPENDS ON   agent/forms.py (ASK_USER), elicitation/protocol.py (slot order),
##              schema (TokenEconomy), verifier/shape_summary.py. No I/O.
## WHY          A designer reads the report as the document of their design:
##              it must say what was decided, by whom, and on what basis.
## =============================================================================

import html
import json
import re
import textwrap
from typing import Any

from schema import TokenEconomy

from te_platform.agent.forms import ASK_USER
from te_platform.agent.notes import is_platform_note
from te_platform.elicitation.paths import get_value, has_value
from te_platform.elicitation.protocol import current_protocol
from te_platform.reports.method import steps
from te_platform.reports.plain import is_clock_event, CHECKS, describe, rule_words

## Short names for the inputs table (slot id -> label). Slots not listed
## fall back to their id.
SLOT_LABELS: dict[str, str] = {
    "meta.name": "Name",
    "meta.archetype": "Kind of token economy",
    "tokens.ids": "Tokens",
    "tokens.function": "What the token is used for",
    "tokens.value_anchor": "What gives it value",
    "tokens.earning": "How members earn it",
    "tokens.holding": "Reasons to keep it rather than spend it",
    "tokens.verification": "How contributions are checked",
    "tokens.redemption": "What it can be spent on",
    "events": "Activities that create or remove tokens",
    "tokens.emission": "How tokens are created",
    "tokens.initial_distribution": "Tokens at launch",
    "tokens.burn": "How tokens are removed",
    "tokens.outstanding_cap": "Limit on tokens in circulation",
    "cross_token_flows": "Links between tokens",
    "governance.type": "Who governs",
    "governance.rule_structure": "Who decides what",
    "governance.gamma": "Chance that taking without contributing is noticed",
    "governance.sanction": "What happens to someone caught",
    "governance.gini": "How unequally tokens are held (0 = equal, 1 = one holds all)",
    "participants.N": "Active members",
    "participants.d": "Purchases per member per week",
    "participants.topology": "Who trades with whom",
    "participants.network_degree": "Trading partners per member",
    "tokens.K": "Kinds of things to spend on",
    "participants.Q": "Value traded per week",
    "participants.growth_g": "How membership changes",
    "participants.agent_types": "Kinds of members",
    "meta.nfrs.resilience": "Goal: keep working through quiet times (1-5)",
    "meta.nfrs.adaptability": "Goal: rules easy to change (1-5)",
    "meta.nfrs.accessibility": "Goal: easy to join (1-5)",
    "meta.nfrs.transparency": "Goal: everything visible to members (1-5)",
    "meta.nfrs.proportionality": "Goal: rewards follow effort (1-5)",
    "meta.nfrs.circulation_speed": "Goal: how quickly tokens are spent",
    "meta.nfrs.governance_maturity": "Goal: when members share decisions",
}

SOURCES = {
    "committed": "You",
    "estimated": "Estimate",
    "unknown": "Unknown",
    "default": "Default",
}

DESCRIPTION_MAX = 2500
THOUSANDS = 1000  # from here on, no decimals in tables
VALUE_MAX = 160  # a longer structured value is shown in the rules table instead

## The sections the agent may write (report.render_pdf.v1 `narrative`), in
## the order the report prints them. The report answers "is this design
## sustainable, and why?" through six plain questions (plain.CHECKS), one
## explanation each (check_FM1 ... check_FM6); the design sections present
## the token economy in the designer's terms.
NARRATIVE_SECTIONS: dict[str, str] = {
    "executive_summary": "In brief",
    "design_overview": "The design",
    **{f"check_FM{n}": CHECKS[f"FM{n}"]["name"] for n in range(1, 7)},
    "recommendations": "What to change",
    "limitations": "What this analysis could not check",
    "legal_feasibility": "Legal feasibility",
}
DESIGN_SECTIONS = ("design_overview",)
# The standard report has a fixed length, for its reader and for the models that
# write and then review it: tools/report_render_pdf.py refuses longer text, and
# tools/report_publish.py a longer report.
MAX_PAGES = 12
WORD_LIMITS: dict[str, int] = {
    "executive_summary": 130,
    "design_overview": 130,
    **{f"check_FM{n}": 70 for n in range(1, 7)},
    "recommendations": 220,
    "limitations": 110,
    "legal_feasibility": 170,
}
FIGURE_NOTE_WORDS = 45


def over_word_limit(narrative: dict[str, str], figure_notes: dict[str, str]) -> list[str]:
    """Return a complaint per section or figure note longer than the standard allows."""
    long = [
        f"{key}: {len(text.split())} words, at most {WORD_LIMITS[key]}"
        for key, text in narrative.items()
        if key in WORD_LIMITS and len(text.split()) > WORD_LIMITS[key]
    ]
    long += [
        f"figure {key}: {len(text.split())} words, at most {FIGURE_NOTE_WORDS}"
        for key, text in figure_notes.items()
        if len(text.split()) > FIGURE_NOTE_WORDS
    ]
    return long


CHECK_SECTIONS = tuple(f"check_FM{n}" for n in range(1, 7))
EVALUATION_SECTIONS = CHECK_SECTIONS  # the template's name for the evaluation part


# --- Values ------------------------------------------------------------------


def fmt_number(x: float) -> str:
    """Format a number for a table: thousands separators, 4 significant digits."""
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, int) or float(x).is_integer():
        return f"{int(x):,}"
    return f"{x:,.0f}" if abs(x) >= THOUSANDS else f"{x:.4g}"


def fmt_value(value: Any) -> str:
    """Show an answer or counterexample value in plain words, briefly."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return fmt_number(value)
    if isinstance(value, dict) and set(value) >= {"min", "max"}:
        lo, hi = value["min"], value["max"]
        return fmt_number(lo) if lo == hi else f"{fmt_number(lo)} to {fmt_number(hi)}"
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        return ", ".join(str(v).replace("_", " ") for v in value)
    if isinstance(value, str):
        return value.replace("_", " ")
    if value is None:
        return "—"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= VALUE_MAX else "see the rules below"


# --- Counterexample names --------------------------------------------------------

_RULE = r"(?P<tok>[A-Za-z0-9_]+?)_(?P<kind>emit|burn)_(?P<i>\d+)"
_PRETTY_RULE = r"tokens\[(?P<tok>[^\]]+)\]\.(?P<kind>emission|burn)_rules\[(?P<i>\d+)\]"
_KIND = {"emit": "creation", "emission": "creation", "burn": "removal"}
_PARAM = {"unspec": "amount per period (shape not specified)", "c": "constant amount"}


def _rule(m: re.Match[str]) -> str:
    return f"{m['tok']}, {_KIND[m['kind']]} rule {int(m['i']) + 1}"


def humanize_name(name: str) -> str:
    """Turn a verifier variable name into a label a designer can read."""
    patterns: list[tuple[str, Any]] = [
        (
            _PRETTY_RULE + r"\.function\.(?P<p>\w+)$",
            lambda m: f"{_rule(m)}: {_PARAM.get(m['p'], 'coefficient ' + m['p'])}",
        ),
        (
            _PRETTY_RULE + r"\.trigger\.event_frequency\.\w+$",
            lambda m: f"{_rule(m)}: how often its activity happens per period",
        ),
        (_RULE + r"__state_t$", lambda m: f"{_rule(m)}: period at which it is evaluated"),
        (_RULE + r"__event_(?P<f>\w+)$", lambda m: f"{_rule(m)}: activity's {m['f']}"),
        (_RULE + r"__expr_free$", lambda m: f"{_rule(m)}: amount per period (any value)"),
        (_RULE + r"_fndist\w*$", lambda m: f"{_rule(m)}: random amount"),
        (_RULE + r"_freq\w*$", lambda m: f"{_rule(m)}: how often its activity happens"),
        (
            _RULE + r"_fn__(?P<p>\w+)$",
            lambda m: f"{_rule(m)}: {_PARAM.get(m['p'], 'coefficient ' + m['p'])}",
        ),
        (r"param__(?P<p>\w+)$", lambda m: f"parameter “{m['p'].replace('_', ' ')}”"),
        (
            r"(?P<tok>[^.\s]+)\.Q \(transaction volume\)$",
            lambda m: f"{m['tok']}: value traded per period",
        ),
        (
            r"(?P<tok>[^.\s]+)\.outstanding_supply_cap$",
            lambda m: f"{m['tok']}: cap on tokens outstanding",
        ),
        (r"(?P<tok>[^.\s]+)\.E_total.*$", lambda m: f"{m['tok']}: tokens created per period"),
        (r"(?P<tok>[^.\s]+)\.B_total.*$", lambda m: f"{m['tok']}: tokens removed per period"),
        (
            r"agent_types\[(?P<a>[^\]]+)\]\.expected_holding_time \(token (?P<tok>[^)]+)\)$",
            lambda m: f"{m['a'].replace('_', ' ')}: periods they keep {m['tok']}",
        ),
    ]
    for pattern, label in patterns:
        m = re.match(pattern, name)
        if m:
            return str(label(m))
    return name.replace("__", " ").replace("_", " ")


## An experiment's change, in words: "tokens[HOUR].burn_rules[0].function.
## asymptotic_class.parameter_ranges.c" -> "HOUR, removal rule 1: amount (c)".
_IR_LABELS = {
    "participants.count_N": "Active members",
    "participants.average_demand_d": "Purchases per member per week",
    "participants.expected_Q": "Value traded per week",
    "governance.monitoring_capacity_gamma": "Chance that taking without contributing is noticed",
    "governance.token_balance_gini": "How unequally tokens are held",
    "governance.rule_structure": "Who decides what",
    "governance.sanction_structure": "What happens to someone caught",
    "governance.type": "Who governs",
}
## Design paths an experiment can change -> the slot whose words describe them.
_PATH_SLOTS = {
    "governance.rule_structure": "governance.rule_structure",
    "governance.sanction_structure": "governance.sanction",
    "participants.growth_g": "participants.growth_g",
    "participants.agent_types": "participants.agent_types",
}
_TOKEN_FIELDS = {
    "offer_variety_K": "kinds of things to spend on",
    "outstanding_supply_cap": "limit on tokens in circulation",
    "emission_rules": "how tokens are created",
    "burn_rules": "how tokens are removed",
    "initial_distribution": "tokens at launch",
}


def change_words(path: str, value: Any, spec: dict[str, Any]) -> str:
    """Describe an experiment's change ("what changes") in words."""
    m = re.match(r"tokens\[(?P<tok>[^\]]+)\]\.(?P<field>emission_rules|burn_rules)$", path)
    slot = _PATH_SLOTS.get(path) or (
        f"tokens.{'emission' if m['field'] == 'emission_rules' else 'burn'}" if m else ""
    )
    words = describe(slot, value, spec, m["tok"] if m else None) if slot else fmt_value(value)
    return f"{path_label(path)}: {words}"


def path_label(path: str) -> str:
    """Describe a design field path in words (the path itself is printed next to it)."""
    if path in _IR_LABELS:
        return _IR_LABELS[path]
    m = re.match(r"events\[(?P<event>[^\]]+)\]\.(?P<what>payload|frequency)\b", path)
    if m:
        event = m["event"].replace("_", " ")
        return f"{'tokens per' if m['what'] == 'payload' else 'how often:'} {event}"
    m = re.match(
        r"tokens\[(?P<tok>[^\]]+)\]\.(?P<kind>emission|burn)_rules\[(?P<i>\d+)\]\.(?P<rest>.+)$",
        path,
    )
    if m:
        rest = m["rest"]
        what = (
            f"amount ({rest.rsplit('.', 1)[-1]})"
            if "parameter_ranges" in rest
            else rest.replace("_", " ").replace(".", " ")
        )
        return f"{m['tok']}, {_KIND[m['kind']]} rule {int(m['i']) + 1}: {what}"
    m = re.match(r"tokens\[(?P<tok>[^\]]+)\]\.(?P<field>\w+)$", path)
    if m:
        return f"{m['tok']}: {_TOKEN_FIELDS.get(m['field'], m['field'].replace('_', ' '))}"
    return path.replace("_", " ")


# --- Session data -> design context ------------------------------------------------


def _blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    content = (row.get("content") or {}).get("content", [])
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)]


def _user_texts(messages: list[dict[str, Any]]) -> list[str]:
    return [
        b["text"]
        for r in messages
        if r.get("role") == "user"
        for b in _blocks(r)
        if b.get("type") == "text"
        and str(b.get("text", "")).strip()
        and not is_platform_note(str(b["text"]))
    ]


def _form_questions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        q
        for r in messages
        if r.get("role") == "assistant"
        for b in _blocks(r)
        if b.get("type") == "tool_use" and b.get("name") == ASK_USER
        for q in (b.get("input") or {}).get("questions", [])
        if isinstance(q, dict)
    ]


def _token_id(spec: dict[str, Any], indices: list[int]) -> str | None:
    tokens = spec.get("tokens") or []
    if indices and 0 <= indices[0] < len(tokens):
        return str(tokens[indices[0]].get("id", ""))
    return None


_ABSENT = object()
MAX_VALUE_CHARS = 110  # the whole rule is in the rules table of section 1


def _decoded_value(value: Any) -> Any:
    """Return a value some models stored as JSON text ('{"min": 1, "max": 2}') as data."""
    if isinstance(value, str) and value.lstrip()[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _value_in_design(spec: dict[str, Any], answer: dict[str, Any]) -> Any:
    """Return what the design holds for an answer's slot, or _ABSENT if it holds nothing."""
    slot = current_protocol().slot(answer["slot_id"])
    if slot is None or slot.answer_type == "list":
        return _decoded_value(answer["value"])  # a list slot spans all elements: the answer is the row
    indices = tuple(answer["indices"])
    try:
        return (
            get_value(spec, slot.ir_path, indices)
            if has_value(spec, slot.ir_path, indices)
            else _ABSENT
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return answer["value"]


def _inputs(
    spec: dict[str, Any], answers: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """One row per recorded input, in protocol order."""
    order = {slot.id: n for n, (_, slot) in enumerate(current_protocol().ordered_slots())}
    basis = {str(q.get("id")): str(q["basis"]) for q in _form_questions(messages) if q.get("basis")}
    rows = []
    for a in sorted(answers, key=lambda a: (order.get(a["slot_id"], 999), a["indices"])):
        label = SLOT_LABELS.get(a["slot_id"], a["slot_id"])
        token = _token_id(spec, a["indices"]) if a["slot_id"].startswith("tokens.") else None
        if token and a["slot_id"] != "tokens.ids":
            label = f"{label} ({token})"
        in_design = _value_in_design(spec, a)
        recorded = describe(a["slot_id"], _decoded_value(a["value"]), spec, token)
        value = recorded if in_design is _ABSENT else describe(a["slot_id"], in_design, spec, token)
        quote = str(a.get("user_quote") or "")
        if a["status"] == "estimated":
            note = basis.get(a["slot_id"], "")
        else:
            note = quote if quote and quote != value else ""
        # The table states what was checked; a different recorded answer is said, not hidden.
        if in_design is _ABSENT and a["status"] in ("committed", "estimated"):
            note = f"{note} Not part of the design that was checked.".strip()
        elif value != recorded and a["status"] in ("committed", "estimated"):
            note = f"{note} First recorded as {recorded}.".strip()
        rows.append(
            {
                "label": label,
                "value": value if len(value) <= MAX_VALUE_CHARS else f"{value[:MAX_VALUE_CHARS].rstrip()}…",
                "source": SOURCES.get(a["status"], a["status"]),
                "status": a["status"],
                "note": note,
            }
        )
    return rows


def _rules(spec: dict[str, Any]) -> list[dict[str, str]]:
    """Every creation and removal rule as a plain sentence (plain.rule_words)."""
    events = {str(e.get("id")): e for e in spec.get("events") or [] if isinstance(e, dict)}
    out = []
    for tok in spec.get("tokens") or []:
        for kind, key in (("Created", "emission_rules"), ("Removed", "burn_rules")):
            for rule in tok.get(key) or []:
                event_id = (rule.get("trigger") or {}).get("event_id")
                ev = events.get(event_id or "")
                out.append(
                    {
                        "token": tok.get("id", ""),
                        "kind": kind,
                        "when": (
                            ev.get("label", event_id)
                            if ev and not is_clock_event(ev)
                            else "every week, by the clock"
                        ),
                        "summary": rule_words(rule, events, tok.get("id", "tokens")),
                    }
                )
    return out


def design_context(
    spec: dict[str, Any] | None,
    answers: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the design part of the report from a session's stored data."""
    texts = _user_texts(messages)
    description = texts[0] if texts else ""
    if len(description) > DESCRIPTION_MAX:
        description = description[: DESCRIPTION_MAX - 1].rstrip() + "…"
    te = None
    if spec:
        try:
            te = TokenEconomy.model_validate(spec)
        except ValueError:
            te = None  # an incomplete spec: the table still shows the answers
    return {
        "description": description,
        "inputs": _inputs(spec or {}, answers, messages),
        "rules": _rules(spec) if te and spec else [],
        "flow_svg": flow_svg(te, spec or {}) if te else None,
        "evidence": design_evidence(spec, answers, messages),
        "steps": steps(messages, answers),
        "spec": spec or {},
    }


def design_evidence(
    spec: dict[str, Any] | None,
    answers: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Everything the narrative may take numbers from besides the results.

    The designer's own figures (their messages, their answers, the spec
    built from them) and the estimates shown to them in forms are facts of
    the design, so the narrative may quote them.
    """
    return {
        "spec": spec or {},
        "answers": [{"value": a["value"], "quote": a.get("user_quote")} for a in answers],
        "designer": _user_texts(messages),
        "estimates": [
            {"estimate": q.get("estimate"), "basis": q.get("basis")}
            for q in _form_questions(messages)
        ],
    }


# --- Flow diagram ------------------------------------------------------------------

_W, _BOX_W, _LINE = 640, 200, 13
# Inline attributes, not CSS classes: the SVG is drawn on its own by the PDF
# renderer. Creation green, removal red, the token blue, flows grey.
_FILL = {"src": "#e3f1e6", "sink": "#f7e4e1", "token": "#dfe9f6", "flow": "#eeeeee"}
_STROKE = {"src": "#2f7d45", "sink": "#a8463a", "token": "#2d5c9a", "flow": "#777777"}


def _lines(text: str, width: int = 34, most: int = 4) -> list[str]:
    lines = textwrap.wrap(text, width) or [""]
    if len(lines) > most:
        lines = [*lines[: most - 1], lines[most - 1][: width - 1] + "…"]
    return lines


def _rule_lines(rule: dict[str, str]) -> list[str]:
    # Only the activity: the rules table under the diagram gives the amounts.
    return _lines(rule["when"], most=3)


def _box(x: float, y: float, w: float, lines: list[str], cls: str) -> tuple[str, float]:
    h = 10 + _LINE * len(lines)
    parts = [
        (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" '
            f'fill="{_FILL[cls]}" stroke="{_STROKE[cls]}"/>'
        )
    ]
    for n, line in enumerate(lines):
        parts.append(
            f'<text x="{x + 8}" y="{y + 17 + n * _LINE}" font-size="10" '
            f'font-family="sans-serif" fill="#222">{html.escape(line)}</text>'
        )
    return "".join(parts), h


def _arrow(x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" '
        'stroke-width="1.2" marker-end="url(#arrow)"/>'
    )


def flow_svg(te: TokenEconomy, spec: dict[str, Any]) -> str:
    """Draw, per token: creation rules -> token -> removal rules, then cross-token flows."""
    rules = _rules(spec)
    parts: list[str] = []
    y = 10.0
    for token in te.tokens:
        created = [r for r in rules if r["token"] == token.id and r["kind"] == "Created"]
        removed = [r for r in rules if r["token"] == token.id and r["kind"] == "Removed"]
        left: list[tuple[str, float, float]] = []
        right: list[tuple[str, float, float]] = []
        ly = ry = y
        for r in created or [{"when": "no creation rule", "summary": ""}]:
            svg, h = _box(0, ly, _BOX_W, _rule_lines(r), "src")
            left.append((svg, ly, h))
            ly += h + 8
        for r in removed or [{"when": "no removal rule", "summary": ""}]:
            svg, h = _box(_W - _BOX_W, ry, _BOX_W, _rule_lines(r), "sink")
            right.append((svg, ry, h))
            ry += h + 8
        bottom = max(ly, ry)
        mid = (y + bottom - 8) / 2
        token_svg, th = _box(_W / 2 - 70, mid - 16, 140, [f"{token.id} in circulation"], "token")
        parts.append(token_svg)
        for svg, by, h in left:
            parts.append(svg + _arrow(_BOX_W, by + h / 2, _W / 2 - 72, mid - 16 + th / 2))
        for svg, by, h in right:
            parts.append(svg + _arrow(_W / 2 + 70, mid - 16 + th / 2, _W - _BOX_W - 2, by + h / 2))
        y = bottom + 18
    for f in te.cross_token_flows:
        text = (
            f"When {f.source_event.replace('_', ' ')} happens in {f.source_token}: "
            f"{f.target_action.value} {f.target_token}"
        )
        svg, h = _box(_W / 2 - 160, y, 320, _lines(text, 48, 2), "flow")
        parts.append(svg)
        y += h + 8
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {y}" '
        f'width="{_W}" height="{y}">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#555"/></marker></defs>'
    )
    return head + "".join(parts) + "</svg>"
