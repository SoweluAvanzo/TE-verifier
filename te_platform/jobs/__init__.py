## =============================================================================
## te_platform/jobs/__init__.py — background jobs (simulations, reports)
## =============================================================================
## GUIDE STEP   6.1-6.3 (simulations), 10.3 (report rendering)
## PURPOSE      Marks jobs/ as a package. Work that takes longer than a web
##              request may last (Monte Carlo simulations, single trajectories,
##              PDF rendering) is put on a queue in Redis and done by separate
##              worker processes.
##
##              How the files relate:
##
##                tools/sim_*.py, tools/report_render_pdf.py
##                     │ enqueue_job / get_job / cancel_job
##                     ▼
##                queue.py ──(Redis, RQ)──► worker.py (te-worker process)
##                                              │ runs
##                                              ▼
##                                          tasks.py ──► service.py (simulate, trajectory)
##                                          report_task.py ──► reports/render.py (PDF)
##
##              queue.py runs inside the MCP server process; worker.py,
##              tasks.py and report_task.py run inside the `worker` container. They share only
##              Redis (the queue and results) and the database.
## WHY          Architecture D12: simulations exceed request timeouts (gunicorn
##              60 s, the pipeline's tool_timeout_s); RQ is a small library on
##              Redis with a short learning curve.
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
