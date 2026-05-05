# NFR-driven reweighting

> **Status.** Phase 5d — implemented.

## Statement

Two non-functional requirements are wired to FM thresholds via
configurable multipliers:

- **NFR1 (resilience)** scales `rho_burn_coverage_floor` in FM3.
- **NFR5 (proportionality)** scales the demand side of the contributor-
  rate condition in FM4 (effectively `φ · K ≥ d · multiplier`).

Both multipliers default to `1.0` for ratings 1–3 and rise modestly
for ratings 4–5. The defaults are no-ops on the case-study verdict
matrix; users can override the tables in `VerifierConfig` to enforce
stricter policies.

NFR6 (circulation_speed = circulate_fast) and NFR7 (governance_maturity
= indefinite + centralized) reweight verdict **status** rather than
threshold values; those reweightings are documented in `docs/proofs/fm2.md`
and `docs/proofs/fm6.md`.

## Paper reference

Verifier extension — the paper does not specify a coupling between
non-functional requirements and FM thresholds. The mechanism is
configurable so users can set policy that matches their context.

## Justification

NFR1 (resilience) declares "how important it is that the system
continues to function under stress." A high resilience requirement
should make the verifier less tolerant of marginal supply imbalance;
multiplying ρ_floor by 1.05 or 1.10 captures this.

NFR5 (proportionality) declares "how important it is that contributors
are not free-ridden upon." A high proportionality requirement should
make the verifier less tolerant of marginal contributor undersupply;
multiplying d by 1.10 or 1.20 captures this.

These are policy choices, not paper claims; they are configurable so
that organizations with different policy stances can apply the
verifier consistently.

## Monotonicity

Both multipliers are ≥ 1.0; the multiplied threshold is therefore
monotonically tighter as the NFR rating rises. **Setting NFR1 = 5
cannot turn a passing FM3 verdict into a failing one without changing
the underlying parameters** — it can only flip a marginal pass into a
fail. This monotonicity is what justifies the reweightings as honest
"tightening" rather than arbitrary verdict adjustment.

## Z3 encoding

```python
# FM3
nfr1_mult = config.nfr1_rho_multiplier_table[str(nfrs.resilience)]
rho_floor_effective = RHO_BURN_COVERAGE_FLOOR * nfr1_mult
solver.add(B_total < E_total * rho_floor_effective)
```

```python
# FM4
nfr5_mult = config.nfr5_phi_multiplier_table[str(nfrs.proportionality)]
cond_phi = phi * K < d * nfr5_mult   # tightened proportionality
```

Both multipliers are scalars known at solver-construction time; no
nonlinear arithmetic added.

## Tests

- `tests/test_phase5_nfr_reweighting.py` (Phase 5e):
  - Default multipliers preserve every case-study verdict.
  - Override multiplier to 2.0 → previously-passing FM3 / FM4 verdicts
    flip to FAIL on synthetic IRs near the boundary.
