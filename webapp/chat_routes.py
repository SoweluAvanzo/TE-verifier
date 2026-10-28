## =============================================================================
## webapp/chat_routes.py — serves the chat and login PAGES from the Flask web app
## =============================================================================
## GUIDE STEP   9.0 (GET /login), 9.1 (GET /chat), 9.2 (their
##              Content-Security-Policy header)
## PURPOSE      A Flask *Blueprint* (a bundle of routes that can be attached to
##              an app) with two routes: GET /login renders
##              templates/login.html and GET /chat renders templates/chat.html.
##              That is all Flask does for the chat. Everything else — login
##              itself, sending messages, streaming answers, report downloads —
##              is served by the FastAPI agent service at /agent/*
##              (te_platform/agent/chat_api.py, spec_api.py and login_api.py,
##              included by agent/app.py).
##
##              Both are reached through the same address: Caddy routes
##              /, /chat (and the rest) to Flask and /agent/* to FastAPI
##              (architecture §2). For the browser it is ONE site (one
##              "origin"), so chat.js can call /agent/... without CORS, and the
##              login cookie works for both services.
## USED BY      webapp/app.py (registers the blueprint, see ACTIVATE),
##              Caddy (routes /login and /chat here).
## DEPENDS ON   flask; templates/chat.html and login.html; static/chat.js,
##              chat.css, login.js.
## WHY          Architecture §3.5 and D10: keep the working Flask app, add the
##              chat page to it; put async streaming in FastAPI where it fits.
##              A blueprint keeps chat code out of the already-long app.py.
## ACTIVATE     Guide 9.0: uncomment the code below EXCEPT the block labelled
##              "Guide 9.1" (it stays commented once, see te_platform/README.md
##              §1.1), then register the blueprint in webapp/app.py with two
##              lines:
##                at the top, with the other imports:
##                    from webapp.chat_routes import chat_bp
##                right after `app = Flask(...)`:
##                    app.register_blueprint(chat_bp)
##              Check: GET /login returns 200 and loads its JS/CSS.
##              Guide 9.1: uncomment the "Guide 9.1" block; GET /chat returns
##              200 and loads its JS/CSS. The pages hold no data, so they need
##              no login themselves: every API call they make is checked by
##              the agent service (cookie session, te_platform/agent/auth.py),
##              and chat.js sends the user to /login when it gets a 401.
##              Guide 9.2: uncomment the two "Guide 9.2" blocks (the Response
##              import and the header hook). Test:
##              tests/platform_tests/test_platform_security.py (its 9.2 test).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the names exactly as
## written here: webapp/app.py imports `chat_bp` (see ACTIVATE step 2).
##
## Guide 9.0
## [ ] 1. Top import: `Blueprint` and `render_template` from flask.
## [ ] 2. Create the blueprint at module level (the SOLUTION's "##" lines
##        explain both arguments):
##          | chat_bp = Blueprint("chat", __name__)
## [ ] 3. `login_page() -> str`, decorated with `@chat_bp.get("/login")`,
##        with a one-line docstring: it only returns
##        render_template("login.html"). Flask never sees the access code;
##        the agent service checks it (POST /agent/login).
## [ ] 4. Register the blueprint in webapp/app.py: the import at the top
##        and `app.register_blueprint(chat_bp)` right after
##        `app = Flask(...)` (header ACTIVATE).
## [ ] 5. Check: activate templates/login.html, static/login.js and the
##        Guide 9.0 block of static/chat.css, start the web app
##        (`uv run python -m webapp.app`) and open /login: it answers 200
##        and loads its CSS and login.js.
##
## Guide 9.1
## [ ] 6. `chat_page() -> str`, decorated with `@chat_bp.get("/chat")`:
##        returns render_template("chat.html"). Add a short docstring: no
##        data is embedded, the page asks the agent service after loading.
## [ ] 7. Check: activate the Guide 9.1 parts of templates/chat.html,
##        static/chat.js and static/chat.css, then open /chat: it answers
##        200 and loads its JS/CSS (header ACTIVATE).
##
## Guide 9.2
## [ ] 8. Import `Response` from flask (it types the hook below).
## [ ] 9. A constant `_CSP`: the policy's directives joined by "; ":
##          | "default-src 'self'", "script-src 'self' https://cdn.jsdelivr.net",
##        then style-src 'self', img-src 'self' data:, connect-src 'self',
##        frame-ancestors 'none', base-uri 'self', form-action 'self'.
##        Never 'unsafe-inline' in script-src (the SOLUTION explains each).
## [ ] 10. A hook decorated with `@chat_bp.after_request` that sets
##        response.headers["Content-Security-Policy"] = _CSP and returns
##        the response. On the blueprint, it covers /login and /chat only.
## [ ] 11. Check: the 9.2 test of tests/platform_tests/test_platform_security.py,
##        then open /chat in the browser: the console shows no CSP errors,
##        and the guide's test message <img src=x onerror=alert(1)> shows
##        no alert.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from flask import Blueprint, render_template

## Guide 9.2: the type of the response the header hook receives.
from flask import Response

## Blueprint(name, import_name): `name` prefixes endpoint names
## (url_for("chat.login_page")); `__name__` tells Flask where the blueprint
## lives. It declares no template folder of its own, so render_template
## finds the pages in the app's templates/ folder (webapp/templates/).
chat_bp = Blueprint("chat", __name__)


## The login page. It only shows a form; the form's script posts the
## access code to the agent service (POST /agent/login), which sets the
## session cookie. Flask never sees the code.
@chat_bp.get("/login")
def login_page() -> str:
    """Render the login form (the agent service checks the code)."""
    return render_template("login.html")


## Guide 9.1: the chat page (commented twice until then).
@chat_bp.get("/chat")
def chat_page() -> str:
    """Render the chat page (no data embedded: it asks the agent service)."""
    return render_template("chat.html")


## Guide 9.2: the Content-Security-Policy (CSP) of the login and chat pages,
## the browser's second line of defence behind DOMPurify. Directive by
## directive:
## - default-src 'self': anything not listed below loads only from this site;
## - script-src: scripts only from this site and from the CDN that serves
##   marked and DOMPurify (pinned to exact versions in chat.html). There is
##   no 'unsafe-inline', so the browser runs no inline <script> and no
##   onclick=... attribute: even model text that slipped past DOMPurify as
##   HTML could not run code;
## - style-src 'self': stylesheets only from this site (these two pages use
##   no inline styles);
## - img-src 'self' data:: images from this site, plus small inline (data:)
##   images;
## - connect-src 'self': fetch() may only call this site, i.e. /agent/*;
## - frame-ancestors 'none': no other site may embed these pages
##   (clickjacking);
## - base-uri / form-action 'self': an injected <base> or <form> cannot
##   redirect links or form posts to another site.
## The hook is registered on the BLUEPRINT, so only /login and /chat get
## it. The existing pages (form, explore) build inline style attributes and
## get the site-wide policy from Caddy at guide 12.3.
_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://cdn.jsdelivr.net",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


@chat_bp.after_request
def _content_security_policy(response: Response) -> Response:
    """Add the Content-Security-Policy header to the blueprint's pages."""
    response.headers["Content-Security-Policy"] = _CSP
    return response
