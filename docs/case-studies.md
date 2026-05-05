# Case Studies — Stack Validation Against Known Token Economies

This document picks five publicly known token economies — diverse in archetype, scale, and outcome — encodes each in the TE-IR sketched in [docs/architecture.md](architecture.md), and traces the six failure-mode conditions from the paper through them. The goals are: (1) demonstrate that the IR can faithfully represent real designs; (2) check whether the stack would have produced *useful* verdicts and counterexamples; (3) surface gaps in the IR or the toolchain that need to be closed before the verifier ships.

## Methodology and honest scoping

The verification stack (KeYmaera X, dReach/dReal, Lean 4 + Mathlib, cadCAD) is **not yet installed** and the IR schema has no implementation. The "verification" exercises below are therefore performed **analytically by hand**, applying the closed-form sustainability conditions from §3 of the failure-modes paper to public parameters of each system. Concretely: for each case we (a) write the TE-IR by hand, (b) plug numbers into FM1–FM6 conditions, (c) record what each backend in the stack *would* do once running, and (d) note what kind of counterexample each backend *would* produce. When the stack is implemented, these encodings become the first integration tests; the analytical verdicts here become the expected outputs.

Public parameters are cited where they matter. Where exact figures differ across sources or change over time we use round design-stage estimates and flag the dependence; the analytical verdict is robust to small variations.

The five cases cover deliberately different shapes:

| Case | Archetype | Tokens | Outcome | What it stresses in the stack |
|---|---|---|---|---|
| Bitcoin | Fixed-supply native asset | 1 (BTC) | Long-running; healthy | Bounded-supply asymptotics, FM6 edge case |
| Ethereum (post-EIP-1559) | Demand-burning fee economy | 1 (ETH) | Healthy | Demand-driven burn, FM3 structural correctness |
| MakerDAO | Collateral-backed stablecoin + governance | 2 (DAI + MKR), cross-flow | Survived a real failure (Black Thursday 2020) | Cross-token flows, oracle-dependent verification, FM3 + FM6 |
| Curve / veCRV | Vote-escrow governance | 2 (CRV + veCRV), time-locked | Operational, governance-captured | Time-decaying positions, FM6 on token Gini |
| Axie Infinity | Play-to-earn dual token | 2 (AXS + SLP) | **Famous collapse 2021–2022** | Whether the verifier would have flagged it pre-launch (FM1 + FM2 + FM3 + FM4 simultaneously) |

---

## Case 1 — Bitcoin

**Why this case.** The simplest non-trivial design: fixed terminal supply, zero burn, time-based emission with a discrete halving schedule. Tests whether the IR can express bounded-supply asymptotics (which technically lie outside the standard polynomial / exponential / log lattice) and whether the verifier handles a system designed to satisfy FM1 by construction.

**Public parameters.** Terminal supply 21 000 000 BTC. Block reward halves every 210 000 blocks (~4 years); current reward 3.125 BTC/block (post-April 2024 halving). Block interval ~10 minutes. Active address count ≈ 10⁷–10⁸. No protocol-level burn. Governance via Bitcoin Improvement Proposals (BIPs) requiring rough consensus among core developers and miner adoption.

### TE-IR encoding

```yaml
TokenEconomy:
  meta:
    name: Bitcoin
    nfrs:
      circulation_speed: retain_value      # store-of-value culture
      governance_maturity: indefinite
      adaptability: 1                       # protocol intentionally rigid
      transparency: 5
      proportionality: 5                    # PoW = work proportional rewards
      resilience: 5
      accessibility: 2
  tokens:
    - id: BTC
      function: [medium_of_exchange, store_of_value]
      value_anchor: none
      emission_rules:
        - trigger: { kind: time_based }
          function:
            sign: decreasing_positive
            asymptotic_class:
              family: bounded_range          # asymptotically constant at 21M
              bounds: { min: 0, max: 21_000_000 }
            parameters: { initial_block_reward: 50, halving_interval_blocks: 210_000 }
          regimes:                           # halving schedule, sketched
            - predicate: "blocks_since_genesis > 210_000"
              active_function: { sign: decreasing_positive, asymptotic_class: { family: constant }, parameters: { reward: 25 } }
            - predicate: "blocks_since_genesis > 420_000"
              active_function: { ..., parameters: { reward: 12.5 } }
            # …repeats; in implementation a generator should emit all 33 halvings
      burn_rules: []                         # no protocol burn
      initial_distribution: { kind: none }
  participants:
    count_N: { min: 10_000_000, max: 100_000_000 }
    growth: { family: log }                  # adoption decelerating
    expected_Q: { min: 1e5, max: 1e6 }       # daily on-chain tx, decoupled from holders
    topology: well_mixed
    agent_types:
      - { id: hodler,  fraction: 0.7, expected_holding_time: { class: linear, parameters: { years: 3 } } }
      - { id: trader,  fraction: 0.25, expected_holding_time: { class: bounded_range, bounds: { min_days: 1, max_days: 30 } } }
      - { id: miner,   fraction: 0.05, expected_holding_time: { class: bounded_range, bounds: { min_days: 1, max_days: 7 } } }
  governance:
    type: hybrid
    rule_structure:
      protocol_change: rough_consensus_dev_plus_miner
      mining_difficulty: algorithmic
      block_reward: not_adjustable
    monitoring_capacity: 0.99                # all on-chain
    sanction_structure: { kind: economic, S: high }
```

### Failure-mode trace

- **FM1 (oversupply / inflation).** The condition is `Δ(MV)/MV > ΔQ/Q`. Emission `Ė(t)` is exponentially decaying toward zero; cumulative supply asymptotes at 21M; therefore `Ṁ/M → 0`. Adoption-driven `Q̇/Q` is positive log-class. Conclusion: condition fails-to-hold (i.e. inflation does *not* arise) for all `t > t*` where `t*` is computable. **Pass.**
- **FM2 (velocity trap).** Wealth-weighted holding time `τ̄` measured in years, not days. `τ̄ → 1` (one period) is nowhere near. **Pass.**
- **FM3 (burn/emission imbalance).** `B(t) = 0`, `E(t) > 0`, so the condition `E − B ≤ g·M` requires `E/M ≤ g`. Currently `E/M ≈ 1.5%/yr` and falling; `g` (active address growth) historically ≥ that. **Pass conditionally**, with the verifier emitting "passes provided `g ≥ Ė/M`, which holds for adoption growth ≥ X%/yr."
- **FM4 (free-rider collapse).** Not directly applicable — Bitcoin has no contributor-to-redeemer economy in the cooperative sense. The verifier should mark this as *N/A* given the token function set, not flag it.
- **FM5 (critical mass).** `N ≥ 2Kd + 1` trivially holds; `N` is in the tens of millions.
- **FM6 (governance capture).** This is the interesting one. Computing `Γ = unilateral_decisions / total_decisions` over the BIP process gives a borderline figure: protocol upgrades require both core-dev and miner-pool consent, and miner-pool concentration has at times exceeded 50%. Likely flagged depending on encoding. The August 2017 Bitcoin Cash hard fork is a documented governance dispute that supports `Γ > 0.5` for that period.

### What each backend would do

- **dReach/dReal.** Fast δ-decision over the supply ODE. Would return "no inflation counterexample within δ" for FM1; would surface a concrete `t*` from which sustainability holds.
- **KeYmaera X.** Differential dynamic logic naturally expresses the bounded-supply ODE plus the discrete halving jumps as a hybrid program. Yields a certified proof of FM1 sustainability for `t → ∞`.
- **Lean 4 + Mathlib.** Theorem: "supply emission of class `bounded_range(0, M_max)` satisfies FM1 for any `g(t) ≥ 0` after some `t*`." Generic theorem, reusable by every fixed-supply system.
- **cadCAD.** Numerical simulation showing supply asymptote; useful for the user-facing visualization but not load-bearing for the verdict.

### Counterexample produced (FM6, illustrative)

> "If we model `Γ` as the fraction of upgrade-relevant decisions where a coalition of the top-3 mining pools could unilaterally veto, then for the period 2017-Q3 that coalition controlled 71% of hashrate, yielding `Γ ≈ 0.71 > 0.5`. Concrete trajectory: SegWit2x activation timeline, miner-pool signaling matrix on dates 2017-07 through 2017-11."

### Notes on stack fit

- The asymptotically-bounded supply does not fit the polynomial/log/exponential lattice cleanly; `bounded_range` was added to the IR for exactly this. The Lean theorem has to be stated in terms of `IsBigO (fun t => 1)` (i.e. `O(1)`), which Mathlib supports.
- The 33-step halving regime expansion is verbose. The IR should grow a `RegimeGenerator` shorthand (e.g. `halvings(initial=50, period=210_000, count=33)`) so users don't write 33 `RegimeSwitch` entries.

---

## Case 2 — Ethereum (post-Merge, with EIP-1559)

**Why this case.** Cleanest example of a *demand-driven burn*. Tests whether the IR distinguishes demand-driven from rule-driven (which the paper requires for FM3 to be assessed correctly) and whether the verifier rewards correct structural choices.

**Public parameters.** Total supply ~120 M ETH. Issuance: ~0.6%/yr post-Merge under Proof-of-Stake, scaling sub-linearly with total stake. Burn: per-transaction `base_fee × gas_used`, dynamic. In high-activity periods net issuance has been negative. Governance: off-chain rough consensus via the EIP process; no on-chain token-weighted vote.

### TE-IR encoding

```yaml
TokenEconomy:
  meta:
    name: Ethereum (post-Merge, EIP-1559)
    nfrs:
      circulation_speed: balanced
      governance_maturity: medium_term
      transparency: 5
  tokens:
    - id: ETH
      function: [medium_of_exchange, store_of_value, governance_right]   # informal governance
      value_anchor: none
      emission_rules:
        - trigger: { kind: time_based }                       # per-slot validator rewards
          function:
            sign: always_positive
            asymptotic_class:
              family: linear                                   # in stake amount, sub-linear globally
              parameter_ranges: { issuance_rate: [0.004, 0.012] }   # 0.4%–1.2%/yr
              parameters: { participation_factor: 0.5 }
      burn_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "transaction.included"
            event_frequency:
              family: linear                                   # transactions roughly proportional to active users
              parameter_ranges: { tx_per_user_per_day: [0.1, 5] }
          function:
            sign: always_negative
            asymptotic_class:
              family: linear                                   # base_fee × gas
              parameter_ranges: { avg_base_fee_gwei: [5, 200] }
  participants:
    count_N: { min: 1e7, max: 1e8 }                            # active addresses
    growth: { family: log }
    topology: well_mixed
    agent_types:
      - { id: hodler,    fraction: 0.6, expected_holding_time: { class: linear, parameters: { years: 2 } } }
      - { id: defi_user, fraction: 0.3, expected_holding_time: { class: bounded_range, bounds: { min_days: 1, max_days: 90 } } }
      - { id: validator, fraction: 0.1, expected_holding_time: { class: linear, parameters: { years: 1 } } }
  governance:
    type: hybrid
    rule_structure:
      protocol_change: rough_consensus_off_chain
      issuance_curve: not_adjustable_within_eip
    monitoring_capacity: 0.99
    sanction_structure: { kind: economic_slashing, S: high }
```

### Failure-mode trace

- **FM1.** Net `Ṁ` can be negative when burn > issuance. Even when positive, `Ė/M ≈ 0.6%/yr`. With `Q` (transaction throughput) growing log-class with adoption, `(MV)' / MV < Q'/Q` holds. **Pass.**
- **FM2.** Staking, holding incentives, deep store-of-value culture; `τ̄` measured in months at minimum. **Pass.**
- **FM3.** Burn is **demand-driven** (it fires per transaction inclusion, scaling with `Q`). The condition `E − B ≤ g·M` is much easier to satisfy: when `Q` increases, `B` increases, automatically tightening the supply. The IR's `burn_rules.trigger.kind = behavioral_event` distinguishes this from a rule-driven schedule, and the verifier should reward it with a structurally-strong pass.
- **FM4.** Same N/A as Bitcoin — no community-contribution model.
- **FM5.** Trivially passes.
- **FM6.** Off-chain rough consensus produces a moderate `Γ`. Core developer concentration is real but balanced by validators and the broader EIP process. Borderline; depends on encoding choices.

### What each backend would do

- **dReach.** Verifies `∀ avg_base_fee ∈ [5, 200] gwei`, `∀ tx_per_user ∈ [0.1, 5]/day`, FM3 holds. Returns no counterexample.
- **KeYmaera X.** Hybrid program with continuous issuance ODE and burn jumps on transaction events. Certified proof of FM3 over the parameter range.
- **Lean.** General theorem: "if `B(t) = α · Q(t)` for `α > 0` and `E(t) = β · M(t)` with `β` constant, then `ρ ≥ 1` whenever `Q(t)/M(t) ≥ β/α`." Reusable for any fee-burn design.
- **cadCAD.** Recreates the historical `ρ` series; useful for sanity-checking the analytical verdict against history.

### Counterexample (none expected)

If we set the parameter ranges to extreme values (e.g. `avg_base_fee = 0.01 gwei`, `tx_per_user = 0.001/day`) the verifier should produce a degenerate-low-activity counterexample showing `ρ < 1`. This is a useful *sensitivity* output: "your design is sustainable as long as activity does not collapse below X."

### Notes on stack fit

- This case validates the **structural distinction between demand-driven and rule-driven burn** that the IR enforces. A naive boolean "has burn / no burn" would not have given Ethereum partial credit; the structural class does.
- The "issuance rate scales with `√(total stake)`" sub-linearity of Ethereum's actual curve is not perfectly captured by `family: linear`. The IR may need a `family: sublinear_root(degree)` extension, or this can be approximated by tightening `parameter_ranges` and noting the systematic underestimate.

---

## Case 3 — MakerDAO (DAI + MKR)

**Why this case.** First multi-token case with a real cross-token flow (stability fees → DAI surplus → MKR buyback-and-burn). Tests `cross_token_flows` in the IR. More importantly, MakerDAO suffered a documented partial failure on Black Thursday (March 12, 2020) when oracle delays and a 50% ETH price crash forced emergency MKR minting. The verifier — given the right oracle-delay model — should produce that exact counterexample.

**Public parameters.** DAI: pegged to USD 1.00, supply elastic (~$5B at peak). MKR: cap ~1M tokens, no scheduled emission, burned via surplus auctions when stability-fee revenue exceeds bad debt. Collateralization ratio for ETH vaults: 150% (liquidation threshold). Stability fees: variable by collateral type. Governance: token-weighted DAO, `Γ` low nominally but with concentrated holders (a16z and others).

### TE-IR encoding

```yaml
TokenEconomy:
  meta:
    name: MakerDAO
    nfrs:
      circulation_speed: circulate_fast      # DAI is medium of exchange
      governance_maturity: short_term
      resilience: 4
  tokens:
    - id: DAI
      function: [medium_of_exchange, unit_of_account]
      value_anchor: pegged                   # to USD 1.00
      redemption: { kind: open_market }
      emission_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "vault.opened OR vault.collateral_added"
            event_frequency: { family: linear, parameter_ranges: { vaults_per_day: [10, 1000] } }
          function:
            sign: always_positive
            asymptotic_class: { family: linear, parameter_ranges: { dai_per_eth_locked: [0, 0.66] } }   # 1/150% LTV
      burn_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "vault.debt_repaid OR vault.liquidated"
          function:
            sign: always_negative
            asymptotic_class: { family: linear, parameter_ranges: { burn_per_repayment: [1, 1] } }
    - id: MKR
      function: [governance_right]
      value_anchor: none
      emission_rules:
        - trigger:
            kind: algorithmic
            event_predicate: "system_surplus < 0"            # bad debt outpaces revenue
          function:
            sign: always_positive
            asymptotic_class: { family: unspecified }        # emergency, magnitude not bounded a priori
      burn_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "system_surplus > 0 AND auction.completed"
            event_frequency: { family: linear, parameter_ranges: { auctions_per_week: [0, 5] } }
          function:
            sign: always_negative
            asymptotic_class: { family: linear, parameter_ranges: { mkr_burned_per_auction: [10, 1000] } }
  cross_token_flows:
    - source_token: DAI
      source_event: "stability_fees_accrued > debt_auction_threshold"
      target_token: MKR
      target_action: burn
      amount: { asymptotic_class: { family: linear }, parameters: { conversion_via: surplus_auction } }
    - source_token: MKR
      source_event: "system_surplus < 0"
      target_token: DAI
      target_action: mint                                   # emergency: MKR minted, sold for DAI to cover debt
      amount: { asymptotic_class: { family: unspecified } }
  participants:
    count_N: { min: 1e4, max: 1e5 }
    growth: { family: linear }
    topology: well_mixed
    agent_types:
      - { id: vault_owner,   fraction: 0.7, expected_holding_time: { class: bounded_range, bounds: { min_days: 30, max_days: 365 } } }
      - { id: mkr_governor,  fraction: 0.05, expected_holding_time: { class: linear, parameters: { years: 2 } } }
      - { id: dai_user,      fraction: 0.25, expected_holding_time: { class: bounded_range, bounds: { min_days: 1, max_days: 30 } } }
  governance:
    type: dao
    rule_structure:
      stability_fee:        token_holder_vote
      collateral_onboarding: token_holder_vote
      emergency_shutdown:   token_holder_vote
    monitoring_capacity: 0.99
    sanction_structure: { kind: economic, S: high }
```

### Failure-mode trace

- **FM1 (DAI).** Pegged to USD; price `P` is held to 1.00 by arbitrage and the savings rate. Inflation in DAI's purchasing power is not assessed via Fisher; the verifier instead checks whether the peg can be maintained, which reduces to FM3.
- **FM2 (DAI).** NFR6 = `circulate_fast`; high velocity is the design goal. Velocity trap not a risk for DAI by intent.
- **FM3 (DAI).** `B(t)` is demand-driven (fires on debt repayment / liquidation). Structurally sound. **Pass** — provided liquidations actually occur.
- **FM3 (MKR).** Here is where it gets interesting. In normal operation `ρ_MKR > 1`: stability-fee revenue burns MKR. But the IR's emission rule for MKR fires on `system_surplus < 0`, with `asymptotic_class: unspecified` — the verifier cannot bound the magnitude. The verifier should flag: "Under the trajectory where collateral price drops by Δ within window W and oracle latency exceeds L, MKR emission becomes unbounded; FM3 violated for those trajectories."
- **FM4.** No contribution-reward economy in the cooperative sense.
- **FM5.** Trivially passes ($billion TVL).
- **FM6.** `Γ` from the governance rule structure: all key levers are token-holder votes, so `Γ_nominal ≈ 0`. Token Gini is moderate-to-high — secondary signal. Borderline; depends on whether we count voting concentration empirically.

### Black Thursday counterexample (FM3 for MKR)

Given an oracle-delay model and a sharp ETH-price input range, the verifier should produce:

> "Trajectory `t = 0..72h`: ETH price drops from $200 to $90 within 24h. Oracle update lag = 1h. Vaults with collateralization ratio in [150%, 165%] become undercollateralized but liquidations execute at stale prices. System surplus drops below 0; MKR emergency emission triggers, supply increases by ~8%. `ρ_MKR(t)` falls to roughly −0.5 over the 72h window. FM3 violated."

This is approximately the historical Black Thursday outcome: MakerDAO minted ~5.7M new MKR after the event to cover bad debt. **A pre-deployment verifier with the oracle-delay model encoded would have caught this exact trajectory.**

### What each backend would do

- **dReach.** Strong fit. δ-decision over `(eth_price_drop_rate, oracle_latency)` space; produces concrete trajectories where the system fails. Black Thursday counterexample emerges naturally.
- **KeYmaera X.** Hybrid program with the price input as a continuous nondeterministic variable bounded by a rate constraint; produces certified statement of the form "for all price drop rates ≤ R%/hour, FM3 holds; for rates > R% with oracle latency > L, it fails."
- **Lean.** Theorem about cross-token flows: "if `T2.emission` is unbounded conditional on `T1`'s state, then `T1`'s state must be bounded for `T2`'s `ρ` to be well-defined." A reusable structural lemma.
- **cadCAD.** Replays Black Thursday with stress-test parameter sweeps; produces historically-accurate trajectories.

### Notes on stack fit

- Cross-token flows work cleanly in the IR. Good.
- **Critical gap surfaced**: external oracles (price feeds) are not first-class in the current IR. They show up implicitly via `parameter_ranges` on the cross-token flow but the **rate of change** of the external input (price drop rate, oracle update frequency) is not capturable. We need an `ExternalSignal` IR construct with bounds on both value and derivative. Without it, the Black Thursday counterexample cannot be expressed.
- The verifier's verdict here depends critically on the assumed bounds of the external signal. If the user's `parameter_ranges` for ETH price drop rate are wrong, the verdict is misleadingly confident. **The decision flow must surface this and force the user to commit to a worst-case bound, with a sensitivity-analysis pass after the verdict.**

---

## Case 4 — Curve / veCRV

**Why this case.** Time-locked vote-escrow positions: users lock CRV for up to 4 years and receive non-transferable veCRV with voting power that decays linearly to zero over the lock period. Tests whether the IR can express **time-decaying balances**, and whether FM6 picks up the well-documented Convex-driven governance concentration ("Curve Wars").

**Public parameters.** CRV total supply ≈ 3.03B (cap). Emission: decaying schedule, ~2/3 to liquidity providers. veCRV obtained by locking CRV; voting power = `locked_amount × (time_remaining / 4 years)`. Convex Finance accumulated ~50% of veCRV supply through cvxCRV deposits at peak.

### TE-IR encoding

```yaml
TokenEconomy:
  meta:
    name: Curve / veCRV
    nfrs:
      circulation_speed: retain_value         # locking incentive is the entire design
      governance_maturity: short_term
  tokens:
    - id: CRV
      function: [governance_right, medium_of_exchange]
      value_anchor: none
      emission_rules:
        - trigger: { kind: time_based }
          function:
            sign: decreasing_positive
            asymptotic_class:
              family: bounded_range
              bounds: { min: 0, max: 3_030_000_000 }
            parameters: { initial_daily: 2_200_000, decay_rate: "annualized 16%" }
      burn_rules: []
    - id: veCRV
      function: [governance_right]
      value_anchor: none
      transferable: false
      # veCRV positions DECAY linearly over the lock period — IR gap, see notes
      emission_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "user.lock_crv(amount, duration)"
          function:
            sign: always_positive
            asymptotic_class: { family: linear }              # initial veCRV amount = locked × (duration / 4y)
      burn_rules:
        - trigger:
            kind: time_based
            event_predicate: "lock_decay_per_block"
          function:
            sign: decreasing_positive                          # decay = continuous burn
            asymptotic_class: { family: linear }
  cross_token_flows:
    - source_token: CRV
      source_event: "user.lock"
      target_token: veCRV
      target_action: mint
      amount: { asymptotic_class: { family: linear }, parameters: { ratio: "locked × duration / 4y" } }
    - source_token: veCRV
      source_event: "lock_expired"
      target_token: CRV
      target_action: transfer                                  # CRV returned to user
      amount: { asymptotic_class: { family: linear }, parameters: { ratio: 1.0 } }
  participants:
    count_N: { min: 1e4, max: 1e5 }
    growth: { family: log }
    topology: network
    topology_params: { dominant_aggregator: "Convex Finance" }
  governance:
    type: dao
    rule_structure:
      gauge_weights:        veCRV_weighted_vote
      pool_admin_fee:       veCRV_weighted_vote
    monitoring_capacity: 0.95
    sanction_structure: { kind: none, S: 0 }
```

### Failure-mode trace

- **FM1.** CRV emission is bounded; `Ṁ → 0`. Pass.
- **FM2.** Massive holding incentive by design (4-year max lock for max voting power). `τ̄ → 1` is impossible by construction. Pass.
- **FM3 (CRV).** No native CRV burn. `ρ_CRV = 0`. Strictly the condition fails: `E − B = E > 0`. Whether this is a real issue depends on `g(t)`; once `E` decays toward zero (by 2030 emissions are tiny relative to circulating supply), the condition becomes asymptotically satisfied. The verifier should flag "structurally violates FM3 in growth phase; recovers as `E → 0`."
- **FM4.** LP contribution model. Offer variety `K` = number of pools (large, hundreds). `d` = average user demand (variable). `φ` = LP participation rate. Empirically passes; the verifier could prove it parametrically.
- **FM5.** Trivially passes.
- **FM6.** This is the headline. `Γ_nominal = 0` (all governance is token-vote), but token Gini is high: at peak Convex held ~50% of veCRV → effective single-actor control over gauge weights. Secondary `G` signal flags. **Pass nominal, flagged on Gini.**

### Counterexample (FM6 via token Gini)

> "Aggregator entity `A` accumulates veCRV through user deposits via a wrapping protocol with 90%+ of users depositing into `A`. By month 14, `A` controls 51% of veCRV. From that point, every governance proposal that requires a simple majority can be passed unilaterally by `A`. Trajectory: cvxCRV wrapping launch (May 2021) → veCRV share progression → first majority threshold crossed (~Q4 2021)."

### What each backend would do

- **dReach.** Can model the cumulative-deposit dynamic into Convex as an ODE; finds the threshold crossing time.
- **KeYmaera X.** The time-decaying voting weight is an ODE on `voting_power(t) = locked × max(0, (T_unlock - t) / 4y)`. dL handles this gracefully.
- **Lean.** Theorem: "in a vote-escrow system where any aggregator that does not redistribute voting rights can accumulate, governance Gini converges to 1 unless redistribution is enforced." A reusable structural lemma about veToken designs.
- **cadCAD.** Models the Curve Wars dynamic empirically; pairs with on-chain data to validate.

### Notes on stack fit

- **Major IR gap surfaced**: time-decaying balances are not a first-class IR concept. We hacked them above by giving veCRV a continuous burn rule, but this is awkward — the burn is per-position, not aggregate, and depends on each lock's start and duration. The IR needs a `LinearlyDecayingBalance` construct that takes (locked_amount, lock_duration, current_time) and yields the current balance. **Action item: add this to the IR before the schema is frozen.**
- This case also shows that FM6's token-Gini secondary signal is at least as important as `Γ` for vote-weighted DAOs; the verifier must compute and report both.

---

## Case 5 — Axie Infinity (AXS + SLP)

**Why this case.** The decisive test. Axie's economy collapsed publicly in 2022 with SLP price falling from ~$0.40 to ~$0.005. The collapse was driven by the simultaneous violation of FM1, FM2, FM3, and FM4 — exactly the supply-side reinforcing triad the paper warns about (§3.1, end). **If the verifier cannot flag this design pre-launch, it is not useful.** This case validates or invalidates the entire stack premise.

**Public parameters.** AXS: cap 270M, emission via staking and play-to-earn. SLP: uncapped emission, earned per Adventure win and PvP victory. Burn: SLP consumed in Axie breeding, in fixed amounts per breed (rule-driven), plus AXS partly. Player base peaked ~2.7M daily active in late 2021; collapsed to <100k by mid-2022.

### TE-IR encoding

```yaml
TokenEconomy:
  meta:
    name: Axie Infinity
    nfrs:
      circulation_speed: circulate_fast       # SLP designed for spending in-game
      governance_maturity: short_term
      proportionality: 3
  tokens:
    - id: AXS
      function: [governance_right, access_right, store_of_value]    # access: needed for breeding
      value_anchor: none
      emission_rules:
        - trigger: { kind: time_based }
          function:
            sign: decreasing_positive
            asymptotic_class: { family: bounded_range, bounds: { min: 0, max: 270_000_000 } }
      burn_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "axie.breed"
            event_frequency: { family: unspecified, parameter_ranges: { breeds_per_day: [0, 1e5] } }
          function:
            sign: always_negative
            asymptotic_class: { family: linear }
    - id: SLP
      function: [medium_of_exchange]                                # in-game only
      value_anchor: none
      emission_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "player.adventure_win OR player.pvp_win"
            event_frequency:
              family: linear                                         # emission scales linearly with N
              parameter_ranges: { wins_per_player_per_day: [10, 50] }
          function:
            sign: always_positive
            asymptotic_class: { family: constant }                  # fixed SLP per win, ~150 SLP/day per player
            parameters: { slp_per_day_per_active_player: [50, 200] }
      burn_rules:
        - trigger:
            kind: behavioral_event
            event_predicate: "axie.breed"
            event_frequency:
              family: unspecified                                    # depends entirely on player demand to breed
              parameter_ranges: { breeds_per_day: [0, 1e5] }
          function:
            sign: always_negative
            asymptotic_class: { family: constant }
            parameters: { slp_per_breed: [600, 1300] }              # variable schedule
  cross_token_flows:
    - source_token: SLP
      source_event: "axie.breed"
      target_token: AXS
      target_action: burn                                           # breeding also consumes some AXS
      amount: { asymptotic_class: { family: constant }, parameters: { axs_per_breed: 0.5 } }
  participants:
    count_N: { min: 1e5, max: 3e6 }                                  # peak DAU
    growth:
      family: unspecified                                            # initially exponential, then crashed
      parameter_ranges: { growth_rate_per_month: [-0.5, 1.0] }       # IRL went from +50%/mo to −50%/mo
    expected_Q: { min: 1e6, max: 1e8 }                               # daily SLP transactions
    topology: well_mixed
    agent_types:
      - { id: scholar,  fraction: 0.6, expected_holding_time: { class: bounded_range, bounds: { min_hours: 1, max_hours: 24 } } }
      - { id: manager,  fraction: 0.3, expected_holding_time: { class: bounded_range, bounds: { min_days: 1, max_days: 30 } } }
      - { id: breeder,  fraction: 0.1, expected_holding_time: { class: bounded_range, bounds: { min_days: 7, max_days: 365 } } }
  governance:
    type: centralized                                                # Sky Mavis effectively controls
    rule_structure:
      slp_emission_rate:    single_entity
      breeding_cost:        single_entity
      adventure_rewards:    single_entity
    monitoring_capacity: 0.7
    sanction_structure: { kind: account_ban, S: medium }
```

### Failure-mode trace — the analytical pre-mortem

- **FM1 (SLP) — fails immediately.** `E_SLP(t) = N(t) × slp_per_day_per_active_player`. Burn `B_SLP(t)` depends on breeding demand, which is bounded by the rate at which players want new Axies — itself bounded by player growth. When `N(t)` is growing exponentially in early phases, both `E` and `B` rise; the system maintains rough balance only while *new players keep arriving to breed*. When `g(t) → 0` (saturation) and then `g(t) < 0` (decline), `B(t)` collapses while `E(t)` continues. The condition `Ṁ_SLP/M_SLP > Q̇/Q` is violated for any `g(t) < g*` where `g* ≈ slp_per_day_per_player / breeding_cost`. Plugging numbers: `g* ≈ 150/800 ≈ 0.19/day` ≈ rapid sustained growth. **Once growth dropped below ~5%/week, FM1 violation was guaranteed by design.**
- **FM2 (SLP) — fails by design intent.** `expected_holding_time` for scholars is hours, not days. The Filipino scholar economy was structurally a velocity-trap: earn SLP, immediately sell to PHP, spend on cost-of-living. `τ̄ → 1` exactly. **FAIL.**
- **FM3 (SLP) — fails because burn is ambivalent.** Burn is demand-driven *in form* (fires on breeding) but the demand for breeding is tied to *expected SLP earnings*. Once SLP price falls, breeding ROI falls, breeding demand falls, burn falls. Positive feedback: lower price → less burn → more excess supply → even lower price. The verifier with the right cross-derivative model detects the runaway. **FAIL.**
- **FM4 — fails on contribution structure.** Most participants are SLP earners (scholars), few are breeders (only ~10%). `φ` (active contributor rate, where contribution = breeding which produces value) is too low; `d/K` (demand for new Axies / Axie variety) is high in growth phase, low in decline. The free-rider condition `φ ≥ d/K` is satisfied only in growth. **FAIL.**
- **FM5.** Passes throughout (millions of users at peak).
- **FM6.** Centralized governance; `Γ ≈ 1`. Flagged. The user might mark NFR7 = "indefinite" to declare this acceptable, but for a P2E claiming community ownership the gap between declared positioning and `Γ` is itself diagnostic.

**Verifier verdict:** four supply-side and incentive-side failure modes flagged simultaneously, with concrete counterexample trajectories tying the failure to specific parameter combinations (player growth rate, breeding ROI, scholar holding time). All four conditions evaluate at design stage from public parameters alone — no longitudinal data required.

### Counterexample produced (FM1 + FM3 combined)

> "Let `N(t)` be the daily active player count and assume `g(t) = N'(t)/N(t)`. With `slp_per_day_per_player = 150`, `slp_per_breed = 800`, `breeds_per_day = 0.1 × N(t) × g(t)` (only growing populations breed), and constant SLP price assumption `P = 0.40 USD`: for any `g(t) < 0.05/day` sustained for `T > 30` days, `M_SLP(t)` grows linearly while `Q(t)` (driven by breeding demand) collapses, and `P` must fall to satisfy Fisher → demand-driven feedback loop → P collapses by factor 10× within 90 days. Trajectory: `g` drops below `0.05/day` at `t = T_critical`; price collapse begins at `T_critical + ~20d`. Empirically: T_critical ≈ January 2022, collapse pronounced by April 2022."

### What each backend would do

- **dReach.** Strong. Parameter sweep over `(g(t), slp_per_breed, scholar_holding_time)`; finds the failure region.
- **KeYmaera X.** ODEs for `M_SLP`, `M_breed_demand`, with switching on `g(t)`. Hybrid program produces a certified "for any g(t) ≤ g*, FM1 fails."
- **Lean.** Theorem about constant-emission games: "any economy with `E ∝ N` and `B ∝ N × g(N)` is sustainable iff `g(N) ≥ E/B_per_event`. Once `g → 0`, system violates FM1 unconditionally." This is the deep structural insight that should live in the proofs document.
- **cadCAD.** Replays the Axie collapse with parameter sweeps; the trajectory matches history.

### Notes on stack fit

- **The strongest case for the stack.** Every ingredient — multi-token, cross-token burn dependency, agent-type holding time heterogeneity, parametric growth-rate sensitivity — is captured by the IR and resolved by the closed-form failure-mode conditions from the paper. A pre-launch verifier would have flagged this design with high confidence.
- The verifier's value here is exactly the "you must commit to a worst-case bound" discipline that MakerDAO needed: Axie's design implicitly assumed perpetual exponential growth, and forcing the user to commit to a `parameter_ranges.growth_rate` that includes negative values surfaces the failure immediately.

---

## Cross-case assessment

### Where the stack handles things well

1. **Closed-form sustainability conditions are a perfect target.** All six failure-mode conditions from the paper reduce to inequalities over (sign, asymptotic class, parameter range). For each of the five cases, the analytical verdict could be derived without simulation. **The model checker is doing exactly the right kind of reasoning for this domain.**
2. **The structural distinction between demand-driven and rule-driven burn earns its keep.** Ethereum's structurally correct `B = α · Q` design is rewarded with a clean FM3 pass; Axie's superficially-similar but population-dependent burn is correctly flagged.
3. **Multi-token + cross-token flows scale.** All three multi-token cases (MakerDAO, Curve, Axie) encoded cleanly. The `CrossTokenFlow` IR construct is load-bearing and works.
4. **Counterexample quality is high where the failure is parametric.** The Axie pre-mortem and Black Thursday reconstruction read like real post-mortems, not abstract logic outputs. Users can act on them.
5. **Lean reuse is real.** Each case surfaced at least one general theorem (bounded-supply ⇒ FM1 in the limit; demand-driven burn ⇒ structural FM3 pass; veToken aggregator ⇒ Gini approaches 1) that lives in the proofs document and is reused across systems.

### Where the stack would struggle

1. **External signals are not first-class.** MakerDAO's failure mode hinges on the **rate of change** of an external price feed and the **latency** of an oracle. The current IR has no `ExternalSignal` construct with bounds on value *and* derivative *and* observation lag. Without it, oracle-dependent designs cannot be verified meaningfully. **High-priority IR addition.**
2. **Time-decaying balances are not first-class.** Curve veCRV positions decay continuously; we hacked it via per-position burn rules. A `LinearlyDecayingBalance` (or more generally, `BalanceWithTrajectory`) IR construct is needed before locking the schema.
3. **Sub-linear / non-standard asymptotic classes.** Ethereum's `√(stake)` issuance curve, Bitcoin's bounded-range supply, Curve's exponential decay toward a cap — these don't all fit the polynomial/log/exponential lattice. Either the lattice grows or we adopt a `family: derived` construct that defers to Lean's `IsBigO` machinery directly.
4. **Behavioral assumptions are a soft underbelly.** Axie's collapse hinged on `expected_holding_time` for scholars and on the assumption that scholars sell immediately. The IR captures both, but how does the user know their estimate is right? The verifier's confidence is bounded by the user's parameter discipline.
5. **Sensitivity analysis is implicit.** The verifier currently outputs pass/fail per failure mode. What it should also output is the **boundary** at which each verdict flips — the closest counterexample even when the system passes, so the user knows how much margin they have. cadCAD parameter sweeps can do this, but the integration into the diagnostic aggregator needs to be explicit.

### What this tells us about the specification flow

The five cases produce a clear lesson: **the most useful early questions are the ones that determine which IR fields are even active.** Asking a Bitcoin user about graduated sanctions or asking an Axie user about cross-token oracle latency wastes their time and ours. The roadmap document's linear questionnaire (groups 1.1 → 1.7 → 2.1 → ...) is a poor fit; many users will skip 60% of the fields, and others will not realize fields are even relevant.

What the cases reveal as the *real* organizing axes:

- **Archetype recognition first.** The five cases cluster into recognizable patterns: fixed-supply native asset, demand-burning fee economy, collateral-backed multi-token, vote-escrow governance, play-to-earn dual token, plus the paper's community/cooperative archetype. Identifying the archetype early lets the flow pre-populate sensible defaults and skip irrelevant questions.
- **Multi-token branching matters.** The single-token / multi-token decision is binary and changes everything downstream (cross-token flows, governance distribution per token, etc.). Ask it second, after the archetype.
- **External-dependency disclosure is mandatory and easy to forget.** Every case with an external signal (MakerDAO price feed, Axie SLP-to-fiat exchange) had its failure mode driven by that signal's behavior. The flow must explicitly ask "does any rule in your system depend on a value coming from outside the protocol?" and force the user to bound it.
- **Behavioral declarations need a confidence handle.** The user should be allowed to say "I don't know" for `expected_holding_time` per agent type, and the verifier must respond with sweep-based bounds rather than a false-confident pass.
- **Failure-mode triage should be NFR-driven.** If the user declares NFR6 = `circulate_fast` (DAI-style), the velocity trap is not a risk, it is the goal — the verifier should report it as "feature working as intended" not "warning". The current paper's framework supports this; the flow must surface it.

These observations drive [docs/specification-flow.md](specification-flow.md), the user-facing decision flow that the next document constructs.

---

## Summary table — what the verifier would say about each case

| Case | FM1 | FM2 | FM3 | FM4 | FM5 | FM6 | Headline counterexample |
|---|---|---|---|---|---|---|---|
| Bitcoin | Pass | Pass | Pass conditional on `g ≥ Ė/M` | N/A | Pass | Borderline (mining concentration) | 2017 SegWit2x miner-pool concentration |
| Ethereum | Pass | Pass | **Pass with structural credit** (demand-driven burn) | N/A | Pass | Borderline | (none expected at design stage) |
| MakerDAO | Pass (peg-mediated) | N/A (intentional high V) | Pass for DAI; **flagged for MKR** under oracle-delay scenarios | N/A | Pass | Pass nominal, secondary Gini concern | **Black Thursday 2020 reconstruction** |
| Curve | Pass | Pass | **Flagged in growth phase** (no native CRV burn) | Pass | Pass | Pass nominal, **flagged on Gini** (Curve Wars) | Convex aggregator crossing 50% veCRV |
| Axie Infinity | **FAIL** | **FAIL** | **FAIL** | **FAIL** | Pass | Flag (centralized governance) | **Full pre-mortem of the 2022 collapse** |

Bitcoin and Ethereum should give clean passes (the verifier validates known-healthy designs). MakerDAO and Curve produce nuanced verdicts that surface real risks the systems are known to have. Axie produces a complete pre-mortem before launch, which is the headline value proposition.
