## =============================================================================
## te_platform/__init__.py — marks te_platform/ as an importable Python package
## =============================================================================
## GUIDE STEP   1.1
## PURPOSE      A folder becomes a Python *package* (something you can
##              `import te_platform`) when it contains an __init__.py file.
##              This file is that marker. It also records the platform's
##              version, for humans and for `te_platform.__version__` checks.
## USED BY      Every module that does `from te_platform import ...`. (Reports
##              and verification_refs record the VERIFIER's version instead,
##              read from the installed package metadata by hashing.py,
##              because that is what determines the verdicts.)
## DEPENDS ON   Nothing.
## WHY          D1: one repository, one package, several container roles.
## ACTIVATE     1. Add "te_platform*" to [tool.setuptools.packages.find] in
##                 pyproject.toml (see pyproject_additions.toml).
##              2. Uncomment the line below.
##              3. Check: `uv run python -c "import te_platform; print(te_platform.__version__)"`.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code.
##
## Guide 1.1
## [ ] 1. Before writing any code: in ../pyproject.toml, replace the
##        `include` line of [tool.setuptools.packages.find] with the one in
##        te_platform/pyproject_additions.toml (step 1.1 section), so that
##        "te_platform*" is installed too. Then run `uv sync --all-extras`.
## [ ] 2. Write one line, the package version, as a plain string:
##          | __version__ = "0.1.0"
##        It must equal `version` in pyproject.toml (the `##` note below
##        explains why the value is written twice).
## [ ] 3. Check: run the `uv run python -c ...` command given in step 3 of
##        the ACTIVATE field above. It must print 0.1.0.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Keep this in sync with `version` in pyproject.toml. A single source would
## be nicer (importlib.metadata.version("token-economy-verifier")), but that
## only works once the package is installed, and this file must also work in
## a plain checkout during early development.
__version__ = "0.1.0"
__version__ = "0.1.0"
