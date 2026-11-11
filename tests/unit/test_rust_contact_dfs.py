"""``rust.contact_dfs`` on puzzles whose assemblies can be listed by hand.

The three strips of ``support.documents`` stand in any order in the footprint
regime and in one order once they have roofs. Everything here follows from
that, and from two more puzzles that cannot be assembled at all.
"""

import math
from typing import Any

import pytest

from maxplus_solvers import (
    Pose,
    PuzzleInstance,
    Regime,
    SolverConfig,
    SolveResult,
    SolveStatus,
    solve,
    solvers,
)
from maxplus_solvers.metrics import SearchMetrics
from maxplus_solvers.validation import validate_solution
from support import assemblies, documents, geometry

DFS = "rust.contact_dfs"
SWITCHES = ("anchor", "cavity_pruning", "closure_pruning", "lookahead")
TIMES = {"wall_time_s", "cpu_time_s", "first_solution_s", "exhausted_s"}


def footprint() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.three_strips())


def relief() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.three_strips_relief())


def everything(mode: Regime = Regime.FOOTPRINT, **options: Any) -> SolverConfig:
    return SolverConfig(DFS, mode=mode, max_solutions=None, options=options)


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


def in_order(*order: int) -> list[list[tuple[float, float]]]:
    """The strips standing in the given order from the left wall, by hand."""
    polygons: list[list[tuple[float, float]]] = [[], [], []]
    x = -60.0
    for strip in order:
        width = documents.THREE_STRIP_WIDTHS[strip]
        polygons[strip] = [(x, -36.0), (x + width, -36.0), (x + width, 36.0), (x, 36.0)]
        x += width
    return polygons


ORDERS = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]


def same_set(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(sum(assemblies.same(x, y) for y in b) == 1 for x in a)


# --- what is found ------------------------------------------------------------------------


def test_every_order_of_the_strips_is_found_when_turns_are_counted() -> None:
    instance = footprint()
    result = solve(instance, everything(tray_rotations="all"), validate=True)
    assert result.status is SolveStatus.SOLVED and result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    assert same_set(placed(instance, result), [in_order(*order) for order in ORDERS])


def test_an_order_and_its_reverse_are_one_assembly() -> None:
    """The tray's half turn reverses an order: 6 orders, 3 assemblies."""
    instance = footprint()
    result = solve(instance, everything(), validate=True)
    assert result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    found = placed(instance, result)
    assert len(found) == 3
    half_turn = [assemblies.turned(a, math.pi, (0.0, 0.0)) for a in found]
    assert same_set(found + half_turn, [in_order(*order) for order in ORDERS])


def test_roofs_leave_one_order() -> None:
    """Worked out in ``documents.three_strips_relief``: the order the roofs were cut in."""
    instance = relief()
    result = solve(instance, everything(Regime.RELIEF), validate=True)
    assert result.status is SolveStatus.SOLVED and result.exhaustive
    (solution,) = result.solutions
    assert solution.valid is True
    assert solution.residuals is not None
    assert solution.residuals["roof_mismatch_mm"] == pytest.approx(0.0, abs=1e-9)
    (found,) = placed(instance, result)
    cut = in_order(0, 1, 2)
    assert assemblies.same(found, cut) or assemblies.same(
        found, assemblies.turned(cut, math.pi, (0.0, 0.0))
    )

    both = solve(instance, everything(Regime.RELIEF, tray_rotations="all"), validate=True)
    assert all(solution.valid for solution in both.solutions)
    assert same_set(placed(instance, both), [cut, assemblies.turned(cut, math.pi, (0.0, 0.0))])
    assert both.metrics["rejected_roof"] > 0


def test_the_roofs_are_hidden_in_footprint_mode() -> None:
    result = solve(relief(), everything(Regime.FOOTPRINT))
    assert result.regime is Regime.FOOTPRINT
    assert len(result.solutions) == 3
    assert result.metrics["rejected_roof"] == 0


def test_a_roof_out_of_step_leaves_no_assembly() -> None:
    """Lift the middle roof by 0.25 mm: every seam it could have now has a step."""
    doc = documents.three_strips_relief()
    doc["pieces"][1]["roof"]["z0"] += 0.25
    instance = PuzzleInstance.from_dict(doc)
    result = solve(instance, everything(Regime.RELIEF))
    assert result.status is SolveStatus.NO_SOLUTION_FOUND and result.exhaustive
    # The validator agrees about the assembly the roofs were cut from: it is 0.25 mm out.
    poses = {
        piece.id: Pose(centre, 0.0, 0.0)
        for piece, centre in zip(instance.pieces, documents.THREE_STRIP_CENTRES, strict=True)
    }
    report = validate_solution(instance, poses)
    assert report.worst_roof_mismatch_mm == pytest.approx(0.25, abs=1e-9)


@pytest.mark.parametrize(("tolerance", "found"), [(0.2, 0), (0.3, 1)])
def test_the_roof_tolerance_can_be_set_on_its_own(tolerance: float, found: int) -> None:
    """Lift the middle roof by 0.25 mm and say how large a step may be.

    The roofs then run 20 to 26, 26.25 to 35.25 and 35 to 50 mm, so the order they
    were cut in has a step of 0.25 mm at both seams: refused at 0.2 mm, allowed at
    0.3 mm. No other pair of edges comes within 0.3 mm: unturned, a seam joins a
    right height (26, 35.25, 50) to a left one (20, 26.25, 35), and a turned strip
    swaps its two, so the only near pairs are 26 with 26.25 and 35.25 with 35.
    That is the cut order and its half turn with the tray: one assembly.
    """
    doc = documents.three_strips_relief()
    doc["pieces"][1]["roof"]["z0"] += 0.25
    instance = PuzzleInstance.from_dict(doc)
    result = solve(instance, everything(Regime.RELIEF, roof_tolerance_mm=tolerance), validate=True)
    assert result.exhaustive
    assert len(result.solutions) == found
    for solution in result.solutions:
        assert solution.residuals is not None
        assert solution.residuals["roof_mismatch_mm"] <= tolerance + 1e-9
    if found:
        worst = min(s.residuals["roof_mismatch_mm"] for s in result.solutions if s.residuals)
        assert worst == pytest.approx(0.25, abs=1e-9)


def test_the_roof_tolerance_means_nothing_without_roofs() -> None:
    plain = solve(footprint(), everything())
    set_anyway = solve(footprint(), everything(roof_tolerance_mm=5.0))
    assert len(set_anyway.solutions) == len(plain.solutions) == 3


def test_strips_too_narrow_for_the_tray_are_refused_at_the_root() -> None:
    """24 + 36 + 48 mm of strips for 120 mm of tray: the areas cannot add up."""
    doc = documents.three_strips()
    doc["pieces"][2]["polygon"] = [[-24.0, -36.0], [24.0, -36.0], [24.0, 36.0], [-24.0, 36.0]]
    instance = PuzzleInstance.from_dict(doc)
    result = solve(instance, everything())
    assert result.status is SolveStatus.NO_SOLUTION_FOUND and result.exhaustive
    assert (result.metrics["nodes"], result.metrics["pruned_cavity"]) == (1, 1)
    assert "first_solution_s" not in result.metrics
    # Without the pruning the same answer takes placements to reach.
    plain = solve(instance, everything(cavity_pruning=False, closure_pruning=False))
    assert plain.status is SolveStatus.NO_SOLUTION_FOUND
    assert plain.metrics["nodes"] > 1 and plain.metrics["pruned_cavity"] == 0


# --- the switches change the work, not what is found --------------------------------------


@pytest.mark.parametrize("instance", [footprint(), relief()], ids=["footprint", "relief"])
def test_each_switch_can_be_turned_off_without_changing_what_is_found(
    instance: PuzzleInstance,
) -> None:
    on = dict.fromkeys(SWITCHES, True)
    reference = placed(instance, solve(instance, everything(instance.regime, **on)))
    assert reference
    counted = {
        "anchor": "pruned_anchor",
        "cavity_pruning": "pruned_cavity",
        "closure_pruning": "pruned_closure",
        "lookahead": "pruned_lookahead",
    }
    for switch in SWITCHES:
        result = solve(instance, everything(instance.regime, **{**on, switch: False}))
        assert result.exhaustive
        assert same_set(placed(instance, result), reference), switch
        assert result.metrics[counted[switch]] == 0, switch
    bare = solve(instance, everything(instance.regime, **dict.fromkeys(SWITCHES, False)))
    assert same_set(placed(instance, bare), reference)


def test_the_order_of_trying_changes_only_which_comes_first() -> None:
    instance = footprint()
    reference = placed(instance, solve(instance, everything()))
    firsts = []
    for order in ("matched-edges", "generated", "random"):
        result = solve(instance, everything(order=order))
        assert same_set(placed(instance, result), reference), order
    for seed in range(8):
        config = SolverConfig(DFS, max_solutions=None, seed=seed, options={"order": "random"})
        result, again = solve(instance, config), solve(instance, config)
        assert result.solutions == again.solutions, "a seed fixes the order"
        assert same_set(placed(instance, result), reference)
        firsts.append(placed(instance, result)[0])
    assert any(not assemblies.same(first, firsts[0]) for first in firsts), "8 seeds, one order"


def test_solutions_come_in_one_canonical_form() -> None:
    """Whatever the order they were found in, an assembly is returned with the same poses."""
    instance = footprint()
    reference = solve(instance, everything()).solutions
    other = solve(
        instance, SolverConfig(DFS, max_solutions=None, seed=3, options={"order": "random"})
    ).solutions
    for solution in other:
        twins = [
            r
            for r in reference
            if all(
                math.dist((r.poses[k].x, r.poses[k].y), (p.x, p.y)) <= 1e-9
                and abs(r.poses[k].theta - p.theta) <= 1e-9
                for k, p in solution.poses.items()
            )
        ]
        assert len(twins) == 1


def test_the_search_is_deterministic_and_ignores_the_seed_unless_asked() -> None:
    instance = footprint()
    first = solve(instance, everything())
    second = solve(instance, SolverConfig(DFS, max_solutions=None, seed=99))
    assert first.solutions == second.solutions
    assert {k: v for k, v in first.metrics.items() if k not in TIMES} == {
        k: v for k, v in second.metrics.items() if k not in TIMES
    }


# --- limits and statuses ------------------------------------------------------------------


def test_the_first_solution_is_returned_by_default_and_claims_no_more() -> None:
    result = solve(footprint(), SolverConfig(DFS))
    assert result.status is SolveStatus.SOLVED
    assert len(result.solutions) == 1 and not result.exhaustive
    assert "first_solution_s" in result.metrics
    assert "exhausted_s" not in result.metrics, "the search did not reach its end"


def test_the_two_times_are_reported_separately() -> None:
    result = solve(footprint(), everything())
    assert result.exhaustive
    first, end = result.metrics["first_solution_s"], result.metrics["exhausted_s"]
    assert 0.0 <= first <= end
    assert end == result.metrics["wall_time_s"]


def test_limits_interrupt() -> None:
    limited = solve(footprint(), everything(node_limit=1))
    assert limited.status is SolveStatus.INTERRUPTED and not limited.exhaustive
    assert limited.metrics["nodes"] == 1
    hurried = solve(footprint(), SolverConfig(DFS, max_solutions=None, time_limit_s=1e-12))
    assert hurried.status is SolveStatus.INTERRUPTED
    assert hurried.metrics["nodes"] == 0


# --- what a result records ----------------------------------------------------------------


def test_a_result_names_the_candidate_set_of_its_regime() -> None:
    spec = solvers.get(DFS)
    assert spec.regimes == frozenset({Regime.FOOTPRINT, Regime.RELIEF})
    flat = solve(footprint(), everything(lookahead=True))
    assert (flat.solver, flat.candidate_set) == (DFS, "corner-contact/1")
    assert flat.candidate_set == spec.candidate_sets[Regime.FOOTPRINT]
    assert flat.candidates_proven_complete is False
    assert flat.config is not None and flat.config.options == {"lookahead": True}
    assert flat.solver_version.count(".") == 2
    assert set(flat.metrics) == set(SearchMetrics().to_dict()) | {"first_solution_s", "exhausted_s"}
    roofed = solve(relief(), everything(Regime.RELIEF))
    assert roofed.candidate_set == "corner-contact-relief/1"
    assert roofed.instance_hash == relief().instance_hash()


def test_the_tropical_regime_is_not_offered() -> None:
    instance = PuzzleInstance.from_dict(documents.tropical_aware())
    with pytest.raises(ValueError, match="does not work in tropical-aware mode"):
        solve(instance, SolverConfig(DFS, mode=Regime.TROPICAL_AWARE))
    with pytest.raises(ValueError, match="does not work in the tropical-aware regime"):
        solvers.get(DFS).run(instance, SolverConfig(DFS, mode=Regime.TROPICAL_AWARE))


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"prune": True}, "unknown options prune"),
        ({"node_limit": 0}, "node_limit must be a positive integer"),
        ({"node_limit": True}, "node_limit must be a positive integer"),
        ({"lookahead": "yes"}, "lookahead must be true or false"),
        ({"anchor": 1}, "anchor must be true or false"),
        ({"order": "sideways"}, "order must be one of"),
        ({"tray_rotations": "twice"}, "tray_rotations must be one of"),
        ({"roof_tolerance_mm": 0}, "roof_tolerance_mm must be a positive number"),
        ({"roof_tolerance_mm": True}, "roof_tolerance_mm must be a positive number"),
        ({"roof_tolerance_mm": "wide"}, "roof_tolerance_mm must be a positive number"),
    ],
)
def test_options_it_does_not_understand_are_refused(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        solve(footprint(), SolverConfig(DFS, options=options))


def test_a_negative_seed_is_refused() -> None:
    with pytest.raises(ValueError, match="seed must not be negative"):
        solve(footprint(), SolverConfig(DFS, seed=-1))


def test_the_hand_made_assemblies_are_what_they_claim() -> None:
    """Guard the expectations above: each order tiles the tray, by the test oracle."""
    for order in ORDERS:
        polygons = in_order(*order)
        assert sum(geometry.area(p) for p in polygons) == pytest.approx(120.0 * 72.0, abs=1e-9)
        assert sorted(min(x for x, _ in p) for p in polygons)[0] == -60.0
