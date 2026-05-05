# Topology corrections to FM5

> **Status.** Phase 5c — implemented.

## Statement

For a token economy with `topology = NETWORK` and an
`average_degree ∈ [δ_lo, δ_hi]` declared in `topology_params`, the
critical-mass condition reduces to

> `δ_lo ≥ 2·K·d`,

independent of `N`. The participant count `N` becomes irrelevant
(provided each participant has the declared average degree).

## Paper reference

§3.5 last paragraph notes the well-mixed bound is conservative for
non-well-mixed topologies. The explicit network-correction formula is
introduced by the verifier; the math is a corollary of the matching
derivation in §3.5.

## Assumptions

1. **(Connected component.)** Every participant is in a single
   connected component of average degree `avg_degree`. Disconnected
   communities require a per-component analysis (Tier-2 work).
2. **(Match probability scales with degree.)** The probability that a
   given participant finds a compatible match per period is
   `avg_degree / K` rather than `(N − 1) / K`. Justified by the
   well-mixed argument restricted to the participant's neighborhood.

## Proof

Repeating the well-mixed derivation from `docs/proofs/fm5.md` but
restricting the per-participant reachable population to `avg_degree`:

The expected number of compatible matches per period at participant
`i` is `avg_degree / K` (assumption 2). Aggregate matches across all
`N` participants: `N · avg_degree / (2·K)` (factor 1/2 because each
match is counted from both ends).

Aggregate demand per period: `N · d`.

Sustainability:

> `N · avg_degree / (2·K) ≥ N · d`
>
> ⟺  `avg_degree ≥ 2·K·d`. ∎

This is **strictly weaker** than the well-mixed `N ≥ 2·K·d + 1` when
`avg_degree < N − 1` — i.e. for genuinely networked populations the
verifier accepts smaller `N` provided each participant has enough
neighbors.

## Critical-value formula

> `avg_degree* = 2 · K · d`

By monotonicity in K and d, the worst-case is at the upper corner:

> `avg_degree*_worst = 2 · K_hi · d_hi`.

## Z3 encoding

Closed-form via `2 * K_hi * d_hi` evaluation. No Z3 needed.

In `verifier/failure_modes/fm5_critical_mass.py`:

```python
avg_deg_range = te.participants.topology_params.get("average_degree")
if topology == NETWORK and avg_deg_range is not None:
    deg_star = 2 * K_hi * d_hi
    if avg_deg_range.min >= deg_star:
        return PASS  # network-corrected
```

When the network rule passes, the verifier short-circuits before
running the well-mixed Z3 check; otherwise it falls through to the
well-mixed analysis (which still produces an INCONCLUSIVE for
network topology, accompanied by the network-corrected critical
value for redesign guidance).

## Numerical correctness

Closed-form arithmetic; exact within IEEE 754 modulo
`numeric_epsilon`.

## Tests

- `tests/test_phase5_topology.py::test_network_topology_passes_with_high_degree`
- `tests/test_phase5_topology.py::test_network_topology_fails_with_low_degree`
(added in Phase 5e).

## Lean stub

```lean
-- File: TEVerifier/Topology.lean
theorem fm5_network_correction (K d δ : ℝ)
    (hK : 0 < K) (hd : 0 ≤ d) (hδ : 0 ≤ δ) :
    -- Network sustainability ↔ avg_degree ≥ 2·K·d
    sorry := by
  sorry
```
