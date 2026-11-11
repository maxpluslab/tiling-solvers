"""``rust.contact_dfs``: the contact search, run entirely in Rust.

The search rule is the prototype's: branch on the convex corner of the uncovered
region that the fewest placements fill. ``docs/algorithms.md`` gives the rule,
the argument for it, and each of the things this solver adds:

* the relief regime, where a placement must also continue its neighbours' roofs;
* cavity pruning, closure pruning and an optional one-placement lookahead;
* the tray's rotations taken out, and solutions returned in canonical form;
* a choice of the order in which a node's candidates are tried.

Every addition can be switched off through ``SolverConfig.options``, so that
its effect can be measured. None of them changes what a whole search finds;
``tray_rotations`` changes how the same assemblies are counted.

This module converts the instance, makes one call into ``_native`` and converts
the answer back. The search does not return to Python until it is finished.
"""

import math
import time
from collections.abc import Mapping
from typing import Any

from maxplus_solvers import _native
from maxplus_solvers.metrics import SearchMetrics
from maxplus_solvers.models import (
    Pose,
    PuzzleInstance,
    Regime,
    Solution,
    SolverConfig,
    SolveResult,
    SolveStatus,
    TolerancePolicy,
)
from maxplus_solvers.solvers import SolverSpec

NAME = "rust.contact_dfs"
CANDIDATE_SETS = {
    # Vertex-at-corner contacts with one edge flush: the prototype's set.
    Regime.FOOTPRINT: "corner-contact/1",
    # The same, kept only where the roofs are continuous across every shared edge.
    Regime.RELIEF: "corner-contact-relief/1",
}

ORDERS = ("matched-edges", "generated", "random")
TRAY_ROTATIONS = ("once", "all")

# Option name -> default. The lookahead is off by default: it cuts the nodes visited but
# usually examines more states to do it. docs/algorithms.md has the measurements.
DEFAULTS: Mapping[str, Any] = {
    "node_limit": None,
    "tray_rotations": "once",
    "anchor": True,
    "cavity_pruning": True,
    "closure_pruning": True,
    "lookahead": False,
    "order": "matched-edges",
}


def _options(given: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"{NAME}: unknown options {', '.join(unknown)}")
    options = {**DEFAULTS, **given}
    limit = options["node_limit"]
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError(f"{NAME}: node_limit must be a positive integer")
    for switch in ("anchor", "cavity_pruning", "closure_pruning", "lookahead"):
        if not isinstance(options[switch], bool):
            raise ValueError(f"{NAME}: {switch} must be true or false")
    if options["order"] not in ORDERS:
        raise ValueError(f"{NAME}: order must be one of {', '.join(ORDERS)}")
    if options["tray_rotations"] not in TRAY_ROTATIONS:
        raise ValueError(f"{NAME}: tray_rotations must be one of {', '.join(TRAY_ROTATIONS)}")
    return options


def solve(instance: PuzzleInstance, config: SolverConfig) -> SolveResult:
    if instance.regime not in CANDIDATE_SETS:
        raise ValueError(f"{NAME} does not work in the {instance.regime} regime")
    options = _options(config.options)
    if config.seed < 0:
        raise ValueError(f"{NAME}: the seed must not be negative")

    policy = config.tolerances or TolerancePolicy.from_instance(instance)
    fit_mm = policy.contact_noise_mm
    if not fit_mm > 0:
        raise ValueError(f"{NAME}: the contact noise must be positive")
    # A turn by this angle moves a point one span away by the contact noise.
    fit_rad = fit_mm / instance.span_mm
    roofs = None
    height_mm = fit_mm
    if instance.regime is Regime.RELIEF:
        roofs = []
        for piece in instance.pieces:
            assert piece.roof is not None, "a relief instance has a roof on every piece"
            roofs.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
        # A point off by the contact noise changes a roof's height by that times its slope.
        steepest = max(math.hypot(gx, gy) for _, gx, gy in roofs)
        height_mm = fit_mm * max(1.0, steepest)

    cpu_started = time.process_time()
    outcome = _native.contact_dfs(
        instance.target,
        [piece.polygon for piece in instance.pieces],
        roofs,
        length_tol=fit_mm,
        angle_tol=fit_rad,
        slope_tol=fit_rad,
        height_tol=height_mm,
        max_solutions=config.max_solutions,
        time_limit_s=config.time_limit_s,
        node_limit=options["node_limit"],
        all_tray_rotations=options["tray_rotations"] == "all",
        anchor=options["anchor"],
        cavity_pruning=options["cavity_pruning"],
        closure_pruning=options["closure_pruning"],
        lookahead=options["lookahead"],
        order=options["order"],
        seed=config.seed,
    )
    cpu_time_s = time.process_time() - cpu_started

    ids = [piece.id for piece in instance.pieces]
    solutions = tuple(
        Solution({pid: Pose(*pose) for pid, pose in zip(ids, poses, strict=True)})
        for poses in outcome.solutions
    )
    metrics = SearchMetrics(
        nodes=outcome.nodes,
        backtracks=outcome.backtracks,
        placements=outcome.placements,
        max_depth=outcome.max_depth,
        candidates_generated=outcome.candidates_generated,
        rejected_outside=outcome.rejected_outside,
        rejected_overlap=outcome.rejected_overlap,
        rejected_roof=outcome.rejected_roof,
        pruned_cavity=outcome.pruned_cavity,
        pruned_closure=outcome.pruned_closure,
        pruned_anchor=outcome.pruned_anchor,
        pruned_lookahead=outcome.pruned_lookahead,
        duplicates=outcome.duplicates,
        solutions=len(solutions),
        wall_time_s=outcome.wall_time_s,
        cpu_time_s=cpu_time_s,
        first_solution_s=outcome.first_solution_s,
        exhausted_s=outcome.wall_time_s if outcome.exhausted else None,
    )
    if solutions:
        status = SolveStatus.SOLVED
    elif outcome.exhausted:
        status = SolveStatus.NO_SOLUTION_FOUND
    else:
        status = SolveStatus.INTERRUPTED
    return SolveResult(
        status=status,
        solver=NAME,
        regime=instance.regime,
        instance_hash=instance.instance_hash(),
        solutions=solutions,
        exhaustive=outcome.exhausted,
        # The arguments for the candidates and for the pruning rules are about exact
        # assemblies in exact arithmetic; this is f64 with tolerances.
        candidates_proven_complete=False,
        metrics=metrics.to_dict(),
        candidate_set=CANDIDATE_SETS[instance.regime],
        config=config,
        solver_version=_native.version(),
    )


SPEC = SolverSpec(
    name=NAME,
    run=solve,
    candidate_sets=CANDIDATE_SETS,
    description="Rust: depth-first search over corner contacts, with roofs and pruning",
)
