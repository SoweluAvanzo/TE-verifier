# Proofs document — entry point

This directory is the mathematical truth layer of the verifier. For
every claim the verifier makes — a failure-mode condition, a critical
value formula, an elicitation-derivation rule, a Z3 encoding — there is
a corresponding proof file here that:

1. **states the claim formally** (Statement),
2. **lists the assumptions** (Assumptions),
3. **proves the claim** in rigorous mathematical English (Proof),
4. **shows how the Z3 encoding realizes the claim** (Z3 Encoding), and
5. **declares the Lean 4 stub** for future Tier-2 mechanization (Lean Stub).

When the paper is published, every claim in this directory must be
traceable to a paper section or to an explicitly-flagged calibration
that the paper does not pin down. The `paper_section` and
`paper_equation` fields on every `verifier.config.ConfigValue` and
`verifier.paper.PaperCondition` cross-reference here.

## Why this layer exists

The verifier's contract with the user is "your design is provably
sustainable iff the six conditions hold." That contract is only as
good as the proofs that justify each condition's encoding. Without this
directory, "we encode FM4 as `γ·S > T − R`" would be an unverified
implementation choice; with it, it is a checkable mathematical claim.

Markdown is rigorous enough for Tier-1: every step in every proof is
explicit, every assumption is named, every elided manipulation is one
the reader can re-derive. Lean 4 mechanization (Tier-2) replaces
"the reader can re-derive" with "the kernel re-derives."

## Files

| File | Topic | Status |
|---|---|---|
| `template.md` | The canonical proof template every other file follows. | Authoritative |
| `optimization.md` | Z3 `Optimize` correctness over linear/polynomial real arithmetic; threshold-extraction primitive. | Skeleton (Phase 0); finalized in Phase 1. |
| `fm1.md` | FM1 oversupply: condition, derivation, critical-value formula, encoding. | Skeleton; finalized in Phase 1. |
| `fm2.md` | FM2 velocity trap: τ̄ definition, NFR6 reweighting, threshold rationale. | Skeleton; finalized in Phase 1. |
| `fm3.md` | FM3 burn/emission imbalance: ρ definition, structural credit for demand-driven burn, growth-corrected boundary. | Skeleton; finalized in Phase 1. |
| `fm4.md` | FM4 free-rider: Ostrom proportionality, monitoring condition, γ\* and K\* formulas. | Skeleton; finalized in Phase 1. |
| `fm5.md` | FM5 critical mass: well-mixed derivation, structured-topology bound. | Skeleton; finalized in Phase 1. |
| `fm6.md` | FM6 governance capture: Γ definition, Gini secondary signal, n\_demote integer programming. | Skeleton; finalized in Phase 1. |
| `derivations.md` | Elicitation-derivation rules (mechanism → parameter range). Each rule has a justification and override semantics. | Created in Phase 2. |
| `composition.md` | Composition rules — event frequency × per-event amount = rate; cross-token flow contributions. | Created in Phase 5. |
| `sensitivity.md` | The "swept vs committed" marking semantics and the cross-FM coupling graph. | Created in Phase 4. |

## PR rule

Every PR that touches a paper-derived value (in `verifier/paper.py` or
`verifier/config.py`) or that adds an elicitation-derivation rule (in
`verifier/elicitation.py`, Phase 2 onwards) must update the
corresponding proof file in this directory in the same PR. CI enforces
this via a script that diffs the affected source files and the
proofs directory.

## Lean 4 mechanization (Tier-2)

Each proof file ends with a `Lean Stub` section declaring the Lean 4
signature that mechanizes the claim. These stubs are not yet imported
into a Lean project; they are placeholders for the parallel-track
mechanization work scheduled after the webapp prototype lands. The
stubs use Mathlib's `Asymptotics` namespace (`IsBigO`, `IsTheta`,
`IsLittleO`) for asymptotic-class reasoning, since the choice of Lean +
Mathlib over Coq or Isabelle is justified specifically by Mathlib's
existing treatment of those classes.
