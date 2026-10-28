/*
=============================================================================
webapp/static/chat.js — behaviour of the chat page
=============================================================================
GUIDE STEP   9.1 (conversation + streaming + logout), 9.2 (Markdown,
             rendered safely), 9.3 (open in form), 10.3 (report links)
PURPOSE      - starts (or resumes) a design session with the agent service;
             - sends the user's messages and reads the streamed answer;
             - renders the assistant's Markdown SAFELY;
             - shows tool activity, confirmation questions (Yes/No), spec
               panel updates, verdicts (via the existing verdict.js) and jobs;
             - "Open in form": hands the session's spec to the questionnaire;
             - "Log out": ends the login session (POST /agent/logout);
             - report links: a download link next to each report job.
USED BY      webapp/templates/chat.html.
DEPENDS ON   The agent API (the endpoints in te_platform/agent/chat_api.py,
             spec_api.py, login_api.py and user_reports_api.py, included by
             agent/app.py; same origin under /agent/*), the SSE event names in te_platform/agent/events.py
             (they MUST match the `case` labels below; the 10.3 part reads
             job_progress's `download_url`), marked, DOMPurify (9.2),
             verdict.js (window.renderVerdict).
WHY          Architecture §3.5. Why fetch() and not EventSource: the browser's
             EventSource can only send GET requests, but sending a message is
             a POST with a JSON body. fetch() lets us POST and then read the
             response body piece by piece with a stream reader.
SECURITY     Model output is untrusted (guide §2.2). Until 9.2 it is shown
             as plain text (textContent, which never interprets HTML); from
             9.2 Markdown is converted with marked, then ALWAYS cleaned by
             DOMPurify before it touches innerHTML. Plain text (user
             messages, tool names) is always inserted with textContent.
ACTIVATE     This file uses `// ` line comments for deactivated code and
             block comments like this one for explanations. Code for a LATER
             step is commented twice (`// // `) under a block comment that
             starts with "Guide X.Y" (the same rule as te_platform/README.md
             §1.1): the first toggle leaves it commented; toggle it again at
             that step. At 9.1 uncomment block by block (editor toggle on
             each code block), then reload /chat. At 9.2, 9.3 and 10.3 toggle
             the blocks labelled with that step (9.2 also deletes one 9.1
             line, see the TO-DO LIST).
=============================================================================
*/
/* -----------------------------------------------------------------------------
TO-DO LIST: build this file yourself, step by step
-----------------------------------------------------------------------------
Write your code between this comment and the SOLUTION marker below. Do the
steps in order and run each "Check" before moving on. Lines starting with
"|" are short illustrations, not the full code. Element ids must match
templates/chat.html, and the event names in step 7 must match
te_platform/agent/events.py exactly. The SOLUTION's block comments explain
each part; read them as you go.

Guide 9.1
[ ] 1. The wrapper: an IIFE with "use strict" first (section "Wrapper").
       Everything below goes inside it.
[ ] 2. Elements and state: constants log, form, input, sendBtn for the ids
       "chat-log", "chat-form", "chat-input", "chat-send"; then
         | let sessionId = sessionStorage.getItem("te_chat_session");
         | let busy = false;
[ ] 3. `addLine(cls, text)`: create a div, set className and textContent
       (never innerHTML), append it to log, scroll log to the bottom and
       return the element.
[ ] 4. `async api(path, options = {})`: fetch with a JSON Content-Type
       header, spreading `options` after it. On 401 go to
       "/login?next=" + encodeURIComponent("/chat") and throw; on any other
       non-ok status throw an Error `HTTP <status>` that also carries the
       number in `err.status`; otherwise return the response.
[ ] 5. `async ensureSession()`: return sessionId if set; otherwise POST
       "/agent/sessions" with body "{}", keep the `session_id` of the JSON
       answer and save it in sessionStorage under "te_chat_session".
[ ] 6. `async readEvents(response, onEvent)`: read the body with
       response.body.getReader() and a TextDecoder, append each chunk to a
       text buffer, cut complete events at every blank line ("\n\n"), read
       their "event: " and "data: " lines, and call onEvent(name, data
       parsed as JSON, or {} when there is no data). Keep the incomplete
       tail in the buffer (section "Reading the event stream").
         | buffer += decoder.decode(value, { stream: true });
[ ] 7. `async sendTurn(text, confirmations = {})`: return if busy; set busy
       and disable sendBtn; ensureSession(); add a "msg user" line when
       there is text and an empty "msg assistant" bubble; POST
       {text, confirmations} as JSON to
       `/agent/sessions/${encodeURIComponent(id)}/messages`; then
       readEvents with a switch on the name: text_delta (append ev.text to
       `answer` and show it as plain text: `bubble.textContent = answer`),
       tool_started, tool_finished, confirmation_required, spec_updated,
       verdict_updated, job_progress, error, done (only the reasons
       limit_reached and refusal add a line). Remove the bubble if no text
       arrived. The catch forgets the stored session when err.status is
       404 (it no longer exists or belongs to another login) and says so;
       any other error shows "Connection problem — please try again.";
       finally clears busy and re-enables the button.
[ ] 8. `showConfirmation(ev)`: a div.confirm-box with the question as
       textContent and two buttons; each removes the box and answers in a
       new turn with the approval keyed by the tool use id:
         | sendTurn("", { [ev.tool_use_id]: true });   // false for "No"
[ ] 9. `updatePanel(ev)`: write ev.state into "session-state", rebuild
       "slot-list" with one li per ev.slots entry (slot_id, then a span
       with the classes `badge ${s.status}`).
[ ] 10. `showVerdicts(verdicts)`: replace the children of "verdict-cards"
        with window.renderVerdict(...) for each verdict (verdict.js). The
        tool sends the short id ("FM1") in failure_mode and the full name
        in failure_mode_name: pass the full name as failure_mode, so the
        cards look like the form's.
[ ] 11. `showJob(ev)`: find or create the li with id `job-${ev.job_id}` in
        "job-list"; its text is the first 8 characters of the job id, the
        status, and the progress in percent when it is not null.
[ ] 12. Logout: a "click" listener on "logout-btn" that POSTs
        "/agent/logout" through api() (ignoring a failure: then the user
        is logged out already), removes "te_chat_session" from
        sessionStorage and goes to "/login".
[ ] 13. Wiring, last in the IIFE: a "submit" listener on the form that
        calls preventDefault(), ignores empty (trimmed) text, clears the
        input and calls sendTurn(text). Then a "keydown" listener on the
        input: Enter without Shift (and not e.isComposing) calls
        preventDefault() and form.requestSubmit(); and a "click" listener
        on each button.starter that puts its data-prompt into the input
        and calls form.requestSubmit(). Then close the IIFE.
[ ] 14. Check: with the agent service running and logged in, reload /chat:
        a full conversation works (guide 9.1), and "Log out" brings you to
        /login; going back to /chat and sending a message sends you to
        /login again (the old cookie gives 401).

Guide 9.2 (activate the marked + DOMPurify scripts in chat.html first)
[ ] 15. After addLine, `renderMarkdown(el, markdownText)`: the ONLY place
        that touches innerHTML, and always through DOMPurify (header
        SECURITY):
          | el.innerHTML = DOMPurify.sanitize(marked.parse(markdownText));
[ ] 16. In sendTurn's text_delta case, DELETE the 9.1 line
        `bubble.textContent = answer;` (marked "Guide 9.1 only") and use
        renderMarkdown(bubble, answer) instead.
[ ] 17. Check: send the test message of guide 9.2 (an img tag with
        onerror=alert(1)): it stays harmless; Markdown (lists, bold) is
        rendered.

Guide 9.3
[ ] 18. Between showJob and the logout listener: a "click" listener on
        "open-in-form" that returns if there is no sessionId, GETs
        `/agent/sessions/${encodeURIComponent(sessionId)}/spec`, reads
        `yaml` and `spec_hash` from the JSON. No yaml: show "There is no
        design to open yet." when spec_hash is also empty, else "The design
        is not complete yet: answer the remaining questions first." (an
        incomplete spec is not schema-valid, and the form only loads valid
        ones). Otherwise store yaml in sessionStorage under "te_chat_yaml"
        and navigate to "/".
[ ] 19. Add the small form.js change described in the NOTE of the SOLUTION's
        "Open in form" section (form.js does not read the spec yet).
[ ] 20. Check: click "Open in form", edit and verify in the form; the agent
        sees the edit on its next turn (guide 9.3 "Done when").

Guide 10.3
[ ] 21. In showJob, after setting the text: remember a download_url the
        event carries in li.dataset.downloadUrl (later events for the same
        job may come without it), and when one is known append a link
        "Download report" to it. Accept only links of this site's report
        endpoint (they start with "/agent/reports/").
[ ] 22. Check: ask the assistant for a report; the job list shows the
        report job with a working download link (guide 10.3).

Forms extension (structured questions; te_platform/agent/forms.py, not in the
guide yet)
[ ] 23. In api(), on a 422 keep the JSON `detail` on the error (err.detail):
        it names the refused answer's message and question_id.
[ ] 24. sendTurn(text, confirmations = {}, formAnswers = {}): first close
        the forms NOT answered in this message (closeOpenForms: the server
        treats them as not submitted); send form_answers in the body;
        handle "form_requested" with showForm(ev); on a 422 remove the
        assistant bubble and RETURN the detail (null otherwise), so the
        form can show it.
[ ] 25. showForm(ev): a form.ask-form (noValidate) with the title, the intro
        and one fieldset per question (buildQuestion), then a "Send
        answers" button. Everything through createElement + textContent:
        the form text comes from the model (header SECURITY).
[ ] 26. buildQuestion(q): a fieldset with a legend (the label), the help
        text and the inputs of its kind: radio buttons (single_choice,
        yes_no), checkboxes (multiple_choice), one or two number inputs
        (number, range; the unit after them), a textarea (text); "Other:"
        with a text field when allow_other, "I don't know" when
        allow_unknown (it disables the other inputs). Its read() returns
        {status, value, other?} plus `display` for the summary, or null
        when nothing was filled in.
[ ] 27. submitForm(id): read every question; a required one left empty, or
        an unreadable number, shows its message next to it and focuses it.
        Otherwise lock the form, add a "msg user form-summary" bubble
        (question, then answer) and await sendTurn("", {}, {[id]:
        answers}); when it returns a refusal, remove the summary, unlock,
        and show the message next to the question it names.
[ ] 28. Check: ask the assistant something with fixed options; a form
        appears, the answers come back as your message, and the assistant
        records them (the panel updates).

Conversation history extension (te_platform/agent/transcript.py)
[ ] 29. The open conversation comes from the address (?session=...) first,
        then sessionStorage; setSession(id, push) keeps both in step
        (pushState for a switch, replaceState otherwise). ensureSession uses
        it for a new session.
[ ] 30. loadConversation(id): GET /agent/sessions/{id}; (unless a turn
        started meanwhile) clearConversation(), renderTranscript() of its
        `transcript` items (user_text, assistant_text through
        renderMarkdown, tool lines, form_asked as a compact .ask-asked card
        unless the form is still open, form_answers as a form summary,
        form_skipped), the panel (updatePanel with state and slots,
        showVerdicts), then showForm() for each pending form. A 404 forgets
        the session. Called at start-up when a session is known.
[ ] 31. The sidebar: refreshConversations() (GET /agent/sessions; one
        button.conv-item per conversation with its title and time; a click
        switches with setSession(id, true) + loadConversation), called at
        start-up and after every turn; markCurrent() sets aria-current;
        "New conversation" (newConversation) empties the page and forgets
        the session (the next message creates one); a popstate listener
        follows Back/Forward.
[ ] 32. On an error event with message_discarded: fade the user's bubble
        (.failed), add a .msg-note, and put the text back in the input.
[ ] 33. Check: reload the page: the whole conversation is back; open a
        second tab with "New conversation": both work at once; the sidebar
        switches between them.

Short interview (estimates)
[ ] 34. A question with `estimate` is shown pre-filled (prefill()), with a
        .ask-estimate line "Estimate: <basis>"; changing it removes the
        .is-estimate mark. The summary bubble adds "(estimate kept)" when
        the value sent equals the estimate (the server decides the same,
        agent/forms.py estimate_accepted).
[ ] 34b. The panel's stage follows the session: verdict_updated sets
        "verified", a finished simulation job "simulated" (spec_updated
        carries the derived state for answers).
[ ] 34c. A job line names its kind (job_progress.kind: "Simulation
        (Monte Carlo)", "PDF report") and shows a percentage only while the
        job runs.
[ ] 35. Several forms open at once (a turn may show up to four): only the
        last shows the button, "Send all answers", which checks and sends
        every open form in one message (form_answers holds them all); a
        form sent alone would close the others as skipped.

Stuck, or want to compare? The SOLUTION below is the complete reference
code. Uncomment it only if you decide to use it as it is.
----------------------------------------------------------------------------- */
/* =============================================================================
SOLUTION: complete reference code (commented out on purpose)
============================================================================= */

/* --- Wrapper ------------------------------------------------------------------
An IIFE ("immediately invoked function expression") keeps every variable
private to this file, the same pattern as the existing verdict.js. */
(function () {
  "use strict";

/* --- Elements and state ---------------------------------------------------------
The session id is kept in sessionStorage: it survives a page reload but not
closing the tab. (sessionStorage is per tab and per site.) */
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  // Which conversation is open: the address (?session=..., so a link or a
  // second tab can hold another one) first, then this tab's last one.
  let sessionId = new URLSearchParams(window.location.search).get("session")
    || sessionStorage.getItem("te_chat_session");
  let busy = false;

/* --- Small helpers ------------------------------------------------------------- */
  function addLine(cls, text) {
    const el = document.createElement("div");
    el.className = cls;
    el.textContent = text;            // textContent: never interpreted as HTML
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

/* Guide 9.2: Markdown rendering. marked turns Markdown into HTML; DOMPurify
removes anything that could run code (scripts, event handlers, javascript:
links). Never skip it. */
  // A report link the assistant wrote as bare text (/agent/reports/<id>?exp=…&sig=…)
  // is not a link in Markdown: make it one. Only this site's report endpoint.
  const REPORT_URL = /(^|[\s(:])(\/agent\/reports\/[0-9a-f]{32}\?exp=\d+&sig=[A-Za-z0-9_-]+)(?![^\s)]*\))/g;
  function renderMarkdown(el, markdownText) {
    const linked = markdownText.replace(REPORT_URL, "$1[Open the report (PDF)]($2)");
    el.innerHTML = DOMPurify.sanitize(marked.parse(linked));
    // Report links open in a new tab, so the conversation stays where it is.
    for (const a of el.querySelectorAll('a[href^="/agent/reports/"]')) {
      a.target = "_blank";
      a.rel = "noopener";
    }
  }

  async function api(path, options = {}) {
    // Same origin: the login cookie is sent automatically, and the browser
    // adds the Origin header that the server checks on POST requests.
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    // 401 = not logged in (or the session expired): go to the login page
    // and come back here afterwards (guide 9.0).
    if (res.status === 401) {
      window.location.assign("/login?next=" + encodeURIComponent("/chat"));
      throw new Error("not logged in");
    }
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;          // callers react to 404 (see sendTurn)
      if (res.status === 422) {
        // Forms: the server says which answer does not fit (agent/chat_api.py).
        try { err.detail = (await res.json()).detail; } catch (e) { err.detail = null; }
      }
      throw err;
    }
    return res;
  }

/* --- Session start -------------------------------------------------------------- */
  async function ensureSession() {
    if (sessionId) return sessionId;
    const res = await api("/agent/sessions", { method: "POST", body: "{}" });
    setSession((await res.json()).session_id, false);
    return sessionId;
  }

  // Remember the open conversation in this tab and in the address bar
  // (push: a new history entry, so Back returns to the previous one).
  function setSession(id, push) {
    sessionId = id;
    const url = new URL(window.location.href);
    if (id) {
      sessionStorage.setItem("te_chat_session", id);
      url.searchParams.set("session", id);
    } else {
      sessionStorage.removeItem("te_chat_session");
      url.searchParams.delete("session");
    }
    if (url.href !== window.location.href) {
      window.history[push ? "pushState" : "replaceState"]({ session: id }, "", url);
    }
  }

/* --- Reading the event stream ---------------------------------------------------
The server sends events separated by an empty line:
    event: text_delta
    data: {"type": "text_delta", "text": "Hel"}
    (empty line)
Network chunks do not respect event boundaries, so we keep a buffer, split
it on blank lines, and keep the incomplete tail for the next chunk. */
  async function readEvents(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();      // bytes -> text, handling split UTF-8 characters
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let name = "message", data = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event: ")) name = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        onEvent(name, data ? JSON.parse(data) : {});
      }
    }
  }

/* --- One turn ----------------------------------------------------------------------
Sends text and/or confirmation answers, then handles each event. One
assistant bubble per turn; text deltas are appended and the bubble is
re-rendered (Markdown may only be valid once more text has arrived). */
  async function sendTurn(text, confirmations = {}, formAnswers = {}) {
    if (busy) return null;
    busy = true;
    sendBtn.disabled = true;
    // Forms not answered in this message are skipped (the server tells the
    // assistant so): close them, so they cannot be sent later.
    closeOpenForms(Object.keys(formAnswers));
    let bubble = null;
    try {
      const id = await ensureSession();
      const userBubble = text ? addLine("msg user", text) : null;
      bubble = addLine("msg assistant", "");
      let answer = "";
      const res = await api(`/agent/sessions/${encodeURIComponent(id)}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, confirmations, form_answers: formAnswers }),
      });
      await readEvents(res, (name, ev) => {
        switch (name) {
          case "text_delta":
            answer += ev.text;
/* Guide 9.2: Markdown, rendered safely (replaced the 9.1 plain-text line). */
            renderMarkdown(bubble, answer);
            break;
          case "tool_started":
            addLine("tool-line", `Running ${ev.tool}…`);
            break;
          case "tool_finished":
            // A precondition error is normal (the assistant corrects itself),
            // so it is shown neutrally, not as a red failure.
            addLine(`tool-line ${ev.ok ? "ok" : "err"}`,
                    ev.ok ? `${ev.tool} done` : `${ev.tool}: ${ev.error_code || "not run"}`);
            break;
          case "confirmation_required":
            showConfirmation(ev);
            break;
          case "form_requested":
            showForm(ev);
            break;
          case "spec_updated":
            updatePanel(ev);
            break;
          case "verdict_updated":
            showVerdicts(ev.verdicts);
            // Verdicts exist for the current spec (registry/state.py "verified").
            document.getElementById("session-state").textContent = "verified";
            break;
          case "job_progress":
            showJob(ev);
            if (ev.status === "finished" && (ev.kind === "monte_carlo" || ev.kind === "trajectory")) {
              document.getElementById("session-state").textContent = "simulated";
            }
            break;
          case "error":
            addLine("tool-line err", `${ev.message} (reference ${ev.correlation_id})`);
            if (ev.message_discarded && userBubble) {
              // The server did not keep this message (the turn failed
              // before any answer): fade it and give the text back.
              userBubble.classList.add("failed");
              userBubble.after(make("p", "msg-note", "Not sent. Your message is back in the box below."));
              if (!input.value) input.value = text;
            }
            break;
          case "done":
            if (ev.reason === "limit_reached") addLine("tool-line err", "Stopped: limit for this turn reached.");
            if (ev.reason === "refusal") addLine("tool-line err", "The assistant could not help with that request.");
            break;
        }
      });
      if (!answer) bubble.remove();
      return null;
    } catch (err) {
      if (bubble) bubble.remove();
      if (err.status === 422) {
        // A form answer was refused: the caller (submitForm) shows why.
        const d = err.detail;
        return d && !Array.isArray(d) && d.message ? d : { message: "Check your answers and send them again." };
      }
      if (err.status === 404) {
        // The stored session is gone (database reset) or belongs to
        // another login: forget it, so the next message starts a new one.
        setSession(null, false);
        addLine("tool-line err", "This conversation was not found. Send your message again to start a new one.");
      } else {
        addLine("tool-line err", "Connection problem — please try again.");
      }
      return null;
    } finally {
      busy = false;
      sendBtn.disabled = false;
      refreshConversations();
    }
  }

/* --- Confirmation buttons (expensive tools) ----------------------------------------
The server paused the turn. The answer goes back as `confirmations` in the
next POST; see te_platform/agent/loop.py "HOW CONFIRMATION WORKS". */
  function showConfirmation(ev) {
    const box = document.createElement("div");
    box.className = "confirm-box";
    const q = document.createElement("p");
    q.textContent = ev.question;
    const yes = document.createElement("button");
    yes.textContent = "Yes, run it";
    const no = document.createElement("button");
    no.textContent = "No";
    yes.addEventListener("click", () => { box.remove(); sendTurn("", { [ev.tool_use_id]: true }); });
    no.addEventListener("click", () => { box.remove(); sendTurn("", { [ev.tool_use_id]: false }); });
    box.append(q, yes, no);
    log.appendChild(box);
  }

/* --- Forms (tool ask_user, te_platform/agent/forms.py) ------------------------------
The assistant can ask structured questions: single or multiple choice,
yes/no, number, range (lowest and highest value), open text. The form comes
in a form_requested event and is built here with createElement and
textContent only: its text was written by the model, so it is never parsed
as HTML. The answers go back as form_answers in the next POST; the server
checks every answer against the form IT stored and answers 422 (with the
question's id) when one does not fit. */
  const openForms = new Map();          // tool_use_id -> the form's elements and readers
  let formSeq = 0;                      // makes the inputs' ids unique on the page

  function make(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  // One labelled radio button or checkbox.
  function choiceInput(type, name, value, labelText) {
    const label = make("label", "ask-choice");
    const input = document.createElement("input");
    input.type = type;
    input.name = name;
    input.value = value;
    label.append(input, make("span", "", labelText));
    return { label, input };
  }

  function numberInput(q, aria) {
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.inputMode = "decimal";
    if (q.min !== null && q.min !== undefined) input.min = String(q.min);
    if (q.max !== null && q.max !== undefined) input.max = String(q.max);
    if (q.placeholder) input.placeholder = q.placeholder;
    input.setAttribute("aria-label", aria);
    return input;
  }

  // An "I don't know" checkbox that disables the inputs it stands for.
  function unknownToggle(name, inputs) {
    const { label, input } = choiceInput("checkbox", name, "unknown", "I don't know");
    label.classList.add("ask-unknown");
    input.addEventListener("change", () => {
      for (const i of inputs) i.disabled = input.checked;
    });
    return { label, input };
  }

  // Builds one question; returns its fieldset and read(), which gives
  // {status, value?, other?} for the server, plus `display` for the
  // summary bubble, or null when nothing was filled in.
  function buildQuestion(q) {
    const name = `ask-${++formSeq}`;
    const set = make("fieldset", "ask-question");
    set.dataset.questionId = q.id;
    set.appendChild(make("legend", "", q.label + (q.required ? "" : " (optional)")));
    if (q.help) {
      const help = make("p", "ask-help", q.help);
      help.id = `${name}-help`;
      set.setAttribute("aria-describedby", help.id);
      set.appendChild(help);
    }
    const hasEstimate = q.estimate !== null && q.estimate !== undefined;
    if (hasEstimate) {
      set.classList.add("is-estimate");
      const note = make("p", "ask-estimate");
      note.append(make("strong", "", "Estimate: "), document.createTextNode(q.basis || ""));
      set.appendChild(note);
      // Any change by the designer: no longer the estimate as proposed.
      set.addEventListener("input", () => set.classList.remove("is-estimate"));
      set.addEventListener("change", () => set.classList.remove("is-estimate"));
    }
    const body = make("div", "ask-body");
    set.appendChild(body);
    const unitText = q.unit ? ` ${q.unit}` : "";
    let prefill = () => {};
    let read;

    if (q.kind === "single_choice" || q.kind === "yes_no") {
      const opts = q.kind === "yes_no"
        ? [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]
        : q.options;
      const radios = opts.map((o) => {
        const c = choiceInput("radio", name, o.value, o.label);
        body.appendChild(c.label);
        return { ...c, label_text: o.label };
      });
      let otherText = null;
      if (q.allow_other) {
        const c = choiceInput("radio", name, "__other__", "Other:");
        otherText = make("input", "ask-other");
        otherText.type = "text";
        otherText.maxLength = 500;
        otherText.disabled = true;
        otherText.setAttribute("aria-label", "Other answer");
        c.label.appendChild(otherText);
        body.appendChild(c.label);
        radios.push({ ...c, label_text: "Other" });
      }
      if (q.allow_unknown) {
        const c = choiceInput("radio", name, "__unknown__", "I don't know");
        c.label.classList.add("ask-unknown");
        body.appendChild(c.label);
        radios.push({ ...c, label_text: "I don't know" });
      }
      body.addEventListener("change", () => {
        if (otherText) otherText.disabled = !radios.some((r) => r.input.checked && r.input.value === "__other__");
      });
      prefill = (v) => {
        const want = q.kind === "yes_no" ? (v ? "yes" : "no") : v;
        const r = radios.find((x) => x.input.value === want);
        if (r) r.input.checked = true;
      };
      read = () => {
        const picked = radios.find((r) => r.input.checked);
        if (!picked) return null;
        const v = picked.input.value;
        if (v === "__unknown__") return { status: "unknown", display: "I don't know" };
        if (v === "__other__") {
          const other = otherText.value.trim();
          return other ? { status: "answered", value: null, other, display: `Other: ${other}` } : null;
        }
        if (q.kind === "yes_no") return { status: "answered", value: v === "yes", display: picked.label_text };
        return { status: "answered", value: v, display: picked.label_text };
      };
    } else if (q.kind === "multiple_choice") {
      const boxes = q.options.map((o) => {
        const c = choiceInput("checkbox", name, o.value, o.label);
        body.appendChild(c.label);
        return { ...c, label_text: o.label };
      });
      let otherBox = null, otherText = null;
      if (q.allow_other) {
        const c = choiceInput("checkbox", name, "__other__", "Other:");
        otherBox = c.input;
        otherText = make("input", "ask-other");
        otherText.type = "text";
        otherText.maxLength = 500;
        otherText.disabled = true;
        otherText.setAttribute("aria-label", "Other answer");
        otherBox.addEventListener("change", () => { otherText.disabled = !otherBox.checked; });
        c.label.appendChild(otherText);
        body.appendChild(c.label);
      }
      let unknown = null;
      if (q.allow_unknown) {
        const all = boxes.map((b) => b.input).concat(otherBox ? [otherBox, otherText] : []);
        unknown = unknownToggle(name, all);
        unknown.input.addEventListener("change", () => {
          if (unknown.input.checked) for (const b of all) if (b.type === "checkbox") b.checked = false;
          if (!unknown.input.checked && otherText) otherText.disabled = !otherBox.checked;
        });
        body.appendChild(unknown.label);
      }
      prefill = (v) => {
        for (const b of boxes) b.input.checked = Array.isArray(v) && v.includes(b.input.value);
      };
      read = () => {
        if (unknown && unknown.input.checked) return { status: "unknown", display: "I don't know" };
        const chosen = boxes.filter((b) => b.input.checked);
        const other = otherBox && otherBox.checked ? otherText.value.trim() : "";
        if (!chosen.length && !other) return null;
        const shown = chosen.map((b) => b.label_text).concat(other ? [`Other: ${other}`] : []);
        const out = { status: "answered", value: chosen.map((b) => b.input.value), display: shown.join("; ") };
        if (other) out.other = other;
        return out;
      };
    } else if (q.kind === "number" || q.kind === "range") {
      const row = make("div", "ask-numbers");
      const inputs = q.kind === "number"
        ? [numberInput(q, q.label)]
        : [numberInput(q, "Lowest realistic value"), numberInput(q, "Highest realistic value")];
      if (q.kind === "range") {
        row.append(make("span", "ask-numlabel", "From"), inputs[0], make("span", "ask-numlabel", "to"), inputs[1]);
      } else {
        row.append(inputs[0]);
      }
      if (q.unit) row.appendChild(make("span", "ask-unit", q.unit));
      body.appendChild(row);
      const unknown = q.allow_unknown ? unknownToggle(name, inputs) : null;
      if (unknown) body.appendChild(unknown.label);
      prefill = (v) => {
        if (q.kind === "number") inputs[0].value = String(v);
        else { inputs[0].value = String(v.min); inputs[1].value = String(v.max); }
      };
      read = () => {
        if (unknown && unknown.input.checked) return { status: "unknown", display: "I don't know" };
        if (inputs.every((i) => i.value === "")) return null;
        const nums = inputs.map((i) => (i.value === "" ? NaN : Number(i.value)));
        if (!nums.every(Number.isFinite)) return { error: q.kind === "range" ? "Enter both values as numbers." : "Enter a number." };
        if (q.kind === "number") return { status: "answered", value: nums[0], display: `${nums[0]}${unitText}` };
        if (nums[0] > nums[1]) return { error: "The lowest value is greater than the highest." };
        return { status: "answered", value: { min: nums[0], max: nums[1] }, display: `${nums[0]} to ${nums[1]}${unitText}` };
      };
    } else {
      const area = make("textarea", "ask-text");
      area.rows = 3;
      area.maxLength = 2000;
      if (q.placeholder) area.placeholder = q.placeholder;
      area.setAttribute("aria-label", q.label);
      body.appendChild(area);
      const unknown = q.allow_unknown ? unknownToggle(name, [area]) : null;
      if (unknown) body.appendChild(unknown.label);
      prefill = (v) => { area.value = String(v); };
      read = () => {
        if (unknown && unknown.input.checked) return { status: "unknown", display: "I don't know" };
        const v = area.value.trim();
        return v ? { status: "answered", value: v, display: v } : null;
      };
    }
    if (hasEstimate) prefill(q.estimate);
    const error = make("p", "ask-error");
    error.setAttribute("aria-live", "polite");
    set.appendChild(error);
    return { q, set, read, error };
  }

  // Same answer as the estimate? Numbers compare by value (20 == 20.0).
  function sameValue(a, b) {
    if (typeof a === "number" || typeof b === "number") return Number(a) === Number(b);
    if (Array.isArray(a) && Array.isArray(b)) {
      return a.length === b.length && [...a].sort().every((x, i) => x === [...b].sort()[i]);
    }
    if (a && b && typeof a === "object") return sameValue(a.min, b.min) && sameValue(a.max, b.max);
    return a === b;
  }

  function showForm(ev) {
    const form = ev.form;
    const box = make("form", "ask-form");
    box.noValidate = true;              // we check the answers ourselves (clear messages)
    if (form.title) box.appendChild(make("h3", "", form.title));
    if (form.intro) box.appendChild(make("p", "ask-intro", form.intro));
    const questions = form.questions.map(buildQuestion);
    for (const item of questions) box.appendChild(item.set);
    const footer = make("div", "ask-footer");
    const submit = make("button", "primary-btn", "Send answers");
    submit.type = "submit";
    const general = make("p", "ask-error");
    general.setAttribute("role", "alert");
    footer.append(submit, general);
    box.appendChild(footer);
    box.addEventListener("submit", (e) => {
      e.preventDefault();
      submitForm();
    });
    openForms.set(ev.tool_use_id, { box, questions, submit, general });
    updateSubmitButtons();
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
  }

  // What the user answered, as their own message (question, then answer).
  function formSummary(lines) {
    const summary = make("div", "msg user form-summary");
    for (const [question, shown] of lines) {
      summary.append(make("p", "q", question), make("p", "a", shown));
    }
    log.appendChild(summary);
    log.scrollTop = log.scrollHeight;
    return summary;
  }

  function setLocked(entry, locked) {
    for (const item of entry.questions) item.set.disabled = locked;
    entry.submit.disabled = locked;
  }

  // Read one form; returns {answers, lines} or null when a question needs fixing.
  function readForm(entry) {
    entry.general.textContent = "";
    entry.problems = 0;
    entry.firstBad = null;
    const answers = {};
    const lines = [];
    let firstBad = null;
    for (const item of entry.questions) {
      item.error.textContent = "";
      item.set.removeAttribute("aria-invalid");
      const a = item.read();
      let problem = a && a.error;
      if (!a && item.q.required) {
        problem = item.q.allow_unknown ? "Answer this question, or choose “I don't know”." : "Answer this question.";
      }
      if (problem) {
        item.error.textContent = problem;
        item.set.setAttribute("aria-invalid", "true");
        firstBad = firstBad || item;
        entry.problems = (entry.problems || 0) + 1;
        continue;
      }
      const { display, ...sent } = a || { status: "skipped", display: "(skipped)" };
      answers[item.q.id] = sent;
      const kept = a && a.status === "answered" && item.q.estimate != null && sameValue(a.value, item.q.estimate);
      lines.push([item.q.label, kept ? `${display} (estimate kept)` : display]);
    }
    if (firstBad) {
      entry.firstBad = firstBad;  // submitForm takes the person to the first one of all forms
      return null;
    }
    return { answers, lines };
  }

  // Only the last open form shows the button; with several open forms (one
  // turn may show up to four) it sends them all together, so none is lost.
  function updateSubmitButtons() {
    const entries = [...openForms.values()];
    entries.forEach((entry, n) => {
      const last = n === entries.length - 1;
      entry.submit.hidden = !last;
      entry.submit.textContent = entries.length > 1 ? "Send all answers" : "Send answers";
    });
  }

  async function submitForm() {
    if (busy || !openForms.size) return;
    const entries = [...openForms.entries()];
    const read = entries.map(([, entry]) => readForm(entry));
    if (read.some((r) => r === null)) {
      // Say so next to the button the person clicked, and take them to the
      // first question to fix (the forms can be long: it may be far above).
      const bad = entries.filter(([, e]) => e.firstBad);
      const count = bad.reduce((n, [, e]) => n + e.problems, 0);
      const last = entries[entries.length - 1][1];
      last.general.textContent = count === 1
        ? "One answer needs fixing before sending: see the highlighted question above."
        : `${count} answers need fixing before sending: see the highlighted questions above.`;
      const first = bad[0][1].firstBad;
      first.set.scrollIntoView({ behavior: "smooth", block: "center" });
      const focusable = first.set.querySelector("input:not([disabled]), textarea:not([disabled])");
      if (focusable) focusable.focus({ preventScroll: true });
      return;
    }
    const formAnswers = {};
    entries.forEach(([id], n) => { formAnswers[id] = read[n].answers; });
    for (const [, entry] of entries) setLocked(entry, true);
    const last = entries[entries.length - 1][1];
    last.submit.textContent = "Sending…";
    const summary = formSummary(read.flatMap((r) => r.lines));
    const rejected = await sendTurn("", {}, formAnswers);
    if (rejected) {
      // The server refused an answer: show why, next to that question.
      summary.remove();
      for (const [, entry] of entries) setLocked(entry, false);
      updateSubmitButtons();
      const item = entries.flatMap(([, e]) => e.questions).find((i) => i.q.id === rejected.question_id);
      (item ? item.error : last.general).textContent = rejected.message;
      if (item) item.set.setAttribute("aria-invalid", "true");
      return;
    }
    for (const [id, entry] of entries) {
      entry.box.classList.add("is-answered");
      entry.submit.remove();
      openForms.delete(id);
    }
  }

/* --- Conversations (history, sidebar, new conversation) ---------------------------
GET /agent/sessions/{id} returns the conversation as the person saw it
(`transcript`, te_platform/agent/transcript.py), the panel's content and the
forms still open; GET /agent/sessions lists the user's conversations. */
  const convList = document.getElementById("conv-list");

  // Empty the page: the log, the open forms and the panel.
  function clearConversation() {
    log.replaceChildren();
    openForms.clear();
    document.getElementById("session-state").textContent = "not started";
    document.getElementById("slot-list").replaceChildren();
    document.getElementById("verdict-cards").replaceChildren();
    document.getElementById("job-list").replaceChildren();
  }

  // A form answered earlier, shown compactly: its title and its questions.
  function askedCard(item) {
    const card = make("div", "ask-asked");
    card.appendChild(make("h3", "", item.title || "Questions asked"));
    const list = make("ul");
    for (const q of item.questions) list.appendChild(make("li", "", q));
    card.appendChild(list);
    log.appendChild(card);
  }

  function renderTranscript(items, pendingIds) {
    for (const item of items) {
      if (item.kind === "user_text") addLine("msg user", item.text);
      else if (item.kind === "assistant_text") renderMarkdown(addLine("msg assistant", ""), item.text);
      else if (item.kind === "tool") {
        const state = item.ok === null ? "" : item.ok ? " ok" : " err";
        addLine(`tool-line${state}`, item.ok === false ? `${item.tool}: not run` : item.tool);
      } else if (item.kind === "form_asked" && !pendingIds.has(item.tool_use_id)) askedCard(item);
      else if (item.kind === "form_answers") formSummary(item.answers.map((a) => [a.question, a.display]));
      else if (item.kind === "form_skipped") addLine("tool-line", "Form not answered.");
    }
    log.scrollTop = log.scrollHeight;
  }

  // Open one conversation: its messages, its panel, its open forms.
  async function loadConversation(id) {
    try {
      const res = await api(`/agent/sessions/${encodeURIComponent(id)}`);
      const s = await res.json();
      if (busy) return;                 // a turn started meanwhile: keep what it shows
      clearConversation();
      const pending = s.pending_forms || [];
      renderTranscript(s.transcript || [], new Set(pending.map((f) => f.tool_use_id)));
      updatePanel({ state: s.state, slots: s.slots || [] });
      if ((s.verdicts || []).length) showVerdicts(s.verdicts);
      for (const f of pending) showForm({ tool_use_id: f.tool_use_id, form: f.form });
    } catch (err) {
      if (err.status === 404) {
        // Gone, or not this login's: start with an empty conversation.
        setSession(null, false);
        clearConversation();
      }
    }
    markCurrent();
  }

  function newConversation() {
    if (busy) return;
    setSession(null, true);           // the session is created with the first message
    clearConversation();
    markCurrent();
    input.focus();
  }

  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
  const dayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
  function when(iso) {
    const d = new Date(iso);
    return d.toDateString() === new Date().toDateString() ? timeFormat.format(d) : dayFormat.format(d);
  }

  function markCurrent() {
    for (const b of convList.querySelectorAll(".conv-item")) {
      b.setAttribute("aria-current", String(b.dataset.session === sessionId));
    }
  }

  // The sidebar: one button per conversation, most recent first.
  async function refreshConversations() {
    try {
      const res = await api("/agent/sessions");
      const { conversations } = await res.json();
      convList.replaceChildren(...conversations.map((c) => {
        const li = make("li");
        const b = make("button", "conv-item");
        b.type = "button";
        b.dataset.session = c.session_id;
        b.title = c.title;
        b.append(make("span", "conv-title", c.title), make("span", "conv-time", when(c.updated_at)));
        b.addEventListener("click", () => {
          if (busy || c.session_id === sessionId) return;
          setSession(c.session_id, true);
          loadConversation(c.session_id);
        });
        li.appendChild(b);
        return li;
      }));
      markCurrent();
    } catch (err) {
      // The list is a convenience: the chat keeps working without it.
    }
  }

  // Forms left open when the user sends something else: the server treats
  // them as not submitted, so they are closed here too.
  function closeOpenForms(except) {
    for (const [id, entry] of openForms) {
      if (except.includes(id)) continue;
      setLocked(entry, true);
      entry.box.classList.add("is-skipped");
      entry.submit.remove();
      entry.box.appendChild(make("p", "ask-note", "Not answered: you replied in the chat instead."));
      openForms.delete(id);
    }
  }

/* --- Spec panel ---------------------------------------------------------------------- */
  function updatePanel(ev) {
    document.getElementById("session-state").textContent = ev.state;
    const list = document.getElementById("slot-list");
    list.replaceChildren();
    for (const s of ev.slots || []) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = s.slot_id;
      const badge = document.createElement("span");
      badge.className = `badge ${s.status}`;          // committed | unknown | default | conflict
      badge.textContent = s.status;
      li.append(name, badge);
      list.appendChild(li);
    }
  }

  function showVerdicts(verdicts) {
    // Reuse the existing verdict cards from verdict.js (same look as the
    // form). verify.run.v1 sends the short id ("FM1") in failure_mode and
    // the full name in failure_mode_name; the cards print failure_mode as
    // their title, so they get the full name, as in the form.
    const box = document.getElementById("verdict-cards");
    box.replaceChildren(...verdicts.map((v) =>
      window.renderVerdict({ ...v, failure_mode: v.failure_mode_name || v.failure_mode })));
  }

  function showJob(ev) {
    const list = document.getElementById("job-list");
    let li = document.getElementById(`job-${ev.job_id}`);
    if (!li) {
      li = document.createElement("li");
      li.id = `job-${ev.job_id}`;
      list.appendChild(li);
    }
    // Name the job by what it is; the kind arrives with the first event.
    const names = { monte_carlo: "Simulation (Monte Carlo)", trajectory: "Simulation (one run)", experiment: "Experiment", report: "PDF report" };
    if (ev.kind) li.dataset.kind = names[ev.kind] || ev.kind;
    const running = ev.status === "queued" || ev.status === "running";
    li.textContent = `${li.dataset.kind || ev.job_id.slice(0, 8)}: ${ev.status}` +
                     (running && ev.progress != null ? ` (${Math.round(ev.progress * 100)}%)` : "");
/* Guide 10.3: the download link of a report job. Only links to this site's
report endpoint are accepted, so a manipulated event cannot add a link to
another site. The URL is remembered on the element because later progress
events for the same job (from jobs.status.v1) do not carry it. The link
comes in the job_progress event's `download_url` (te_platform/agent/
events.py), which loop.py fills from the report.render_pdf.v1 result. */
    if (ev.download_url && ev.download_url.startsWith("/agent/reports/")) {
      li.dataset.downloadUrl = ev.download_url;
    }
    if (li.dataset.downloadUrl) {
      const a = document.createElement("a");
      a.href = li.dataset.downloadUrl;
      a.target = "_blank";  // the PDF opens in a new tab
      a.rel = "noopener";
      a.textContent = "Open report (PDF)";
      li.appendChild(a);
    }
  }

/* Guide 9.3: "Open in form". Hands the current spec to the questionnaire through
sessionStorage, the same mechanism form.js already uses to hand a spec to
/explore ("te_form_yaml").
NOTE: form.js does not yet READ a handed-over spec. Activating this step
also needs a small addition to webapp/static/form.js (two places):
  1. at the end of its DOMContentLoaded handler, load a handed-over spec
     like an uploaded YAML file (the upload handler does the same):
       | const chatYaml = sessionStorage.getItem("te_chat_yaml");
       | if (chatYaml) {
       |   sessionStorage.removeItem("te_chat_yaml");
       |   const r = await fetch("/api/yaml-to-ir", { method: "POST",
       |     headers: { "Content-Type": "application/json" },
       |     body: JSON.stringify({ yaml: chatYaml }) });
       |   const data = await r.json();
       |   if (!data.error) hydrateForm(data.ir);
       | }
     (make that handler `async` if it is not);
  2. after a successful verify (where it sets lastVerifiedYaml), post the
     YAML to the chat session, if the form was opened from the chat:
       | const sid = sessionStorage.getItem("te_chat_session");
       | if (sid) await fetch(`/agent/sessions/${encodeURIComponent(sid)}/spec`,
       |   { method: "POST", headers: { "Content-Type": "application/json" },
       |     body: JSON.stringify({ yaml: lastVerifiedYaml }) });
The agent service stores it as a new spec version (author "form",
te_platform/agent/spec_api.py). */
  document.getElementById("open-in-form").addEventListener("click", async () => {
    if (!sessionId) return;
    const res = await api(`/agent/sessions/${encodeURIComponent(sessionId)}/spec`);
    const { yaml, spec_hash: specHash } = await res.json();
    if (!yaml) {
      addLine("tool-line err", specHash
        ? "The design is not complete yet: answer the remaining questions first."
        : "There is no design to open yet.");
      return;
    }
    sessionStorage.setItem("te_chat_yaml", yaml);
    window.location.href = "/";
  });

/* --- Logout -------------------------------------------------------------------------------
POST /agent/logout deletes the session on the server, so a copied cookie
stops working (guide 9.0). A failure means we are logged out already. */
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await api("/agent/logout", { method: "POST", body: "{}" });
    } catch (err) {
      // Already logged out (401 redirects to /login anyway).
    }
    sessionStorage.removeItem("te_chat_session");
    window.location.assign("/login");
  });

/* --- Wiring ---------------------------------------------------------------------------- */
  form.addEventListener("submit", (e) => {
    e.preventDefault();                       // stay on the page; we send with fetch()
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendTurn(text);
  });
  // Enter sends, Shift+Enter starts a new line. isComposing: an input method
  // (e.g. for Japanese) uses Enter to confirm a character, not to send.
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  // The starter prompts of the empty conversation send their text as the
  // first message (chat.css hides them as soon as the log has a message).
  for (const btn of document.querySelectorAll(".starter")) {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.prompt;
      form.requestSubmit();
    });
  }
  document.getElementById("new-chat").addEventListener("click", newConversation);
  // Back / Forward between conversations.
  window.addEventListener("popstate", () => {
    if (busy) return;
    const id = new URLSearchParams(window.location.search).get("session");
    if (id) {
      sessionId = id;
      sessionStorage.setItem("te_chat_session", id);
      loadConversation(id);
    } else {
      sessionId = null;
      sessionStorage.removeItem("te_chat_session");
      clearConversation();
      markCurrent();
    }
  });
  if (sessionId) {
    setSession(sessionId, false);     // puts it in the address bar too
    loadConversation(sessionId);
  }
  refreshConversations();
})();
