## =============================================================================
## te_platform/observability.py — structured JSON logs with correlation IDs
## =============================================================================
## GUIDE STEP   3.1 (the first server process, te-mcp, calls it at startup);
##              guide 12.5 builds on it (correlation IDs across services,
##              dashboards) without changing this file.
## PURPOSE      configure_logging(settings) makes every log line of the process
##              a JSON object, e.g.
##                {"event": "tool call ok", "tool": "verify.run.v1",
##                 "principal": "partner-lab", "correlation_id": "9f2c...",
##                 "level": "info", "timestamp": "2026-10-20T10:01:02Z"}
##              The rest of the code keeps using Python's standard `logging`
##              module (e.g. registry/pipeline.py:
##              log.info("tool call ok", extra={...})); this file only decides
##              how those records are written.
## USED BY      mcp_server/app.py (main), mcp_server/http_app.py (create_app),
##              jobs/worker.py main(),
##              agent/app.py (at import, i.e. process startup). The Flask web
##              app may call it too once it uses the service layer (1.6).
## DEPENDS ON   structlog, logging (standard library), config.py.
## WHY          Guide 3.1 and 12.5. JSON lines can be searched and filtered by field
##              ("all lines with correlation_id 9f2c..."), which plain text
##              cannot do reliably.
## CORRELATION IDS ACROSS SERVICES
##              One user action crosses several processes: browser -> agent
##              service -> MCP server -> job worker. Each step logs the SAME
##              correlation_id, passed on like this:
##                agent/chat_api.py creates one id per chat turn and agent/mcp_bridge.py
##                sends it as the X-Correlation-ID header with every tool call;
##                mcp_server/app.py uses it as ctx.correlation_id (the pipeline
##                logs it with every call); tools that queue jobs pass it to
##                jobs/queue.enqueue_job, which stores it in the job payload;
##                jobs/tasks.py binds it with structlog.contextvars, so every
##                log line of the job carries it.
##              Searching the logs for one id therefore shows the whole story
##              of one chat turn. The id is also returned in every ToolError,
##              so a user's bug report can be matched to the log.
## LATER        OpenTelemetry adds *traces*: timing of each step, shown as a
##              timeline in a tool such as Jaeger or Grafana Tempo. Add it only
##              when the logs are not enough to find slow steps.
## ACTIVATE     Uncomment; then call configure_logging(get_settings()) first
##              thing in each process's main(). Check: one tool call prints a
##              single JSON line with its correlation_id.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate config.py first
## (guide 1.1); structlog comes with the `platform` extra.
##
## Guide 3.1 (before mcp_server/app.py, which calls configure_logging)
## [ ] 1. Imports at the top: `logging`, `sys`, `TYPE_CHECKING` (typing),
##        `structlog` and `Settings` (te_platform.config); then `Processor`
##        (structlog.typing) inside an `if TYPE_CHECKING:` block, because
##        it is only used in a type annotation (ruff TC002).
## [ ] 2. Define `configure_logging(settings: Settings) -> None` (with a
##        one-line docstring) and, inside
##        it, the list `shared: list[Processor]` with five processors in
##        this order: structlog.contextvars.merge_contextvars,
##        stdlib.add_log_level, stdlib.add_logger_name,
##        processors.TimeStamper(fmt="iso", utc=True), stdlib.ExtraAdder().
##        The SOLUTION's comments say what each one adds.
## [ ] 3. Call structlog.configure(...) with the shared processors plus
##        ProcessorFormatter.wrap_for_formatter last, the stdlib
##        LoggerFactory() and cache_logger_on_first_use=True.
## [ ] 4. Build a structlog.stdlib.ProcessorFormatter: foreign_pre_chain is
##        `shared`; its processors are remove_processors_meta,
##        format_exc_info and JSONRenderer(), in that order.
## [ ] 5. Attach it to ONE handler that writes to stderr (never stdout:
##        it carries MCP messages in stdio mode) and make it the only
##        handler of the root logger:
##          | handler = logging.StreamHandler(sys.stderr)
##          | root.handlers[:] = [handler]
## [ ] 6. Levels: root at WARNING; "te_platform" at DEBUG when
##        settings.environment == "development", else INFO; "rq.worker" at
##        INFO.
## [ ] 7. Each process calls configure_logging(get_settings()) first thing
##        at startup; the call sites are written with their files
##        (mcp_server/app.py at 3.1, jobs/worker.py at 6.1, agent/app.py
##        at 8.1).
## [ ] 8. Check: `uv run mypy te_platform`; after mcp_server/app.py (3.1),
##        one tool call prints a single JSON line with its correlation_id.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import logging
import sys
from typing import TYPE_CHECKING

import structlog

from te_platform.config import Settings

## Processor is only used in a type annotation inside the function, which
## Python never evaluates at run time; importing it under TYPE_CHECKING
## (true only for mypy) keeps it out of the running program.
if TYPE_CHECKING:
    from structlog.typing import Processor


def configure_logging(settings: Settings) -> None:
    """Make every log line of this process one JSON object on stderr."""
    # Processors run in order on every log record, each adding or changing
    # fields. They are shared by structlog's own loggers and by records
    # coming from the standard `logging` module ("foreign" records).
    shared: list[Processor] = [
        # Adds fields bound with structlog.contextvars.bind_contextvars(...)
        # (jobs/tasks.py binds correlation_id there): every line logged
        # while a job runs carries them, without passing them around.
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,  # "level": "info"
        structlog.stdlib.add_logger_name,  # "logger": "te_platform.pipeline"
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Copies the fields passed as logging's `extra={...}` (tool,
        # principal, correlation_id, ...) into the JSON object.
        structlog.stdlib.ExtraAdder(),
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Stack traces (log.exception) become a "exception" field instead
            # of many separate lines, so one error = one JSON object.
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    # stderr, never stdout: in stdio mode the MCP server's stdout carries
    # protocol messages, and a log line there would corrupt them.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]  # replace any default handler
    # Our own messages at the configured level (DEBUG in development), but
    # third-party libraries (asyncio, redis, httpx2...) stay at WARNING:
    # at DEBUG they print so much internal chatter that our own lines get
    # lost (seen when running the scaffold).
    root.setLevel(logging.WARNING)
    logging.getLogger("te_platform").setLevel(
        logging.DEBUG if settings.environment == "development" else logging.INFO
    )
    # Worker progress ("job finished", "job failed") is worth keeping too.
    logging.getLogger("rq.worker").setLevel(logging.INFO)
