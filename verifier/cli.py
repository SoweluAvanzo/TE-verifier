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
    args = parser.parse_args(argv)

    try:
        te = load_te(args.spec)
    except Exception as e:
        print(f"error: failed to load {args.spec}: {e}", file=sys.stderr)
        return 2

    config: VerifierConfig | None = None
    if args.config is not None:
        try:
            config = VerifierConfig.from_yaml(args.config)
        except Exception as e:
            print(f"error: failed to load config {args.config}: {e}", file=sys.stderr)
            return 2

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
