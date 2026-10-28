## =============================================================================
## tests/platform_tests/test_platform_verifier_version.py — stored results follow the code
## =============================================================================
## PURPOSE      verification_ref includes verifier_version(). The package
##              version alone never changed when the verifier was fixed, so a
##              live session kept being served a verdict computed by the old
##              code (Bitcoin FM3, 2026-10-25). The version now carries a
##              fingerprint of the verifier's code.
## USED BY      pytest. No database.
## =============================================================================

import hashlib
import re
from importlib.metadata import version
from pathlib import Path

import schema
import verifier
from te_platform import hashing


def test_version_is_package_version_plus_code_fingerprint() -> None:
    v = hashing.verifier_version()
    assert re.fullmatch(re.escape(version("token-economy-verifier")) + r"\+[0-9a-f]{12}", v)


def test_fingerprint_covers_every_verifier_and_schema_file() -> None:
    digest = hashlib.sha256()
    for package in (schema, verifier):
        root = Path(package.__file__).parent
        for path in sorted(root.rglob("*.py")):
            digest.update(f"{package.__name__}/{path.relative_to(root).as_posix()}".encode())
            digest.update(b"\x1f")
            digest.update(path.read_bytes())
            digest.update(b"\x1e")
    assert hashing.verifier_version().endswith("+" + digest.hexdigest()[:12])
    assert any(Path(verifier.__file__).parent.rglob("fm3_burn_emission.py"))
