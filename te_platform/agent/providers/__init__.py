## =============================================================================
## te_platform/agent/providers/__init__.py — model providers (package)
## =============================================================================
## GUIDE STEP   8.2 (interface + fake), 8.3 (Anthropic)
## PURPOSE      A "provider" is the piece of code that talks to one LLM API.
##              base.py defines the interface every provider implements;
##              anthropic.py is the real one; fake.py replays scripted turns
##              for tests. agent/loop.py only knows the interface, so swapping
##              the model provider is one new class plus an eval run (phase 13).
## WHY          Architecture D8 (provider adapter), D9.
## ACTIVATE     Nothing to uncomment here.
## =============================================================================
