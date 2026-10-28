## =============================================================================
## te_platform/security/__init__.py — small, focused security helpers
## =============================================================================
## GUIDE STEP   4.2 (api_keys), 6.3 (quotas), 10.3 (signed_urls)
## PURPOSE      Marks security/ as a package. Each module does ONE security job,
##              so it can be reviewed and tested on its own:
##                api_keys.py     create keys, hash keys (never store plain keys)
##                quotas.py       rate limits and job quotas, counted in Redis
##                signed_urls.py  tamper-proof, expiring download links
##              Callers: mcp_server/auth.py and cli.py (api_keys),
##              registry/pipeline.py step 2 (quotas), tools/report_render_pdf.py
##              and the download route (signed_urls).
## WHY          Guide §2.2: security code in few, small, well-tested places.
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
