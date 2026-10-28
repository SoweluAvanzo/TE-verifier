/* =============================================================================
   webapp/static/login.js — sends the access code, then returns to ?next=
   =============================================================================
   GUIDE STEP   9.0
   PURPOSE      Handles the form of templates/login.html: POSTs the code as
                JSON to /agent/login (same origin, so the browser stores the
                cookie the agent service sets), then navigates to the page
                the user came from.
   USED BY      templates/login.html.
   DEPENDS ON   POST /agent/login (the agent service, te_platform/agent/login_api.py).
   SECURITY     `next` is only followed if it is a path on THIS site
                ("/..." but not "//..."): otherwise the page could be abused
                to send users to another site after logging in (an "open
                redirect", a classic phishing helper).
   ACTIVATE     Remove the leading "// " from the code lines below.
   ============================================================================= */
/* -----------------------------------------------------------------------------
   TO-DO LIST: build this file yourself, step by step
   -----------------------------------------------------------------------------
   Write your code between this comment and the SOLUTION marker below. Do the
   steps in order and run the "Check" at the end. Lines starting with "|" are
   short illustrations, not the full code. The element ids and the endpoint
   path must be exactly these: templates/login.html and te_platform/agent/
   login_api.py use them.

   Guide 9.0
   [ ] 1. A wrapper that keeps every variable private (an IIFE, like
          verdict.js) with "use strict" as its first line. Everything below
          goes inside it.
   [ ] 2. Two constants: `form` (element "login-form") and `errorBox`
          (element "login-error").
   [ ] 3. `safeNext()`: read `next` from the query string, defaulting to
          "/chat", and follow it only if it is a path on this site (header
          SECURITY):
            | return next.startsWith("/") && !next.startsWith("//")
            |   ? next : "/chat";
   [ ] 4. An async "submit" listener on the form: call
          event.preventDefault(), hide errorBox, read the trimmed value of
          "access-code", then fetch POST "/agent/login" with a JSON
          Content-Type header and the body
            | JSON.stringify({ access_code: code })
          inside try/catch: if fetch itself fails (no answer at all), show
          "Connection problem — please try again." in errorBox and return.
   [ ] 5. If res.ok: window.location.assign(safeNext()) and return.
          Otherwise put a message in errorBox.textContent (status 429:
          "Too many attempts. Please wait 15 minutes."; anything else:
          "That access code was not recognised.") and show errorBox.
   [ ] 6. Check: reload /login (the agent service must be running). A wrong
          code shows the error, the eleventh attempt within 15 minutes shows
          the 429 text, and /login?next=https://evil.example still sends you
          to /chat (guide 9.0 "Done when").

   Stuck, or want to compare? The SOLUTION below is the complete reference
   code. Uncomment it only if you decide to use it as it is.
   -------------------------------------------------------------------------- */
/* =============================================================================
   SOLUTION: complete reference code (commented out on purpose)
   ========================================================================== */

(function () {
  "use strict";
  const form = document.getElementById("login-form");
  const errorBox = document.getElementById("login-error");

  function safeNext() {
    const next = new URLSearchParams(window.location.search).get("next") || "/chat";
    return next.startsWith("/") && !next.startsWith("//") ? next : "/chat";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();               // stay on the page; we send it ourselves
    errorBox.hidden = true;
    const code = document.getElementById("access-code").value.trim();
    let res;
    try {
      res = await fetch("/agent/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access_code: code }),
      });
    } catch (err) {
      // The request never reached the server (network down, service stopped).
      errorBox.textContent = "Connection problem — please try again.";
      errorBox.hidden = false;
      return;
    }
    if (res.ok) {
      window.location.assign(safeNext());
      return;
    }
    errorBox.textContent = res.status === 429
      ? "Too many attempts. Please wait 15 minutes."
      : "That access code was not recognised.";
    errorBox.hidden = false;
  });
})();
