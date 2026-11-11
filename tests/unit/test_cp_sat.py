"""``cp_sat.placements`` on puzzles whose assemblies can be listed by hand.

The same three strips as ``test_rust_contact_dfs.py``: any order as footprints,
one order under their roofs. The expectations are the hand-made assemblies and
the strips' arithmetic, never the search the solver's list comes from.
"""

import math
import sys
from typing import Any

import pytest

from maxplus_solvers import (
    PuzzleInstance,
    Regime,
    SolverConfig,
    SolveResult,
    SolveStatus,
    solve,
    solvers,
)
from maxplus_solvers.solvers import cp_sat
from support import assemblies, documents, geometry

CP_SAT = "cp_sat.placements"
TIMES = {
    "wall_time_s",
    "cpu_time_s",
    "first_solution_s",
    "exhausted_s",
    "listing_s",
    "model_s",
    "sat_s",
}
ORDERS = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]


def footprint() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.three_strips())


def relief() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.three_strips_relief())


def everything(mode: Regime = Regime.FOOTPRINT, **options: Any) -> SolverConfig:
    return SolverConfig(CP_SAT, mode=mode, max_solutions=None, options=options)


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


def same_set(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(sum(assemblies.same(x, y) for y in b) == 1 for x in a)


def same_up_to_turns(instance: PuzzleInstance, a: list[Any], b: list[Any]) -> bool:
    """The same assemblies, each allowed to be a turn of its counterpart with the tray.

    Counting turns once, a solver returns one member of each family, and which
    one depends on its options.
    """
    centre = geometry.centroid(instance.target)
    turns = assemblies.tray_turns(instance.target)

    def alike(x: Any, y: Any) -> bool:
        return any(assemblies.same(assemblies.turned(x, turn, centre), y) for turn in turns)

    return len(a) == len(b) and all(sum(alike(x, y) for y in b) == 1 for x in a)


# --- what is found ------------------------------------------------------------------------


def test_every_order_of_the_strips_is_chosen_when_turns_are_counted() -> None:
    instance = footprint()
    result = solve(instance, everything(tray_rotations="all"), validate=True)
    assert result.status is SolveStatus.SOLVED and result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    assert same_set(placed(instance, result), [in_order(*order) for order in ORDERS])
    # By hand: a strip's left side stands at a sum of widths of strips to its left,
    # four places each. The list is longer than those twelve: the search also lays
    # strips on their sides, which fits the tray and is part of no assembly.
    assert result.metrics["model_placements"] >= 12
    assert result.metrics["duplicates"] == 0


@pytest.mark.parametrize("anchor", [True, False])
def test_an_order_and_its_reverse_are_one_assembly(anchor: bool) -> None:
    """The tray's half turn reverses an order: 6 orders, 3 assemblies.

    With the anchor the list holds one of each pair to begin with. Without it
    the list holds every placement, the chooser finds all six orders, and
    three of them are recognised as turns of the others.
    """
    instance = footprint()
    result = solve(instance, everything(anchor=anchor), validate=True)
    assert result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    found = placed(instance, result)
    assert len(found) == 3
    half_turn = [assemblies.turned(a, math.pi, (0.0, 0.0)) for a in found]
    assert same_set(found + half_turn, [in_order(*order) for order in ORDERS])
    if not anchor:
        assert result.metrics["duplicates"] == 3


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
    turned = assemblies.turned(cut, math.pi, (0.0, 0.0))
    assert assemblies.same(found, cut) or assemblies.same(found, turned)

    both = solve(instance, everything(Regime.RELIEF, tray_rotations="all"), validate=True)
    assert all(solution.valid for solution in both.solutions)
    assert same_set(placed(instance, both), [cut, turned])


def test_the_roofs_are_hidden_in_footprint_mode() -> None:
    result = solve(relief(), everything(Regime.FOOTPRINT))
    assert result.regime is Regime.FOOTPRINT
    assert len(result.solutions) == 3


def test_a_roof_out_of_step_leaves_no_assembly() -> None:
    """Lift the middle roof by 0.25 mm: every seam it could have now has a step."""
    doc = documents.three_strips_relief()
    doc["pieces"][1]["roof"]["z0"] += 0.25
    result = solve(PuzzleInstance.from_dict(doc), everything(Regime.RELIEF))
    assert result.status is SolveStatus.NO_SOLUTION_FOUND and result.exhaustive
    assert not result.candidates_proven_complete


@pytest.mark.parametrize("coverage", [True, False])
@pytest.mark.parametrize("pruning", [True, False])
def test_strips_too_narrow_for_the_tray_are_never_an_assembly(
    coverage: bool, pruning: bool
) -> None:
    """24 + 36 + 48 mm of strips for 120 mm of tray.

    With the pruning the listing search stops at its root and lists nothing.
    Without it, strips are listed that stand clear of one another: 24 at the
    left wall, 36 beside it, 48 at the right wall, 12 mm of tray bare. Nothing
    excludes that choice pair by pair, so the model must refuse it by other
    means, with the coverage constraints or without them.
    """
    doc = documents.three_strips()
    doc["pieces"][2]["polygon"] = [[-24.0, -36.0], [24.0, -36.0], [24.0, 36.0], [-24.0, 36.0]]
    instance = PuzzleInstance.from_dict(doc)
    result = solve(
        instance,
        everything(coverage=coverage, cavity_pruning=pruning, closure_pruning=pruning),
    )
    assert result.status is SolveStatus.NO_SOLUTION_FOUND and result.exhaustive
    assert result.solutions == ()
    assert (result.metrics["model_placements"] == 0) is pruning


# --- the switches change the work, not what is found --------------------------------------


@pytest.mark.parametrize("instance", [footprint(), relief()], ids=["footprint", "relief"])
def test_each_switch_can_be_turned_off_without_changing_what_is_found(
    instance: PuzzleInstance,
) -> None:
    switches = [name for name, default in cp_sat.DEFAULTS.items() if isinstance(default, bool)]
    assert sorted(switches) == [
        "anchor",
        "cavity_pruning",
        "closure_pruning",
        "coverage",
        "targeted_probes",
    ]
    reference = placed(instance, solve(instance, everything(instance.regime)))
    assert reference
    # Each switch moved from its default, alone and then all together.
    flipped = {switch: not cp_sat.DEFAULTS[switch] for switch in switches}
    for switch in switches:
        result = solve(instance, everything(instance.regime, **{switch: flipped[switch]}))
        assert result.exhaustive, switch
        assert same_up_to_turns(instance, placed(instance, result), reference), switch
    other = solve(instance, everything(instance.regime, **flipped))
    assert same_up_to_turns(instance, placed(instance, other), reference)
    assert other.metrics["model_covers"] == 0


def test_coverage_adds_constraints_and_no_placements() -> None:
    instance = footprint()
    with_covers = solve(instance, everything()).metrics
    without = solve(instance, everything(coverage=False)).metrics
    assert with_covers["model_covers"] > 0 and without["model_covers"] == 0
    for count in ("model_placements", "model_cliques", "model_pairs", "nodes"):
        assert with_covers[count] == without[count], count


def test_the_solver_is_deterministic() -> None:
    instance = footprint()
    first, second = solve(instance, everything()), solve(instance, everything())
    assert first.solutions == second.solutions
    assert {k: v for k, v in first.metrics.items() if k not in TIMES} == {
        k: v for k, v in second.metrics.items() if k not in TIMES
    }


# --- limits and statuses ------------------------------------------------------------------


def test_the_first_solution_is_returned_by_default_and_claims_no_more() -> None:
    result = solve(footprint(), SolverConfig(CP_SAT), validate=True)
    assert result.status is SolveStatus.SOLVED
    (solution,) = result.solutions
    assert solution.valid is True
    assert not result.exhaustive
    assert "first_solution_s" in result.metrics
    assert "exhausted_s" not in result.metrics


def test_two_of_three_can_be_asked_for() -> None:
    config = SolverConfig(CP_SAT, max_solutions=2)
    result = solve(footprint(), config, validate=True)
    assert len(result.solutions) == 2 and not result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    first, second = placed(footprint(), result)
    assert not assemblies.same(first, second)


def test_a_list_cut_short_is_not_exhaustive_whatever_is_chosen_from_it() -> None:
    """Three of the placements cannot hold all three assemblies, and the result says so."""
    cut = solve(footprint(), everything(max_placements=3), validate=True)
    assert not cut.exhaustive
    whole = solve(footprint(), everything()).metrics["model_placements"]
    # The limit is looked at between nodes, so a node's last placement may pass it.
    assert 3 <= cut.metrics["model_placements"] < whole
    assert len(cut.solutions) < 3
    assert all(solution.valid for solution in cut.solutions)
    assert cut.status is (SolveStatus.SOLVED if cut.solutions else SolveStatus.INTERRUPTED)

    one_node = solve(footprint(), everything(node_limit=1))
    assert one_node.status is SolveStatus.INTERRUPTED and not one_node.exhaustive
    assert one_node.metrics["nodes"] == 1 and one_node.metrics["model_placements"] < whole

    hurried = solve(footprint(), SolverConfig(CP_SAT, max_solutions=None, time_limit_s=1e-12))
    assert hurried.status is SolveStatus.INTERRUPTED and not hurried.exhaustive
    assert hurried.metrics["sat_branches"] == 0


# --- what a result records ----------------------------------------------------------------


def test_a_result_names_the_candidate_set_of_its_regime() -> None:
    spec = solvers.get(CP_SAT)
    assert spec.regimes == frozenset({Regime.FOOTPRINT, Regime.RELIEF})
    flat = solve(footprint(), everything(coverage=False))
    assert (flat.solver, flat.candidate_set) == (CP_SAT, "corner-contact-reachable/1")
    assert flat.candidate_set == spec.candidate_sets[Regime.FOOTPRINT]
    assert flat.candidates_proven_complete is False
    assert flat.config is not None and flat.config.options == {"coverage": False}
    assert flat.solver_version.count(".") == 2
    assert flat.metrics["solutions"] == 3
    for name in ("model_placements", "model_cliques", "model_pairs", "sat_branches", "sat_s"):
        assert name in flat.metrics
    roofed = solve(relief(), everything(Regime.RELIEF))
    assert roofed.candidate_set == "corner-contact-relief-reachable/1"
    assert roofed.instance_hash == relief().instance_hash()


def test_the_other_solvers_do_not_report_a_model() -> None:
    result = solve(footprint(), SolverConfig("rust.contact_dfs"))
    assert not [name for name in result.metrics if name.startswith(("model_", "sat_"))]


def test_the_tropical_regime_is_not_offered() -> None:
    instance = PuzzleInstance.from_dict(documents.tropical_aware())
    with pytest.raises(ValueError, match="does not work in tropical-aware mode"):
        solve(instance, SolverConfig(CP_SAT, mode=Regime.TROPICAL_AWARE))
    with pytest.raises(ValueError, match="does not work in the tropical-aware regime"):
        solvers.get(CP_SAT).run(instance, SolverConfig(CP_SAT, mode=Regime.TROPICAL_AWARE))


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"lookahead": True}, "unknown options lookahead"),
        ({"node_limit": 0}, "node_limit must be a positive integer"),
        ({"max_placements": True}, "max_placements must be a positive integer"),
        ({"max_placements": 1.5}, "max_placements must be a positive integer"),
        ({"coverage": "yes"}, "coverage must be true or false"),
        ({"anchor": 1}, "anchor must be true or false"),
        ({"tray_rotations": "twice"}, "tray_rotations must be one of"),
    ],
)
def test_options_it_does_not_understand_are_refused(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        solve(footprint(), SolverConfig(CP_SAT, options=options))


def test_a_negative_seed_is_refused() -> None:
    with pytest.raises(ValueError, match="seed must not be negative"):
        solve(footprint(), SolverConfig(CP_SAT, seed=-1))


def test_without_or_tools_the_solver_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """The solver is registered either way; only running it needs the extra."""
    for module in ("ortools", "ortools.sat", "ortools.sat.python"):
        monkeypatch.setitem(sys.modules, module, None)
    assert CP_SAT in solvers.available()
    with pytest.raises(ImportError, match="'cp-sat' extra"):
        solve(footprint(), SolverConfig(CP_SAT))


# --- one name for a choice and its turns --------------------------------------------------


def test_a_choice_and_its_turn_have_one_form() -> None:
    # Four placements; a half turn swaps 0 with 3 and 1 with 2.
    half = [3, 2, 1, 0]
    assert cp_sat._form((0, 1), [half]) == (0, 1)
    assert cp_sat._form((2, 3), [half]) == (0, 1)
    assert cp_sat._form((0, 2), [half]) == (0, 2)
    assert cp_sat._form((1, 3), [half]) == (0, 2)
    # With no turns a choice is its own form.
    assert cp_sat._form((2, 3), []) == (2, 3)


def test_a_turn_that_leaves_the_list_is_no_turn() -> None:
    # Placement 3's image is not listed, so (2, 3) has no listed turn to be confused with.
    assert cp_sat._form((2, 3), [[3, 2, 1, None]]) == (2, 3)
    assert cp_sat._form((1, 2), [[3, 2, 1, None]]) == (1, 2)
