"""``te-simulate`` — run the reference ABM on a token-economy spec.

Companion to ``te-verify``. Pipeline:

    te-verify spec.yaml --minimal --json > verdicts.json
    te-simulate spec.yaml --verdicts verdicts.json --runs 1000

The verifier's verdict triages which FMs to simulate (SOUND skipped,
BROKEN refused, FRAGILE/INCONCLUSIVE simulated). The ABM adds
P(violation), Wilson 95% confidence intervals, deployment-vs-dynamic
breakdown, and time-to-violation quartiles.

When no ``--verdicts`` file is provided, ``te-simulate`` runs the
verifier itself and uses the result directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from schema import load_te
from verifier.abm import SimulationConfig, run_simulation
from verifier.config import VerifierConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="te-simulate",
        description=(
            "Reference ABM for the Token Economy verifier. Consumes "
            "the verifier's minimal output and reports P(violation), "
            "time-to-violation, and the deployment-vs-dynamic split "
            "per failure mode."
        ),
    )
    parser.add_argument("spec", type=Path, help="Path to a TE-IR YAML file.")
    parser.add_argument(
        "--runs",
        type=int,
        default=500,
        help="Number of Monte Carlo replicates (default 500).",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=260,
        help="Simulation horizon in periods (default 260 ≈ 5 years).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for determinism. Omit for a fresh run each invocation.",
    )
    parser.add_argument(
        "--verdicts",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file containing the verifier's minimal "
            "output (from `te-verify ... --minimal --json`). When "
            "omitted, te-simulate runs the verifier itself."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="VerifierConfig overrides YAML (passed to the verifier).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of the text table.",
    )
    parser.add_argument(
        "--simulate-all",
        action="store_true",
        help=(
            "Simulate every FM, including SOUND and BROKEN ones "
            "(useful as a sanity check on the verifier's verdicts)."
        ),
    )
    args = parser.parse_args(argv)

    try:
        te = load_te(args.spec)
    except Exception as e:
        print(f"error: failed to load {args.spec}: {e}", file=sys.stderr)
        return 2

    verifier_config: VerifierConfig | None = None
    if args.config is not None:
        try:
            verifier_config = VerifierConfig.from_yaml(args.config)
        except Exception as e:
            print(
                f"error: failed to load config {args.config}: {e}",
                file=sys.stderr,
            )
            return 2

    verdicts = None
    if args.verdicts is not None:
        try:
            verdicts = _load_verdicts(args.verdicts)
        except Exception as e:
            print(
                f"error: failed to load verdicts {args.verdicts}: {e}",
                file=sys.stderr,
            )
            return 2

    sim_config = SimulationConfig(
        n_runs=args.runs,
        horizon_periods=args.horizon,
        seed=args.seed,
        skip_non_fragile=not args.simulate_all,
    )

    report = run_simulation(
        te,
        verdicts=verdicts,
        config=sim_config,
        verifier_config=verifier_config,
    )

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(report.render_text())

    # Exit code: 1 if any simulated FM has P(violation) >= 0.5 — the
    # operational "fail before deployment" signal. 0 otherwise.
    for r in report.per_fm_results:
        if r.simulated and r.p_violation >= 0.5:
            return 1
    return 0


def _load_verdicts(path: Path):
    """Load ReachabilityVerdict list from JSON produced by
    ``te-verify --minimal --json``."""
    from verifier.minimal import ReachabilityVerdict

    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ReachabilityVerdict.model_validate(v) for v in raw]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
