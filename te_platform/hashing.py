## =============================================================================
## te_platform/hashing.py — canonical JSON and content addressing
## =============================================================================
## GUIDE STEP   1.2
## PURPOSE      Gives every spec and every verification result a fingerprint:
##              - spec_hash: identifies one exact spec;
##              - config_hash: identifies one exact VerifierConfig;
##              - verification_ref: identifies "this spec, verified by this
##                verifier version, with this config".
##              Equal inputs always give equal fingerprints, and any change
##              gives a different one.
## USED BY      service.py (attaches hashes to results), registry/facts.py
##              (recomputes the expected verification_ref, which the
##              precondition `verification_ref_matches_spec` then reads),
##              tools/verify_run.py (looks up a stored verification by its ref
##              before computing, phase 5.5), registry/pipeline.py (input hash
##              of the audit row), jobs/queue.py (content-based job ids),
##              jobs/report_task.py (verifier version in report provenance).
##              Reports print the refs computed here as provenance.
## DEPENDS ON   Python standard library only (json, hashlib).
## WHY          Architecture D5. Content addressing gives: caching (same input
##              → reuse the stored result), provenance (a report proves which
##              inputs produced it), and "verified first" enforcement even for
##              stateless MCP clients that keep no session.
## ACTIVATE     Uncomment; activate test_platform_hashing.py at the same time.
##              The property tests there (hypothesis) are the real
##              specification of this file.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: other files import them (te_platform/README.md,
## contracts table).
##
## Guide 1.2
## [ ] 1. Imports at the top: `hashlib` and `json` from the standard library,
##          | from importlib.metadata import version as _pkg_version
##        (reads the installed verifier version, used in step 6), `Any`
##        from typing, and `BaseModel` from pydantic.
## [ ] 2. A private helper `_to_plain(obj: Any) -> Any` that turns Pydantic
##        models, at any depth, into plain JSON data. Handle three cases and
##        recurse into the containers:
##          | if isinstance(obj, BaseModel):
##          |     return obj.model_dump(mode="json")
##        then dict (convert keys with str()), then list/tuple; anything
##        else is returned unchanged.
## [ ] 3. `canonical_json(obj: Any) -> bytes`: json.dumps of _to_plain(obj)
##        with sort_keys=True, separators=(",", ":"), ensure_ascii=False and
##        allow_nan=False, encoded as UTF-8. Each argument removes one way
##        that equal data could produce different bytes (or hide a NaN).
## [ ] 4. `sha256_hex(data: bytes) -> str`: one line with hashlib.sha256 and
##        .hexdigest(). It is public: the pipeline's audit log uses it.
## [ ] 5. `spec_hash(spec)` returns "spec:" + the sha256_hex of the
##        canonical JSON. `config_hash(config)` does the same with the prefix
##        "cfg:", hashing the fixed string "paper-defaults" when config is None.
## [ ] 6. `verifier_version() -> str` (with a one-line docstring): return
##        _pkg_version("token-economy-verifier"), the `name` in pyproject.toml.
## [ ] 7. `verification_ref(spec_hash_value, verifier_version_value,
##        config_hash_value) -> str`: join the three parts with the separator
##        "\x1f" (a control character that never occurs inside them) in an
##        f-string, hash the UTF-8 bytes and add the prefix "vref:".
## [ ] 8. Check: activate tests/platform_tests/test_platform_hashing.py, then
##          | uv run pytest tests/platform_tests/test_platform_hashing.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## _pkg_version reads the installed verifier version. It is part of
## verification_ref: a new verifier release may give different verdicts, so
## its results must not be confused with old ones. The package version does
## not change when the verifier's code is fixed, so verifier_version() adds a
## fingerprint of that code: a stored result never outlives the code that
## computed it.
import hashlib
import json
from functools import lru_cache
from importlib.metadata import version as _pkg_version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _to_plain(obj: Any) -> Any:
    """Convert Pydantic models (at any depth) to plain JSON-compatible data.

    mode="json" turns enums into strings, dates into ISO strings, etc., so
    the result only contains dict / list / str / int / float / bool / None.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> bytes:
    """Serialise `obj` in ONE fixed way, so equal data gives equal bytes.

    - sort_keys: {"a":1,"b":2} and {"b":2,"a":1} produce the same text;
    - separators without spaces: no formatting differences;
    - ensure_ascii=False + UTF-8: non-English text is kept as-is;
    - allow_nan=False: NaN/Infinity are not valid JSON and would make
      hashes unstable, so they are rejected loudly.
    Python's json writes floats with repr(), which round-trips exactly.
    """
    return json.dumps(
        _to_plain(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 of some bytes, as 64 hexadecimal characters.

    Public: the pipeline also uses it to fingerprint tool inputs for the
    audit log, and jobs/queue.py for content-based job ids.
    """
    return hashlib.sha256(data).hexdigest()


def spec_hash(spec: Any) -> str:
    """Fingerprint of a NORMALISED spec (see service.validate).

    Always hash the normalised form: two YAML files that differ only in
    formatting or in spelled-out defaults describe the same economy and
    must get the same hash.
    """
    return "spec:" + sha256_hex(canonical_json(spec))


def config_hash(config: Any | None) -> str:
    """Fingerprint of a VerifierConfig (None = paper defaults)."""
    plain = config if config is not None else "paper-defaults"
    return "cfg:" + sha256_hex(canonical_json(plain))


@lru_cache(maxsize=1)
def verifier_version() -> str:
    """Return the verifier's version: package version + fingerprint of its code.

    The fingerprint covers every Python file of the packages that decide a
    verdict (`schema`, `verifier`), path and content, in a fixed order.
    """
    digest = hashlib.sha256()
    for package in ("schema", "verifier"):
        # Located without importing them: this module stays standard-library only.
        spec = find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError(f"package {package!r} is not installed")
        root = Path(next(iter(spec.submodule_search_locations)))
        for path in sorted(root.rglob("*.py")):
            digest.update(f"{package}/{path.relative_to(root).as_posix()}".encode())
            digest.update(b"\x1f")
            digest.update(path.read_bytes())
            digest.update(b"\x1e")
    return f"{_pkg_version('token-economy-verifier')}+{digest.hexdigest()[:12]}"


def verification_ref(
    spec_hash_value: str, verifier_version_value: str, config_hash_value: str,
) -> str:
    """Fingerprint of one verification: spec + verifier version + config.

    The three parts are joined with a separator that cannot occur inside
    them, so ("ab", "c") and ("a", "bc") can never collide.
    """
    joined = f"{spec_hash_value}\x1f{verifier_version_value}\x1f{config_hash_value}"
    return "vref:" + sha256_hex(joined.encode("utf-8"))
