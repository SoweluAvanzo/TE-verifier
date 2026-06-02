# Token-economy simulator — Flask app served by gunicorn.
# Production WSGI server (gunicorn) — the dev server / Werkzeug debugger in
# `webapp.app:main` is never invoked, so `debug=True` there is inert here.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip && pip install -e ".[webapp]" gunicorn==23.0.0

RUN useradd --system --uid 1000 --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://localhost:8000/ || exit 1

# --workers 1    : single process => the in-app rate limiter is exact + global
#                  (per-worker in-memory counters would otherwise be bypassed).
#                  Fine for a low-traffic, single-user tool.
# --timeout 60   : kill a worker stuck on a pathological Z3 model.
# --max-requests : recycle the worker periodically — guards against memory creep.
CMD ["gunicorn", "webapp.app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "60", "--max-requests", "200", "--max-requests-jitter", "50"]
