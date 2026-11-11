"""``cp_sat.placements``: choose an assembly from a list of placements, with CP-SAT.

The solver knows no geometry. Rust hands it a finite list of placements and
what they exclude among themselves, and it chooses: one Boolean per placement,
as many placements of each class of congruent pieces as the class has members,
at most one from every set that overlaps at a point or disagrees about a roof.
``docs/algorithms.md`` says where the list comes from and why a choice with no
conflict is an assembly.

The list is the placements the corner search of ``rust.contact_dfs`` reaches,
so building it costs one whole search, and this solver finds nothing that
search does not. What it adds is a second route to the same assemblies, through
a solver that shares none of the search's bookkeeping, and a measure of how
hard the choice is once the geometry has been taken out of it.

``INFEASIBLE`` here means that the listed placements hold no assembly. It says
nothing about placements that were not listed.

This module makes one call into ``_native``, for the list. OR-Tools is an
optional extra and is imported only when the solver runs.
"""

import math
import time
from collections.abc import Mapping, Sequence
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

NAME = "cp_sat.placements"
CANDIDATE_SETS = {
    # The placements the corner search puts down anywhere in its tree.
    Regime.FOOTPRINT: "corner-contact-reachable/1",
    # The same for the search that also asks roofs to continue.
    Regime.RELIEF: "corner-contact-relief-reachable/1",
}

TRAY_ROTATIONS = ("once", "all")

# Option name -> default. The first group shapes the search that lists the placements,
# and means there what it means for rust.contact_dfs; ``coverage`` and ``targeted_probes``
# shape the model. Targeted probes are off by default: they turn nearly every listed pair
# into a clique and CP-SAT is slower for it. docs/algorithms.md has the measurements.
DEFAULTS: Mapping[str, Any] = {
    "node_limit": None,
    "max_placements": None,
    "tray_rotations": "once",
    "anchor": True,
    "cavity_pruning": True,
    "closure_pruning": True,
    "coverage": True,
    "targeted_probes": False,
}


def _options(given: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"{NAME}: unknown options {', '.join(unknown)}")
    options = {**DEFAULTS, **given}
    for limit in ("node_limit", "max_placements"):
        value = options[limit]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"{NAME}: {limit} must be a positive integer")
    for switch in ("anchor", "cavity_pruning", "closure_pruning", "coverage", "targeted_probes"):
        if not isinstance(options[switch], bool):
            raise ValueError(f"{NAME}: {switch} must be true or false")
    if options["tray_rotations"] not in TRAY_ROTATIONS:
        raise ValueError(f"{NAME}: tray_rotations must be one of {', '.join(TRAY_ROTATIONS)}")
    return options


def _form(choice: tuple[int, ...], turned: Sequence[Sequence[int | None]]) -> tuple[int, ...]:
    """One name for a choice and for its images under the tray's turns: the least of them.

    A turn that takes some chosen placement to one that is not listed gives an
    image nobody can choose, and is left out.
    """
    form = choice
    for images in turned:
        image = [images[placement] for placement in choice]
        if all(index is not None for index in image):
            form = min(form, tuple(sorted(index for index in image if index is not None)))
    return form


def solve(instance: PuzzleInstance, config: SolverConfig) -> SolveResult:
    if instance.regime not in CANDIDATE_SETS:
        raise ValueError(f"{NAME} does not work in the {instance.regime} regime")
    options = _options(config.options)
    if config.seed < 0:
        raise ValueError(f"{NAME}: the seed must not be negative")
    try:
        from ortools.sat.python import cp_model
    except ImportError as error:
        raise ImportError(
            f"{NAME} needs OR-Tools: install maxplus-solvers with the 'cp-sat' extra"
        ) from error

    policy = config.tolerances or TolerancePolicy.from_instance(instance)
    fit_mm = policy.contact_noise_mm
    if not fit_mm > 0:
        raise ValueError(f"{NAME}: the contact noise must be positive")
    # The tolerances of rust.contact_dfs, so that the two list and judge alike.
    fit_rad = fit_mm / instance.span_mm
    roofs = None
    height_mm = fit_mm
    if instance.regime is Regime.RELIEF:
        roofs = []
        for piece in instance.pieces:
            assert piece.roof is not None, "a relief instance has a roof on every piece"
            roofs.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
        steepest = max(math.hypot(gx, gy) for _, gx, gy in roofs)
        height_mm = fit_mm * max(1.0, steepest)

    started = time.perf_counter()
    cpu_started = time.process_time()
    listed = _native.placement_model(
        instance.target,
        [piece.polygon for piece in instance.pieces],
        roofs,
        length_tol=fit_mm,
        angle_tol=fit_rad,
        slope_tol=fit_rad,
        height_tol=height_mm,
        time_limit_s=config.time_limit_s,
        node_limit=options["node_limit"],
        max_placements=options["max_placements"],
        all_tray_rotations=options["tray_rotations"] == "all",
        anchor=options["anchor"],
        cavity_pruning=options["cavity_pruning"],
        closure_pruning=options["closure_pruning"],
        targeted_probes=options["targeted_probes"],
    )
    classes = listed.classes
    of_class: list[list[int]] = [[] for _ in classes]
    for placement, index in enumerate(listed.placement_class):
        of_class[index].append(placement)

    model_started = time.perf_counter()
    model = cp_model.CpModel()
    chosen = [model.new_bool_var(f"p{index}") for index in range(len(listed.placement_class))]
    for members, placements in zip(classes, of_class, strict=True):
        # As many placements as the class has pieces. A class nothing was listed for
        # asks for a sum of nothing to be positive, and the model is infeasible.
        model.add(sum(chosen[index] for index in placements) == len(members))
    for clique in listed.cliques:
        model.add_at_most_one(chosen[index] for index in clique)
    for first, second in listed.pairs:
        model.add_at_most_one((chosen[first], chosen[second]))
    if not listed.areas_add_up:
        # Pieces that cannot cover the target: a choice with no conflict would not be
        # an assembly, so none is allowed.
        model.add_bool_or([])
    covers = listed.covers if options["coverage"] else []
    for cover in covers:
        # A point of the target that no listed placement reaches cannot be covered.
        model.add_bool_or(chosen[index] for index in cover)

    turned = listed.turned if options["tray_rotations"] == "once" else []
    limit = config.max_solutions

    class Collect(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.choices: dict[tuple[int, ...], tuple[int, ...]] = {}
            self.duplicates = 0
            self.first_s: float | None = None

        def on_solution_callback(self) -> None:
            choice = tuple(index for index, var in enumerate(chosen) if self.boolean_value(var))
            form = _form(choice, turned)
            if form in self.choices:
                self.duplicates += 1
                return
            self.choices[form] = choice
            if self.first_s is None:
                self.first_s = time.perf_counter() - started
            if limit is not None and len(self.choices) >= limit:
                self.stop_search()

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    # One worker, so that a run can be repeated and its counts mean something.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = config.seed
    model_s = time.perf_counter() - model_started
    collect = Collect()
    remaining = None
    if config.time_limit_s is not None:
        remaining = config.time_limit_s - (time.perf_counter() - started)
    ran = remaining is None or remaining > 0
    if ran:
        if remaining is not None:
            solver.parameters.max_time_in_seconds = remaining
        status = solver.solve(model, collect)
        # With every solution asked for, OPTIMAL says they have all been given.
        finished = status in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
    else:
        finished = False
    exhaustive = listed.exhausted and finished
    wall_time_s = time.perf_counter() - started

    ids = [piece.id for piece in instance.pieces]
    solutions = []
    for choice in collect.choices.values():
        poses: dict[str, Pose] = {}
        for members, placements in zip(classes, of_class, strict=True):
            taken = [index for index in placements if index in set(choice)]
            for seat, (piece, placement) in enumerate(zip(members, taken, strict=True)):
                poses[ids[piece]] = Pose(*listed.placement_poses[placement][seat])
        solutions.append(Solution({pid: poses[pid] for pid in ids}))

    metrics = SearchMetrics(
        # The search that listed the placements.
        nodes=listed.nodes,
        backtracks=listed.backtracks,
        placements=listed.placements,
        max_depth=listed.max_depth,
        candidates_generated=listed.candidates_generated,
        rejected_outside=listed.rejected_outside,
        rejected_overlap=listed.rejected_overlap,
        rejected_roof=listed.rejected_roof,
        pruned_cavity=listed.pruned_cavity,
        pruned_closure=listed.pruned_closure,
        pruned_anchor=listed.pruned_anchor,
        duplicates=collect.duplicates,
        solutions=len(solutions),
        wall_time_s=wall_time_s,
        cpu_time_s=time.process_time() - cpu_started,
        first_solution_s=collect.first_s,
        exhausted_s=wall_time_s if exhaustive else None,
        # The model, and the choosing.
        model_placements=len(chosen),
        model_cliques=len(listed.cliques),
        model_pairs=len(listed.pairs),
        model_covers=len(covers),
        sat_branches=solver.num_branches if ran else 0,
        sat_conflicts=solver.num_conflicts if ran else 0,
        listing_s=listed.search_time_s + listed.conflict_time_s,
        model_s=model_s,
        sat_s=solver.wall_time if ran else 0.0,
    )
    if solutions:
        outcome = SolveStatus.SOLVED
    elif exhaustive:
        outcome = SolveStatus.NO_SOLUTION_FOUND
    else:
        outcome = SolveStatus.INTERRUPTED
    return SolveResult(
        status=outcome,
        solver=NAME,
        regime=instance.regime,
        instance_hash=instance.instance_hash(),
        solutions=tuple(solutions),
        exhaustive=exhaustive,
        # The list is what one search reached, in f64 with tolerances. Nothing is proven
        # about placements outside it.
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
    description="CP-SAT: choose among the placements the Rust contact search reaches",
)
