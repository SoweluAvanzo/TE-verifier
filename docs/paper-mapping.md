# Paper mapping — what cites what

This document is the audit trail between the source paper
(*Six Failure Modes…*, DLT2026) and the verifier implementation. For
every paper section, equation, and threshold the implementation
encodes, the corresponding location in the codebase is listed here.
For every paper-derived numeric value in `verifier/config.py`, the
paper section that justifies it is recorded in the `ConfigValue`'s
`paper_section` field; this document indexes those.

The document is checked against the codebase by
`tests/test_paper_mapping.py` (Phase 0): every row in the tables below
must correspond to a real symbol in `paper.py` or `config.py`, and
every paper-cited symbol in those modules must appear in this
document.

## Paper sections → conditions

| Paper section | Failure mode | `paper.py` symbol | Encoding module | Proof file |
|---|---|---|---|---|
| §3.1 | FM1: Token oversupply / inflation spiral | `paper.FM1` | `verifier/failure_modes/fm1_oversupply.py` | `docs/proofs/fm1.md` |
| §3.2 | FM2: Token velocity trap | `paper.FM2` | `verifier/failure_modes/fm2_velocity.py` | `docs/proofs/fm2.md` |
| §3.3 | FM3: Burn / emission imbalance | `paper.FM3` | `verifier/failure_modes/fm3_burn_emission.py` | `docs/proofs/fm3.md` |
| §3.4 | FM4: Free-rider collapse | `paper.FM4` | `verifier/failure_modes/fm4_freerider.py` | `docs/proofs/fm4.md` |
| §3.5 | FM5: Insufficient critical mass | `paper.FM5` | `verifier/failure_modes/fm5_critical_mass.py` | `docs/proofs/fm5.md` |
| §3.6 | FM6: Governance capture | `paper.FM6` | `verifier/failure_modes/fm6_governance.py` | `docs/proofs/fm6.md` |

## Paper equations → sustainability predicates

| Paper equation | What it says | `paper.py` field | Verifier check |
|---|---|---|---|
| eq. (5)–(8) (§3.1) | Fisher equation `MV = PQ`; design-stage `E* = PQ/V`. | `FM1.sustainability_ascii` | FM1 `E ≤ E*` |
| eq. (9)–(12) (§3.2) | `τ̄ = Σ_i (M_i/M)·E_i[τ]`; `V ≥ 1/τ̄`; trap when `τ̄ → 1`. | `FM2.sustainability_ascii` | FM2 `τ̄ > τ_ceiling` |
| eq. (13)–(15) (§3.3) | Net supply change `Ṁ = E − B`. | (premise of FM3) | FM3 setup |
| eq. (16) (§3.3) | Sustainability `E − B ≤ g·M`; ρ ≥ 1 in steady state. | `FM3.sustainability_ascii` | FM3 ρ ≥ ρ_floor |
| eq. (17) (§3.4) | Ostrom proportionality `φ ≥ d/K`. | `FM4.sustainability_ascii` (clause 1) | FM4 clause 1 |
| eq. (18) (§3.4) | Monitoring condition `γ·S > T − R`. | `FM4.sustainability_ascii` (clause 2) | FM4 clause 2 |
| eq. (19)–(21) (§3.5) | Critical mass `N ≥ 2K·d + 1` from well-mixed match-counting. | `FM5.sustainability_ascii` | FM5 |
| eq. (22) (§3.6) | Centralization `Γ = U/T ≤ 0.5`. | `FM6.sustainability_ascii` | FM6 |

## Paper-derived thresholds → `VerifierConfig`

| Paper threshold | `VerifierConfig` field | Default | Override allowed | Justification |
|---|---|---|---|---|
| FM2 ceiling (paper: τ̄ → 1) | `tau_bar_velocity_trap_ceiling` | 1.5 | Yes | Discrete-check conservatism above the asymptotic limit. See `config.py`. |
| FM3 floor (paper: ρ ≥ 1 in steady state) | `rho_burn_coverage_floor` | 1.0 | Yes | Direct from eq. (16). |
| FM4 default temptation gap (paper: qualitative) | `default_temptation_gap_normalized` | 0.5 | Yes | Neutral mid-range; Phase 2 derives from elicitation. |
| FM4 sanction calibration (paper: qualitative) | `sanction_kind_to_S_normalized` | table | Yes | Calibrated from Ostrom design principle 5; phase 2 elaborates. |
| FM6 Γ threshold (paper: Γ ≤ 0.5) | `gamma_capture_threshold` | 0.5 | Yes | Direct from eq. (22). |
| FM6 Gini secondary (paper: qualitative) | `gini_secondary_threshold` | 0.6 | Yes | Calibration; rationale in `config.py`. |
| Numerical tolerance | `numeric_epsilon` | 1e-9 | No | Method constant. |

### Phase 2 — Elicitation calibration tables

These three tables drive the elicitation layer (Roadmap docx → IR
field → derived paper parameter). Each entry is configurable and
documented in `docs/proofs/derivations.md`.

| Table | `VerifierConfig` field | Maps | Paper § | Justification |
|---|---|---|---|---|
| Verification → γ range | `contribution_verification_to_gamma` | docx 1.5 → FM4 γ | §3.4 eq. (18) | docx mechanism descriptions translated to γ intervals. |
| Holding incentive → τ floor | `holding_incentive_to_tau_floor` | docx 1.4 → FM2 τ | §3.2 eq. (12) | docx 1.4 ranking translated to per-mechanism floors. |
| (Verification, redemption) → temptation gap | `verification_redemption_to_temptation_gap` | docx 1.5 + 1.6 → FM4 (T − R) | §3.4 eq. (18) | Monotone matrix; small gap when verification + redemption are both structured. |

### Phase 5 — Archetype routing and NFR multipliers

| Table | `VerifierConfig` field | Effect | Paper § |
|---|---|---|---|
| Archetype FM skip list | `archetype_fm_applicability` | Marks FMs N/A based on `meta.archetype` | (verifier infrastructure) |
| NFR1 → ρ multiplier | `nfr1_resilience_rho_multiplier` | Tightens FM3 ρ floor for high-resilience designs | §3.3 (advisory) |
| NFR5 → φ multiplier | `nfr5_proportionality_phi_multiplier` | Tightens FM4 contributor-rate condition for high-proportionality designs | §3.4 (advisory) |

## `paper.py` symbols → variable definitions

Every `PaperVariable` in `verifier/paper.py` carries a `paper_section`
field. The cross-reference is automated (Phase 0 test
`test_paper_module.py::test_every_variable_has_paper_section`); this
table is human-readable.

| Symbol | Variable | Paper § | Used in FMs |
|---|---|---|---|
| `E(t)` | emission rate | §3.1 | FM1, FM3 |
| `B(t)` | burn rate | §3.3 | FM1, FM3 |
| `M(t)` | circulating supply | §3.1 | FM1, FM3 |
| `g(t)` | participant growth rate | §3.3 | FM3 |
| `V` | velocity | §3.2 | FM1, FM2 |
| `τ̄` | wealth-weighted holding time | §3.2 | FM2 |
| `Q` | expected transaction volume | §3.1 | FM1 |
| `N` | participant count | §3.5 | FM5 |
| `K` | offer variety | §3.4 | FM4, FM5 |
| `d` | average demand per participant | §3.4 | FM4, FM5 |
| `φ` | active contributor rate | §3.4 | FM4 |
| `γ` | monitoring capacity | §3.4 | FM4 |
| `S` | sanction magnitude | §3.4 | FM4 |
| `T − R` | temptation gap | §3.4 | FM4 |
| `Γ` | centralization index | §3.6 | FM6 |
| `G` | token-balance Gini | §3.6 | FM6 |

## NFR reweightings → FM verdicts

The paper does not directly state how non-functional-requirement
declarations should reweight FM verdicts; this is design infrastructure
introduced by the verifier to make user intent first-class. The
reweightings are documented in each FM's `paper.py` `nfr_reweightings`
field and in the proof file.

| NFR | Reweights | Effect | Documented in |
|---|---|---|---|
| NFR6 = circulate_fast | FM2 | FAIL → PASS_AS_INTENDED | `paper.FM2.nfr_reweightings`, `docs/proofs/fm2.md` |
| NFR7 = indefinite (with type=centralized) | FM6 | FAIL → PASS_AS_INTENDED | `paper.FM6.nfr_reweightings`, `docs/proofs/fm6.md` |
| NFR1 = high resilience | FM3 (Phase 5) | tighten ρ floor | `docs/proofs/fm3.md` (Phase 5) |
| NFR3 = high accessibility | coherence check (Phase 5) | flag `accessibility=5 + verification=smart_contract` | `docs/proofs/derivations.md` (Phase 5) |
| NFR5 = high proportionality | FM4 (Phase 5) | tighten `φ ≥ d/K` margin | `docs/proofs/fm4.md` (Phase 5) |

## Calibrations not stated by the paper

The following values are **calibrations** the verifier introduces
because the paper is qualitative on them. Each has a documented
justification in `verifier/config.py` and is configurable.

| Field | Default | Rationale |
|---|---|---|
| `tau_bar_velocity_trap_ceiling` | 1.5 | Conservative discrete proxy for `τ̄ → 1`. |
| `default_temptation_gap_normalized` | 0.5 | Neutral mid-range. Phase 2 derives from `(verification, redemption)`. |
| `sanction_kind_to_S_normalized` | table | Ordered by Ostrom design principle 5. |
| `gini_secondary_threshold` | 0.6 | Inflection point in observed DAO concentration data. |

When the paper is published, this table will be the audit document
reviewers reference to verify nothing is silently calibrated.

## Drift policy

When the paper revises an equation or threshold:

1. Update `verifier/paper.py` with the new formal statement.
2. Update `verifier/config.py` defaults if a numeric threshold changed.
3. Update the corresponding `docs/proofs/fm{n}.md` to reflect the new
   derivation.
4. Update this table.
5. Add or update tests in `tests/test_paper_mapping.py` and
   `tests/test_paper_module.py` to lock the new values.

All five steps land in the same PR. CI's `test_paper_mapping.py` fails
otherwise.
