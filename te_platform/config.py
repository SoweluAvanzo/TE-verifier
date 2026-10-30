## =============================================================================
## te_platform/config.py — all configuration, read once from the environment
## =============================================================================
## GUIDE STEP   1.1 (grows in later steps: each step adds its settings here)
## PURPOSE      One typed object, `Settings`, holds every configurable value of
##              the platform: database address, Redis address, allowed hosts,
##              limits, the Anthropic model name, and so on. Values come from
##              environment variables (set by Docker Compose from `.env` and
##              Docker secrets), are validated once at startup, and are then
##              read from this object only.
## USED BY      Almost every module: mcp_server/app.py (allowed hosts),
##              db/session.py (database URL), jobs/queue.py (Redis URL),
##              agent/providers/anthropic.py (model, API key), registry/
##              pipeline.py (timeouts), security/quotas.py (limits), ...
## DEPENDS ON   pydantic-settings (an add-on to Pydantic that fills a model from
##              environment variables; add it to the dependencies, see
##              pyproject_additions.toml).
## WHY          Guide §2.1 "configuration through the environment" (the
##              twelve-factor rule): the same image runs in development and
##              production; only the environment differs. Reading os.environ in
##              one place means every setting is documented, typed and
##              validated here, and a typo in a variable name fails at startup
##              instead of causing a mysterious bug later.
## ACTIVATE     1.1: uncomment the file (the general settings, check_environment
##              and get_settings). Each later group of fields is commented
##              twice under a "## Guide X.Y" line: toggle it again when you
##              reach that step (the step whose code first reads it).
##              Test: tests/platform_tests/test_platform_config.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: other files import them (te_platform/README.md,
## contracts table). Every field name is also an environment variable name
## (TE_ + the name in capitals), used in ../.env.example and compose files.
##
## Guide 1.1
## [ ] 1. Add the dependency first: copy the `platform` extra
##        (pydantic-settings, structlog) from pyproject_additions.toml into
##        ../pyproject.toml, then run `uv lock && uv sync --all-extras`.
## [ ] 2. Imports at the top: `os`, `Mapping` (collections.abc),
##        `lru_cache` (functools), `Path` (pathlib), `import pydantic`
##        (used as pydantic.Field now, pydantic.SecretStr from 5.2), and
##        `BaseSettings` and `SettingsConfigDict` (pydantic_settings).
## [ ] 3. The constant SECRETS_DIR = Path("/run/secrets"), then
##        `class Settings(BaseSettings)` (keep this name exactly) with a
##        docstring and its configuration as the first line of the class:
##          | model_config = SettingsConfigDict(env_prefix="TE_",
##          |     secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,
##          |     extra="forbid")
##        The SOLUTION's comments explain each of the three.
## [ ] 4. Inside Settings, the "General (guide 1.1)" fields:
##        `environment: str` with pydantic.Field(default="development",
##        pattern="^(development|test|production)$") and
##        `policy_dir: Path = Path("policy")`.
## [ ] 5. After the class: the set NOT_SETTINGS = {"TE_IMAGE_TAG"} and
##        `check_environment(environ: Mapping[str, str] | None = None)
##        -> None`. It uses os.environ when environ is None, builds the
##        known names from the fields, and raises RuntimeError listing the
##        unknown TE_* names, sorted:
##          | known = {"TE_" + name.upper() for name in Settings.model_fields}
##        (then add NOT_SETTINGS to `known`).
## [ ] 6. Last: `get_settings() -> Settings` (keep this name exactly),
##        decorated with @lru_cache(maxsize=1), returning Settings().
## [ ] 7. Check: activate tests/platform_tests/test_platform_config.py, then
##          | uv run pytest tests/platform_tests/test_platform_config.py -q
##          | uv run mypy te_platform
##
## Later steps: one group of fields each
## Add each group INSIDE Settings, under a comment saying what it is for,
## at the step whose code first reads it. Copy names, types and defaults
## exactly from the SOLUTION (other files read them). Secrets are always
## pydantic.SecretStr, never plain str. Check after each group: the step 7
## commands (the config tests of that step carry the same label).
## [ ] 8. Guide 2.4 (pipeline timeouts): tool_timeout_s (float, 60.0).
## [ ] 9. Guide 4.1 (HTTP MCP server): mcp_allowed_hosts and
##        mcp_allowed_origins (list[str]), forwarded_allow_ips (str,
##        "127.0.0.1").
## [ ] 10. Guide 4.2 (API keys): api_key_hashes (dict[str, str], empty).
## [ ] 11. Guide 5.2 (database): database_url (pydantic.SecretStr),
##        db_pool_size (5), db_echo (False).
## [ ] 12. Guide 5.3 (migrations): migration_database_url
##        (SecretStr | None).
## [ ] 13. Guide 6.1: redis_url. Guide 6.3: max_concurrent_jobs (2),
##        max_jobs_per_day (50), max_tool_calls_per_minute (60).
## [ ] 14. Guide 8.1 (agent service, login cookie and CSRF check used by
##        agent/auth.py): web_session_cookie, web_session_ttl_s,
##        public_origin.
## [ ] 15. Guide 8.3 (Anthropic provider): anthropic_api_key
##        (SecretStr | None), agent_model, agent_effort, agent_max_tokens,
##        agent_enable_refusal_fallback (False).
## [ ] 16. Guide 8.4 (agent loop, MCP bridge):
##        agent_max_tool_calls_per_turn, agent_max_seconds_per_turn,
##        agent_session_token_budget, agent_mcp_url,
##        agent_mcp_api_key (SecretStr | None).
## [ ] 17. Guide 10.1: report_storage_dir (Path). Guide 10.3:
##        report_signing_key (SecretStr | None), report_link_ttl_s.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

# --- Imports -----------------------------------------------------------------
# `lru_cache` turns get_settings() into a function that builds Settings once
# and then returns the same object: environment variables are read once.
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

## `import pydantic` (not `from pydantic import Field, SecretStr`): the file
## uses pydantic.Field from guide 1.1 and pydantic.SecretStr from guide 5.2,
## and one module import serves both, so the import lines never change.
## SecretStr is a string that prints as '**********', so secrets never end
## up in logs or error messages by accident; .get_secret_value() reads it.
import pydantic

## BaseSettings: like a Pydantic BaseModel, but each field is filled from an
## environment variable of the same name (with the prefix below).
from pydantic_settings import BaseSettings, SettingsConfigDict

## --- The settings model ------------------------------------------------------
## Docker mounts secrets as files in this folder (compose.yml `secrets:`).
## Outside a container it does not exist; pydantic-settings would then warn
## at every start, so it is only used when present (it is created before
## the process starts, so checking once at import is enough).
SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """Every configurable value of the platform.

    Each field maps to an environment variable named TE_<FIELD_NAME>,
    e.g. `policy_dir` <- TE_POLICY_DIR. Defaults are safe for local
    development; production overrides them in .env / Docker secrets.
    """

    # env_prefix: all variables start with TE_ so they never clash with
    #   variables of other programs.
    # secrets_dir: a file named te_anthropic_api_key in SECRETS_DIR fills
    #   the field anthropic_api_key (when the folder exists, see above).
    # extra="forbid": unknown keys passed directly (e.g. Settings(typo=1) in
    #   a test) are an error. NOTE: pydantic-settings silently IGNORES
    #   environment variables that match no field, so a misspelled TE_*
    #   variable is NOT caught by this; check_environment() below is.
    model_config = SettingsConfigDict(
        env_prefix="TE_",
        secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,
        extra="forbid",
    )

    # ---- General (guide 1.1) -----------------------------------------------
    # "development" relaxes nothing security-related; it only enables
    # friendlier error pages and debug logging.
    environment: str = pydantic.Field(
        default="development", pattern="^(development|test|production)$",
    )
    # Where the policy files live (tool_policy.yaml, elicitation_protocol.yaml).
    policy_dir: Path = Path("policy")

    ## Guide 2.4 (tool execution limits, read by registry/pipeline.py):
    ## maximum seconds a synchronous tool may run before it is stopped with
    ## a `timeout` error. Expensive tools run as jobs instead (phase 6).
    tool_timeout_s: float = 60.0

    ## Guide 4.1 (HTTP MCP server, mcp_server/app.py). mcp_allowed_hosts:
    ## host names accepted in the Host header (DNS-rebinding protection);
    ## in production your public domain only. mcp_allowed_origins: websites
    ## allowed to call the MCP server from a browser. forwarded_allow_ips:
    ## reverse proxies whose X-Forwarded-For header is trusted (uvicorn's
    ## forwarded_allow_ips); default only this machine, in Compose Caddy's
    ## address on the edge network.
    mcp_allowed_hosts: list[str] = ["localhost:8000", "127.0.0.1:8000", "mcp:8000"]
    mcp_allowed_origins: list[str] = []
    forwarded_allow_ips: str = "127.0.0.1"

    ## Guide 4.2 (API keys before the database exists): the known keys, as
    ## a JSON object {"<sha256 hash of the key>": "<principal id>"} in
    ## TE_API_KEY_HASHES. Only HASHES are configured, never plain keys
    ## (`te-platform keys create` prints them). From guide 5.4 on, keys
    ## live in the api_keys table and this mapping is no longer read.
    api_key_hashes: dict[str, str] = {}

    ## Guide 5.2 (database, db/session.py). SQLAlchemy URL;
    ## "postgresql+psycopg" selects the psycopg 3 driver. The app role has
    ## no DDL rights. db_pool_size: how many connections each process keeps
    ## open and reuses (opening one per query would be slow). db_echo=True
    ## prints every SQL statement: useful while learning, too noisy (and
    ## possibly revealing) in production.
    database_url: pydantic.SecretStr = pydantic.SecretStr(
        "postgresql+psycopg://te_app:te_app@localhost:5432/te",
    )
    db_pool_size: int = 5
    db_echo: bool = False

    ## Guide 5.3 (migrations, db/migrations/env.py): the te_migrator role,
    ## which owns the schema. Only the one-shot `migrate` service gets it,
    ## as the secret file te_migration_database_url (compose.yml).
    migration_database_url: pydantic.SecretStr | None = None

    ## Guide 6.1 (background jobs): where Redis runs.
    redis_url: str = "redis://localhost:6379/0"

    ## Guide 6.3 (quotas per principal, security/quotas.py).
    max_concurrent_jobs: int = 2
    max_jobs_per_day: int = 50
    max_tool_calls_per_minute: int = 60

    ## Guide 8.1 (agent service, agent/auth.py): name and lifetime of the
    ## login cookie, and the site's public address, e.g.
    ## "https://te.example.org". POST requests whose Origin header differs
    ## are rejected (CSRF defence).
    web_session_cookie: str = "te_session"
    web_session_ttl_s: int = 8 * 3600
    public_origin: str = "http://localhost:8080"

    ## Guide 8.3 (Anthropic provider). agent_model: the default model
    ## (architecture D9); change it only after the eval suite (phase 13)
    ## shows the alternative is at least as good. agent_effort: how hard the
    ## model thinks (low | medium | high | xhigh | max). agent_max_tokens:
    ## upper bound on one model response, in LLM tokens (large values need
    ## streaming, which the agent always uses). agent_enable_refusal_fallback:
    ## opt-in retry on a fallback model after a safety refusal (see
    ## agent/providers/anthropic.py); off until you have read the Anthropic
    ## documentation on refusals and fallbacks. anthropic_workspace_id: only
    ## for an API key that is not scoped to a workspace; the API then needs
    ## the workspace in every request (header anthropic-workspace-id). Its
    ## ID is on the workspace's page in the Anthropic Console.
    anthropic_api_key: pydantic.SecretStr | None = None
    anthropic_workspace_id: str | None = None
    agent_model: str = "claude-opus-5-5"
    agent_effort: str = "high"
    agent_max_tokens: int = 64_000
    agent_enable_refusal_fallback: bool = False

    ## Which model API the agent uses: "anthropic" (above) or
    ## "openai_compatible", a server speaking the OpenAI chat completions
    ## protocol (agent/providers/openai_compatible.py), e.g. the department's
    ## Open WebUI. llm_base_url: that server's API root (requests go to
    ## {llm_base_url}/chat/completions). llm_api_key: its key, a secret file
    ## (compose.yml maps secrets/te_utopia_api_key to te_llm_api_key). With
    ## that provider agent_model names one of the server's models and
    ## agent_max_tokens must fit the model's limit.
    llm_provider: str = pydantic.Field(
        default="anthropic", pattern="^(anthropic|openai_compatible)$",
    )
    llm_base_url: str = "https://utopia.hpc4ai.unito.it/api"
    llm_api_key: pydantic.SecretStr | None = None

    ## Guide 8.4 (agent loop and MCP bridge): per-turn and per-session
    ## limits (architecture §3.4), where the agent reaches the MCP server
    ## (internal Docker network), and the agent's own API key for it (a
    ## service principal).
    # The short interview records ~20 estimates in one turn (one call each).
    agent_max_tool_calls_per_turn: int = 40
    agent_max_seconds_per_turn: float = 180.0
    agent_session_token_budget: int = 400_000
    agent_mcp_url: str = "http://mcp:8000/mcp"
    agent_mcp_api_key: pydantic.SecretStr | None = None

    ## Guide 10.1 (report rendering): where the PDF files are written.
    report_storage_dir: Path = Path("/data/reports")

    ## Guide 10.3 (download links, security/signed_urls.py): the secret
    ## used to sign links (HMAC; long and random) and how long a link works.
    report_signing_key: pydantic.SecretStr | None = None
    report_link_ttl_s: int = 24 * 3600


## --- Catching misspelled variables ------------------------------------------
## Variables that start with TE_ but are read by OTHER programs, not by
## Settings: Docker Compose (the image tag in the server's .env, which
## `env_file` also passes into the containers). The database passwords are
## secret files, not variables (compose.yml, guide 5.1).
NOT_SETTINGS = {"TE_IMAGE_TAG"}


def check_environment(environ: Mapping[str, str] | None = None) -> None:
    """Raise RuntimeError if a TE_* variable matches no setting.

    Such a variable is almost always a typo (e.g. TE_DATABSE_URL), which
    pydantic-settings would silently ignore, leaving the default in place.
    Call it once at startup of every service, before get_settings()
    (mcp_server/app.py, agent/app.py, jobs/worker.py).
    """
    env = os.environ if environ is None else environ
    known = {"TE_" + name.upper() for name in Settings.model_fields} | NOT_SETTINGS
    unknown = sorted(k for k in env if k.startswith("TE_") and k not in known)
    if unknown:
        raise RuntimeError(f"Unknown TE_* environment variables (typo?): {', '.join(unknown)}")


## --- Accessor ----------------------------------------------------------------
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings, building it on first call.

    Use this function instead of creating Settings() yourself, so the
    environment is read once and every module sees the same values.
    Tests can call get_settings.cache_clear() after changing variables.
    """
    return Settings()
