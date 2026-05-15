"""Reference ABM layer — consumes the verifier's minimal output and
adds likelihood + time-to-violation per failure mode.

Designed to complement the formal verifier:

  • Verifier (``verifier.minimal``) — proves reachability of violation
    and satisfaction. Universal-over-the-box facts.
  • ABM (this package)           — samples the box stochastically,
    evolves state per period, reports P(violation) and
    time-to-violation distributions.

The contract between layers is ``ReachabilityVerdict.safety_predicates``
(see ``verifier.safety_predicate``). The ABM evaluates each predicate
per period against simulated state; aggregate over runs gives the
quantitative answer.

Structure is cadCAD-shaped: state is a plain dict, per-period
evolution is a function ``step(state, params, t) → state_next``, and
predicates are pure functions of state. A future migration to real
cadCAD is a translation, not a rewrite — see ``docs/abm-bridge.md``.

Public API:

    from verifier.abm import run_simulation, SimulationConfig
    report = run_simulation(te, verdicts, SimulationConfig(n_runs=1000))
    print(report.render_text())
"""

from verifier.abm.cadcad_export import export_cadcad_config
from verifier.abm.engine import SimulationConfig, run_simulation
from verifier.abm.explore import ExploreReport, PeriodSnapshot, run_explore
from verifier.abm.report import FMSimulationResult, SimulationReport

__all__ = [
    "ExploreReport",
    "FMSimulationResult",
    "PeriodSnapshot",
    "SimulationConfig",
    "SimulationReport",
    "export_cadcad_config",
    "run_explore",
    "run_simulation",
]
