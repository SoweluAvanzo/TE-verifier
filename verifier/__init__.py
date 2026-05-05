"""Token Economy Verifier — Tier-1 Z3-based static checker.

Public API:
    from verifier import verify, Verdict, Report
    report = verify(te)  # te is a TokenEconomy
"""

from verifier.dispatcher import Report, Severity, Status, verify
from verifier.failure_modes.base import Counterexample, Verdict

__all__ = ["Counterexample", "Report", "Severity", "Status", "Verdict", "verify"]
