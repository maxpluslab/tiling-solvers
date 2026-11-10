"""``solve()``, the registry and ``python.contact_dfs`` on puzzles that can be solved by eye."""

import json
import math
from typing import Any

import pytest

from maxplus_solvers import (
    InstanceError,
    PuzzleInstance,
    Regime,
    SolverConfig,
    SolveResult,
    SolveStatus,
    available_solvers,
    solve,
    solvers,
)
from maxplus_solvers.metrics import SearchMetrics
from support import assemblies, documents

DFS = "python.contact_dfs"


def strips() -> PuzzleInstance:
    """Two identical 72 by 144 strips in a 144 square."""
    return PuzzleInstance.from_dict(documents.footprint())


def unfillable() -> PuzzleInstance:
    """The same with one strip narrowed to 60: 24 by 144 can never be covered."""
    doc = documents.footprint()
    doc["pieces"][1]["polygon"] = [[-30.0, -72.0], [30.0, -72.0], [30.0, 72.0], [-30.0, 72.0]]
    return PuzzleInstance.from_dict(doc)


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


def rectangle(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


UPRIGHT = [rectangle(-72, -72, 0, 72), rectangle(0, -72, 72, 72)]
ACROSS = [rectangle(-72, -72, 72, 0), rectangle(-72, 0, 72, 72)]


# --- the search ---------------------------------------------------------------------------


def test_two_identical_strips_stand_or_lie() -> None:
    """Side by side upright, or one above the other: 2 assemblies, the strips being alike."""
    instance = strips()
    result = solve(instance, SolverConfig(DFS, max_solutions=None))
    assert result.status is SolveStatus.SOLVED
    assert result.exhaustive
    found = placed(instance, result)
    assert len(found) == 2
    assert any(assemblies.same(a, UPRIGHT) for a in found)
    assert any(assemblies.same(a, ACROSS) for a in found)


def test_the_first_solution_is_returned_by_default_and_claims_no_more() -> None:
    result = solve(strips(), SolverConfig(DFS))
    assert len(result.solutions) == 1
    assert result.status is SolveStatus.SOLVED
    assert not result.exhaustive, "stopped at max_solutions: the rest was not searched"
    assert result.metrics["solutions"] == 1
    assert "first_solution_s" in result.metrics


def test_pieces_that_cannot_fill_the_target_give_no_solution_found() -> None:
    result = solve(unfillable(), SolverConfig(DFS, max_solutions=None))
    assert result.status is SolveStatus.NO_SOLUTION_FOUND
    assert result.exhaustive
    assert result.solutions == ()
    assert "first_solution_s" not in result.metrics
    assert result.metrics["backtracks"] > 0


def test_a_node_limit_interrupts_the_search() -> None:
    # One node is the root: it branches, and nothing is ever expanded below it.
    result = solve(unfillable(), SolverConfig(DFS, options={"node_limit": 1}))
    assert result.status is SolveStatus.INTERRUPTED
    assert not result.exhaustive
    assert result.metrics["nodes"] == 1
    # The same limit on a solvable puzzle: interrupted, not "no solution".
    assert solve(strips(), SolverConfig(DFS, options={"node_limit": 2})).status is (
        SolveStatus.INTERRUPTED
    )


def test_a_time_limit_too_short_to_start_interrupts() -> None:
    result = solve(strips(), SolverConfig(DFS, time_limit_s=1e-12))
    assert result.status is SolveStatus.INTERRUPTED
    assert result.metrics["nodes"] == 0


def test_the_search_is_deterministic() -> None:
    first = solve(strips(), SolverConfig(DFS, max_solutions=None))
    second = solve(strips(), SolverConfig(DFS, max_solutions=None, seed=99))
    assert first.solutions == second.solutions
    timed = {"wall_time_s", "cpu_time_s", "first_solution_s"}
    assert {k: v for k, v in first.metrics.items() if k not in timed} == {
        k: v for k, v in second.metrics.items() if k not in timed
    }


def test_the_metrics_of_the_strips_search_can_be_counted_by_hand() -> None:
    """Root: corner (-72, -72) offers the strip upright or lying, 2 placements, the twin skipped.

    Each leaves a 72 by 144 rectangle whose every corner takes the other strip
    one way only, and then all is covered. Nodes: root, 2 with one strip, 2
    complete. Placements: 4. No dead ends.
    """
    result = solve(strips(), SolverConfig(DFS, max_solutions=None))
    counted = {k: result.metrics[k] for k in ("nodes", "placements", "backtracks", "max_depth")}
    assert counted == {"nodes": 5, "placements": 4, "backtracks": 0, "max_depth": 2}
    generated = result.metrics["candidates_generated"]
    refused = result.metrics["rejected_outside"] + result.metrics["rejected_overlap"]
    assert generated > refused > 0


# --- what a result records ----------------------------------------------------------------


def test_a_result_says_what_produced_it_and_what_it_claims() -> None:
    instance = strips()
    config = SolverConfig(DFS, max_solutions=None, seed=7)
    result = solve(instance, config)
    assert result.solver == DFS
    assert result.regime is Regime.FOOTPRINT
    assert result.instance_hash == instance.instance_hash()
    assert result.config == config
    assert result.solver_version.count(".") == 2
    assert result.candidate_set == "corner-contact/1"
    # f64 with tolerances proves nothing about completeness.
    assert result.candidates_proven_complete is False
    assert set(result.metrics) == set(SearchMetrics().to_dict()) | {"first_solution_s"}
    assert SolveResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_solutions_are_not_validated_unless_asked() -> None:
    plain = solve(strips(), SolverConfig(DFS))
    assert plain.solutions[0].valid is None and plain.solutions[0].residuals is None
    checked = solve(strips(), SolverConfig(DFS), validate=True)
    solution = checked.solutions[0]
    assert solution.valid is True
    assert solution.residuals is not None
    assert solution.residuals["overlap_depth_mm"] == 0.0
    assert solution.residuals["uncovered_area_mm2"] == pytest.approx(0.0, abs=1e-6)
    assert solution.poses == plain.solutions[0].poses


# --- regimes ------------------------------------------------------------------------------


def test_a_relief_puzzle_is_solved_as_a_footprint_when_asked() -> None:
    relief = PuzzleInstance.from_dict(documents.relief())
    result = solve(relief, SolverConfig(DFS, mode=Regime.FOOTPRINT, max_solutions=None))
    assert result.regime is Regime.FOOTPRINT
    # The hash is that of what the solver saw, which has no roofs.
    assert result.instance_hash == relief.as_regime("footprint").instance_hash()
    assert result.instance_hash != relief.instance_hash()
    assert len(result.solutions) == 2


def test_a_mode_the_solver_does_not_have_is_refused() -> None:
    relief = PuzzleInstance.from_dict(documents.relief())
    with pytest.raises(ValueError, match="does not work in relief mode"):
        solve(relief, SolverConfig(DFS, mode=Regime.RELIEF))


def test_a_mode_with_more_than_the_instance_knows_is_refused() -> None:
    def everything(instance: PuzzleInstance, config: SolverConfig) -> SolveResult:
        raise AssertionError("the solver must not be reached")

    spec = solvers.SolverSpec(
        "test.everything", everything, frozenset(Regime), "none", "accepts any regime"
    )
    solvers.register(spec)
    try:
        with pytest.raises(InstanceError, match="cannot turn a footprint instance"):
            solve(strips(), SolverConfig("test.everything", mode=Regime.RELIEF))
    finally:
        del solvers._REGISTRY["test.everything"]


def test_the_solver_itself_refuses_roofs() -> None:
    """Reached directly, past ``solve()``, it still does not pretend to handle relief."""
    relief = PuzzleInstance.from_dict(documents.relief())
    with pytest.raises(ValueError, match="footprint regime"):
        solvers.get(DFS).run(relief, SolverConfig(DFS, mode=Regime.RELIEF))


# --- the registry and configuration -------------------------------------------------------


def test_the_registry_lists_the_prototype() -> None:
    assert DFS in available_solvers()
    assert available_solvers() == tuple(sorted(available_solvers()))
    spec = solvers.get(DFS)
    assert spec.regimes == frozenset({Regime.FOOTPRINT})
    assert spec.candidate_set and spec.description


def test_an_unknown_solver_is_refused_with_the_known_ones_named() -> None:
    with pytest.raises(ValueError, match=r"unknown solver 'rust\.nothing'.*python\.contact_dfs"):
        solve(strips(), SolverConfig("rust.nothing"))


def test_a_name_is_registered_once_and_needs_a_regime() -> None:
    spec = solvers.get(DFS)
    with pytest.raises(ValueError, match="already registered"):
        solvers.register(spec)
    with pytest.raises(ValueError, match="declares no regime"):
        solvers.register(solvers.SolverSpec("test.none", spec.run, frozenset(), "x", "x"))
    assert "test.none" not in available_solvers()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"frontier": "mrv"}, "unknown options frontier"),
        ({"node_limit": 0}, "node_limit must be a positive integer"),
        ({"node_limit": 2.5}, "node_limit must be a positive integer"),
        ({"node_limit": True}, "node_limit must be a positive integer"),
    ],
)
def test_bad_options_are_refused(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        solve(strips(), SolverConfig(DFS, options=options))


def test_absent_metrics_are_left_out_of_the_record() -> None:
    record = SearchMetrics(nodes=3, wall_time_s=0.5).to_dict()
    assert record["nodes"] == 3 and record["wall_time_s"] == 0.5
    assert "first_solution_s" not in record
    assert SearchMetrics(first_solution_s=0.25).to_dict()["first_solution_s"] == 0.25
    assert all(math.isfinite(value) for value in record.values())
