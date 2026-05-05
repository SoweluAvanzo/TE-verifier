# Archetype-driven dispatcher routing

> **Status.** Phase 5a — implemented.

## Statement

The dispatcher consults `VerifierConfig.archetype_fm_applicability`
before running each failure mode. When the archetype declares an FM
inapplicable, the verdict is recorded as `NOT_APPLICABLE` with a
formal condition citing the archetype rather than running the FM check.

## Paper reference

Verifier infrastructure — not a paper claim. The archetype field
itself is a verifier-introduced abstraction (see
`docs/specification-flow.md` Stage 1).

## Assumptions

1. **(Soundness of archetype labels.)** The user's `meta.archetype`
   declaration is honest — they are not labeling a contribution-reward
   community as `native_protocol_asset` to dodge FM4. Coherence checks
   in Phase 2 do not currently catch mislabeled archetypes; future
   Tier-2 work could.
2. **(Default empty skip lists are conservative.)** Every archetype
   defaults to skipping no FMs. The infrastructure is in place but
   any actual skipping is opt-in via config override.

## Justification for default empty lists

The Roadmap docx and the paper do not license blanket archetype-based
skipping of FMs. A Bitcoin-style native-protocol-asset *typically* has
no contribution-reward economy, but the verifier has no proof that
*every* native-protocol-asset is contribution-free. Users with a
specific design in mind can declare the skip list themselves.

This conservative default also preserves the verdict matrix from
Phase 0: every case study returns the same set of verdicts because no
archetype-based skipping is in effect by default.

## Override semantics

```yaml
# overrides.yaml
archetype_fm_applicability:
  native_protocol_asset: [FM4]      # skip FM4 for Bitcoin-likes
  stablecoin: []
  governance_utility_pair: []
  play_to_earn_dual: []
  community_reward: []
  other: []
```

```bash
te-verify examples/bitcoin.yaml --config overrides.yaml
# FM4 verdict: NOT_APPLICABLE   (N/A by archetype native_protocol_asset)
```

## Tests

- `tests/test_phase5_archetype.py::test_archetype_routing_skips_fm`
  (added in Phase 5e).
- `tests/test_paper_mapping.py` ensures the new config fields appear
  in the audit doc.
