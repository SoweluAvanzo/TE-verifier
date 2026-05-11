"""Command-line entry point.

Usage:
    te-verify path/to/te.yaml
    te-verify path/to/te.yaml --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from schema import load_te
from verifier.config import VerifierConfig
from verifier.dispatcher import verify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="te-verify",
        description=(
            "Verify a token economy specification (TE-IR YAML) against the "
            "six failure-mode conditions from the DLT2026 paper."
        ),
    )
    parser.add_argument(
        "spec",
        type=Path,
        help="Path to a TE-IR YAML file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Exit non-zero when severity is warn (inconclusive checks).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a YAML file with VerifierConfig overrides "
            "(thresholds, calibration tables). When omitted, "
            "paper-default values are used."
        ),
    )
    parser.add_argument(
        "--emit-v2",
        action="store_true",
        help=(
            "Load the v1 spec, migrate it to the v2 IR via "
            "schema.v2.from_v1, validate, and emit the resulting v2 IR "
            "as YAML on stdout. The live verifier path is skipped — "
            "this is a migration-inspection mode for Phase A of the "
            "v2 rollout."
        ),
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help=(
            "Emit the minimal reachability output — one row per FM "
            "with violation_reachable, satisfaction_reachable, "
            "structural_status (sound/fragile/broken/not_applicable/"
            "inconclusive), threshold, and structured safety_predicates "
            "ready for ABM (cadCAD-class simulator) consumption. Pair "
            "with --json for the JSON form. See docs/abm-bridge.md."
        ),
    )
    args = parser.parse_args(argv)

    try:
        te = load_te(args.spec)
    except Exception as e:
        print(f"error: failed to load {args.spec}: {e}", file=sys.stderr)
        return 2

    if args.emit_v2:
        # Migration-inspection mode: convert v1 → v2 and emit YAML.
        # Doesn't touch the v1 verification path; lets a user diff the
        # input against the migrated form before committing to a native
        # v2 YAML.
        try:
            from schema import v2 as _v2

            te_v2 = _v2.from_v1(te)
        except NotImplementedError as e:
            print(
                f"error: migration not yet supported for this IR: {e}",
                file=sys.stderr,
            )
            return 2
        except Exception as e:
            print(f"error: v2 migration failed: {e}", file=sys.stderr)
            return 2
        import yaml as _yaml

        print(
            _yaml.safe_dump(
                te_v2.model_dump(mode="json", exclude_none=True),
                sort_keys=False,
            )
        )
        return 0

    config: VerifierConfig | None = None
    if args.config is not None:
        try:
            config = VerifierConfig.from_yaml(args.config)
        except Exception as e:
            print(f"error: failed to load config {args.config}: {e}", file=sys.stderr)
            return 2

    if args.minimal:
        # Minimal mode: emit only reachability facts + structured
        # safety_predicates. The ABM (cadCAD or other) consumes this
        # contract directly. No NFR reframing, no narrative,
        # no recommendations beyond a single threshold per FM.
        from verifier.minimal import minimal_report_text, minimal_verdicts

        verdicts = minimal_verdicts(te, config=config)
        if args.json:
            import json

            payload = [v.model_dump(mode="json") for v in verdicts]
            print(json.dumps(payload, indent=2))
        else:
            print(minimal_report_text(verdicts))
        # Exit code: non-zero when any verdict is BROKEN — the
        # design has no parameter assignment that satisfies the FM,
        # which is the strongest signal pre-deployment.
        if any(v.structural_status.value == "broken" for v in verdicts):
            return 1
        return 0

    report = verify(te, config=config)

    if args.json:
        # Use Pydantic's serializer so enums render correctly
        print(report.model_dump_json(indent=2))
    else:
        print(report.render_text())

    if report.severity.value == "fail":
        return 1
    if args.fail_on_warn and report.severity.value == "warn":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
