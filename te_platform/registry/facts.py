## =============================================================================
## te_platform/registry/facts.py — derive the facts the rules need (pipeline step 3b)
## =============================================================================
## GUIDE STEP   2.4
## PURPOSE      Before the preconditions run, the pipeline needs a few facts
##              about the call: which spec it is about, whether that spec is
##              valid, its hash, and
##              whether the verification_ref the caller presents was really
##              computed from THIS spec. derive_facts() computes them once and
##              returns a CallFacts object; predicates.py only reads it.
## USED BY      registry/pipeline.py (step 3b).
## DEPENDS ON   te_platform.service.validate, te_platform.hashing,
##              registry/context.py.
## WHY          Keeps every rule a pure, one-line read of typed fields (D3),
##              and does the expensive part (validating the spec) exactly once
##              per call. The verification check needs NO database: because a
##              verification_ref is a content hash of (spec, verifier version,
##              config) (D5), the server recomputes it from the spec and
##              compares. A ref from another spec, or from before an edit,
##              cannot match.
## CONVENTION   Tool input models name these fields consistently so this file
##              can find them: `spec` (YAML text or object), `session_id`,
##              `verification_ref`. A tool without them simply gets the
##              "nothing known" defaults.
## ACTIVATE     Uncomment together with the pipeline's step 3b; tests in
##              test_platform_pipeline.py (ref from another spec -> mismatch).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `derive_facts`
## exactly as written (te_platform/README.md, contracts table). It needs
## hashing.py, service.py and context.py active.
##
## Guide 2.4
## [ ] 1. Imports at the top: `Any`, `anyio`, `BaseModel` from pydantic,
##        `hashing` and `service` from te_platform, and `CallContext`,
##        `CallFacts` from te_platform.registry.context.
## [ ] 2. A private helper `_expected_ref(spec_hash) -> str`: the ref
##        verify.run.v1 issues for that spec, i.e. hashing.verification_ref
##        of spec_hash, hashing.verifier_version() and
##        hashing.config_hash(None). Copy the `##` lines above it: they say
##        why None (paper defaults) is the only correct config here.
## [ ] 3. The signature (async, `quota_ok` keyword-only) and a docstring:
##          | async def derive_facts(validated: BaseModel, ctx: CallContext,
##          |                        *, quota_ok: bool = True) -> CallFacts:
## [ ] 4. Find the spec: getattr(validated, "spec", None); if it is None and
##        there is a session, use ctx.session.current_spec.
## [ ] 5. Find the ref the same way: the input's `verification_ref`, else
##        the session's verification_ref.
## [ ] 6. No spec: return CallFacts(spec_present=False, ...) carrying vref
##        and quota_ok.
## [ ] 7. Validate in a thread, because it is CPU work:
##          | v = await anyio.to_thread.run_sync(service.validate, spec)
##        If `not v.valid or v.spec_hash is None`, return spec_present=True,
##        spec_valid=False. (Testing spec_hash tells mypy it is a str below;
##        no `assert`: ruff's S101 forbids it, `python -O` removes it.)
## [ ] 8. Return the full CallFacts with verification_matches_spec =
##        (vref is not None and vref == _expected_ref(v.spec_hash)).
## [ ] 9. Check: activate it together with pipeline.py step 3b and
##        tests/platform_tests/test_platform_pipeline.py, then
##          | uv run pytest tests/platform_tests/test_platform_pipeline.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any

import anyio
from pydantic import BaseModel

from te_platform import hashing, service
from te_platform.registry.context import CallContext, CallFacts


# Which verifier configuration a verification_ref may have been computed
# with. verify.run.v1 always verifies with the paper defaults: its input
# model has no `config` field and its handler calls service.verify(spec)
# without one (test_platform_pipeline.py checks both). So the server only
# ever issues refs for config_hash(None), and that is the only ref a
# presented one can legitimately equal. If a tool ever accepts a custom
# VerifierConfig, the ref must carry it too: then compare against the
# config of THAT verification (stored with it from guide 5.5), not this.
def _expected_ref(spec_hash: str) -> str:
    return hashing.verification_ref(spec_hash, hashing.verifier_version(),
                                    hashing.config_hash(None))


async def derive_facts(validated: BaseModel, ctx: CallContext, *,
                       quota_ok: bool = True) -> CallFacts:
    """Derive the facts the preconditions read for one call (pipeline step 3b).

    `validated` is the tool's input after validation; `quota_ok` is what the
    pipeline's quota step found (always True before guide 6.3).
    """
    # 1. Which spec is this call about? The explicit one wins; otherwise the
    #    session's current spec (if the call belongs to a session).
    spec: Any = getattr(validated, "spec", None)
    if spec is None and ctx.session is not None:
        spec = ctx.session.current_spec

    # 2. Which verification does the caller present? Explicit, else the session's.
    vref: str | None = getattr(validated, "verification_ref", None)
    if vref is None and ctx.session is not None:
        vref = ctx.session.verification_ref

    if spec is None:
        return CallFacts(spec_present=False, verification_ref=vref, quota_ok=quota_ok)

    # 3. Validate against the schema in a thread: it is CPU work.
    #    (validate also lists coherence issues; they are findings, not
    #    blockers, so no rule needs them and they are not copied here.)
    v = await anyio.to_thread.run_sync(service.validate, spec)
    # A valid result always carries a hash; testing it here too tells the
    # type checker that spec_hash is a str below (no `assert`, which
    # `python -O` would remove).
    if not v.valid or v.spec_hash is None:
        return CallFacts(spec_present=True, spec_valid=False, verification_ref=vref,
                         quota_ok=quota_ok)

    # 4. Does the presented ref belong to this exact spec? Recompute and
    #    compare (_expected_ref above explains the configuration part).
    return CallFacts(
        spec_present=True,
        spec_valid=True,
        spec_hash=v.spec_hash,
        verification_ref=vref,
        verification_matches_spec=(vref is not None and vref == _expected_ref(v.spec_hash)),
        quota_ok=quota_ok,
    )
