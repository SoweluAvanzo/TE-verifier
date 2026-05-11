"""Safety predicates — structured form of each FM's safety condition.

The verifier-to-ABM bridge. Each ``SafetyPredicate`` describes one
clause of an FM's safety condition in a form that a downstream
simulator (cadCAD, native Python ABM, anything else) can evaluate
per-period against a simulated state.

The contract:

* ``variable``    — a named scalar the ABM is expected to compute at
                    each period from its state. Example: ``rho``,
                    ``tau_bar``, ``effective_gini``.
* ``operator``    — the relation between the variable and the
                    threshold for the *safety* condition (not the
                    violation). Example: ``>=`` for ``rho``,
                    ``<=`` for ``effective_gini``.
* ``threshold``   — the numeric boundary. Worst-case where it
                    matters: for FM1 it's the lower bound on Q, for
                    FM3 it's the NFR1-adjusted ρ floor, etc.
* ``formula``     — short human-readable formula showing how to
                    compute ``variable`` from per-period state. Not
                    machine-parsed; documentation for the ABM author.
* ``inputs``      — list of state-variable names whose values the
                    ABM must surface each period to compute the
                    predicate. Lets cadCAD config authors know what
                    PSUBs need to write.
* ``paper_section`` — source citation in the DLT2026 paper.

These predicates are emitted by ``FailureMode.safety_predicates(te,
config, subject)`` and bundled into ``ReachabilityVerdict``. The ABM
layer consumes them as the formal contract: it must report the same
variables at the same threshold; it adds likelihood, time-to-
violation, per-agent breakdown on top.

This module is intentionally a *contract*, not a code generator. The
ABM author looks at the predicate, names the matching state variable
in their cadCAD/etc. config, and wires the comparison into a
state-update or policy function.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SafetyOperator = Literal[">=", "<=", ">", "<", "=="]


class SafetyPredicate(BaseModel):
    """One clause of a failure-mode safety condition, in a form
    a simulator can evaluate per-period."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    operator: SafetyOperator
    threshold: float

    # Short formula text — human-readable, not machine-parsed.
    formula: str | None = None

    # Names of state quantities the ABM must compute to evaluate this
    # predicate. The ABM author uses this list to scaffold the
    # per-period state in cadCAD / native ABM.
    inputs: list[str] = Field(default_factory=list)

    # Provenance.
    paper_section: str | None = None
    failure_mode: str | None = None  # FM id, set by the FM emitter
