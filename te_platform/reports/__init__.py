## =============================================================================
## te_platform/reports/__init__.py — the PDF report package
## =============================================================================
## GUIDE STEP   10.1-10.3
## PURPOSE      Marks reports/ as a package. It turns verification and
##              simulation results into a downloadable PDF:
##
##                render.py         — fills templates/report.html with data
##                                    (Jinja2) and converts HTML+CSS to PDF
##                                    (WeasyPrint)
##                charts.py         — draws the charts as SVG (matplotlib)
##                numbers_check.py  — rejects narrative text containing
##                                    numbers that are not in the results
##                templates/        — report.html and report.css
##
##              How the files relate (arrows = "uses"):
##
##                render.py ──► charts.py, numbers_check.py, templates/*
##
##              Callers outside: jobs/report_task.py (renders in the
##              worker, writes the PDF and stores the report row via
##              db/repo.py), tools/report_render_pdf.py (enqueues the job,
##              returns a signed link from security/signed_urls.py).
## WHY          Architecture D14 (template-based, deterministic reports) and
##              P1 (the LLM never produces a number: numbers_check.py
##              enforces it on the narrative).
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
