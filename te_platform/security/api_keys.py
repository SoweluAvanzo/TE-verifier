## =============================================================================
## te_platform/security/api_keys.py — create and hash API keys
## =============================================================================
## GUIDE STEP   4.2 (API keys), 9.0 (personal access codes for the web login)
## PURPOSE      generate_api_key() makes a new random key and returns it
##              together with its hash; hash_api_key() computes the hash of a
##              key presented by a client. The plain key is shown ONCE to the
##              person creating it (cli.py) and never stored anywhere; only the
##              hash is stored (Settings.api_key_hashes in phase 4, the
##              api_keys table from phase 5).
## USED BY      cli.py (`te-platform keys create`, and `users create` from
##              9.0), mcp_server/auth.py (hashes the key of every incoming
##              request), the web login (guide 9.0: the typed access code
##              is hashed with hash_api_key and looked up by its hash),
##              agent service setup (its own service key,
##              Settings.agent_mcp_api_key).
## DEPENDS ON   Python standard library only (secrets, hashlib).
## WHY          Guide 4.2 and §2.2: even someone who steals the database or the
##              .env file cannot use the keys.
## WHY SHA-256 (A FAST HASH) IS RIGHT HERE
##              Passwords must be hashed with deliberately SLOW functions
##              (bcrypt, argon2), because people choose guessable passwords and
##              an attacker with the hashes can try billions of guesses. Our keys
##              are not chosen by people: they are 32 random bytes (256 bits)
##              from the operating system's secure random generator. There is
##              nothing to guess — trying all possibilities is impossible at any
##              speed — so a fast hash is safe, and keeps every request cheap.
## ACTIVATE     4.2: uncomment the file; generate_access_code() is commented
##              twice: toggle it again at guide 9.0. Tests in
##              test_platform_security.py (keys are unique and carry the
##              prefix, the hash matches and does not contain the key).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: cli.py and mcp_server/auth.py import them.
##
## Guide 4.2
## [ ] 1. Imports at the top: `hashlib` and `secrets` (standard library).
## [ ] 2. The constant KEY_PREFIX = "te_" (the `##` note above it in the
##        SOLUTION says why keys carry a prefix).
## [ ] 3. `hash_api_key(plain: str) -> str`: SHA-256 of the UTF-8 bytes,
##        as hexadecimal text (one line, like sha256_hex in hashing.py).
## [ ] 4. `generate_api_key() -> tuple[str, str]` returns (plain, hash):
##          | plain = KEY_PREFIX + secrets.token_urlsafe(32)
##        then return plain together with hash_api_key(plain). Never use
##        the `random` module for secrets.
## [ ] 5. Check: activate the guide 4.2 block of
##        tests/platform_tests/test_platform_security.py, then
##          | uv run pytest tests/platform_tests/test_platform_security.py -q
##          | uv run mypy te_platform
##
## Guide 9.0
## [ ] 6. `generate_access_code() -> tuple[str, str]`: the same as
##        generate_api_key, with the prefix "tu_" (a person's login code).
## [ ] 7. Check: activate the guide 9.0 test of test_platform_security.py
##        and run the step 5 commands.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import hashlib
import secrets

## A recognisable prefix: makes leaked keys easy to spot in logs or code
## (GitHub secret scanning can be taught to look for "te_..."), and makes it
## obvious to a human which system a key belongs to.
KEY_PREFIX = "te_"


def hash_api_key(plain: str) -> str:
    """Return the SHA-256 of the key, as 64 hexadecimal characters."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Return (plain_key, key_hash).

    secrets.token_urlsafe(32): 32 bytes from the OS's cryptographically
    secure generator, encoded with URL-safe characters (so the key can be
    pasted into headers and config files without escaping). Never use the
    `random` module for secrets: it is predictable.
    """
    plain = KEY_PREFIX + secrets.token_urlsafe(32)
    return plain, hash_api_key(plain)


## Guide 9.0: a PERSON's login code (agent/auth.py, `te-platform users
## create`). Same construction and the same reasons as API keys above; a
## different prefix ("tu_" = user) so a leaked secret is recognisable at a
## glance.
def generate_access_code() -> tuple[str, str]:
    """Return (plain_code, code_hash) for a person's web login."""
    plain = "tu_" + secrets.token_urlsafe(32)
    return plain, hash_api_key(plain)
