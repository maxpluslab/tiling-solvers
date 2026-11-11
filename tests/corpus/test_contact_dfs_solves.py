"""Phase 4 exit criterion: ``python.contact_dfs`` solves the small flat fixtures.

The 6-piece and 9-piece footprint fixtures are solved, and every solution
returned passes the independent validator. The searches are also run to their
end, and what they find is compared with the answer keys and, for the synthetic
puzzles, with solution counts derived by hand in ``synthetic.py``.

A search that runs to its end and finds four assemblies has shown that its
candidate set holds four. It has not proven that the puzzle has four: the
candidates are generated in ``f64`` with tolerances.
"""

from typing import Any

import pytest

from maxplus_solvers import PuzzleInstance, Regime, SolverConfig, SolveResult, SolveStatus, solve
from maxplus_solvers.validation import validate_solution
from support import assemblies, corpus, geometry

DFS = "python.contact_dfs"

PIECES = {entry["id"]: entry["pieceCount"] for entry in corpus.index()["fixtures"]}
FLAT = corpus.fixture_ids(kind="corpus", regime="footprint")
SMALL = [f for f in FLAT if PIECES[f] in (6, 9)]
# Also within reach of the prototype, though the roadmap does not ask for it.
ELEVEN = [f for f in FLAT if PIECES[f] == 11]
SYNTHETIC = corpus.fixture_ids(kind="synthetic")
# The relief twins of the small fixtures: other rotations and another order of the same pieces.
SMALL_RELIEF = [f.removesuffix("-flat") for f in SMALL]


def instance_of(fixture_id: str) -> PuzzleInstance:
    return PuzzleInstance.from_dict(corpus.fixture(fixture_id))


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


def keyed(fixture_id: str) -> list[Any]:
    return assemblies.world(corpus.fixture(fixture_id), corpus.key(fixture_id)["poses"])


def test_the_exit_criterion_covers_the_fixtures_the_roadmap_names() -> None:
    assert sorted(SMALL) == ["new3-flat", "new4-flat", "new5-flat", "rev2-flat"]
    assert sorted(PIECES[f] for f in SMALL) == [6, 9, 9, 9]
    assert ELEVEN == ["rat1-flat"]


# --- solved, and valid --------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", SMALL + ELEVEN)
def test_the_first_solution_passes_the_validator(fixture_id: str) -> None:
    instance = instance_of(fixture_id)
    result = solve(instance, SolverConfig(DFS), validate=True)
    assert result.status is SolveStatus.SOLVED
    (solution,) = result.solutions
    assert solution.valid is True
    # Checked again here, without going through solve().
    report = validate_solution(instance, solution.poses)
    assert report.solved, report.failed
    # An exact assembly, not one that merely squeezes inside the tolerances.
    assert report.worst_overlap_depth_mm == 0.0
    assert report.worst_outside_mm == 0.0
    assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)
    assert report.outside_area_mm2 == pytest.approx(0.0, abs=1e-6)


def orientations_of_the_key(
    fixture_id: str, instance: PuzzleInstance, found: list[Any]
) -> list[int]:
    """For each quarter turn of the tray, how many of the assemblies found are the key so turned."""
    key = keyed(fixture_id)
    centre = geometry.centroid(instance.target)
    turns = assemblies.tray_turns(instance.target)
    assert len(turns) == 4, "a square tray"
    return [
        sum(assemblies.same(assemblies.turned(key, turn, centre), assembly) for assembly in found)
        for turn in turns
    ]


@pytest.mark.parametrize("fixture_id", SMALL)
def test_every_solution_of_the_whole_search_passes_and_is_the_keyed_assembly(
    fixture_id: str,
) -> None:
    """Run to the end. Each assembly found is the answer key, in one of the tray's orientations."""
    instance = instance_of(fixture_id)
    result = solve(instance, SolverConfig(DFS, max_solutions=None), validate=True)
    assert result.status is SolveStatus.SOLVED
    assert result.exhaustive
    assert not result.candidates_proven_complete
    assert all(solution.valid for solution in result.solutions)
    found = placed(instance, result)
    # A finding about the corpus, relative to the candidates generated: these puzzles have
    # one footprint assembly, found once in each orientation of the tray and nothing else.
    assert orientations_of_the_key(fixture_id, instance, found) == [1, 1, 1, 1]
    assert len(found) == 4


def test_the_eleven_piece_footprint_has_many_assemblies_and_the_key_is_one() -> None:
    """A finding: without its roofs, ``rat1`` can be assembled in 101 ways.

    The whole search returns 404 assemblies, all of which pass the validator as
    exact tilings. They are 101 assemblies in the tray's four orientations
    each, and the answer key is one of the 101. The numbers are pinned: they
    are what this search finds, in ``f64`` and over its own candidates, not a
    proven count. If they change, either the corpus or the candidate generator
    did, and it should be known which.
    """
    fixture_id = "rat1-flat"
    instance = instance_of(fixture_id)
    result = solve(instance, SolverConfig(DFS, max_solutions=None), validate=True)
    assert result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    found = placed(instance, result)
    assert orientations_of_the_key(fixture_id, instance, found) == [1, 1, 1, 1]
    groups = assemblies.orbits(instance.target, found)
    assert {len(group) for group in groups} == {4}, "no assembly is its own rotation"
    assert (len(found), len(groups)) == (404, 101)


@pytest.mark.parametrize("fixture_id", SMALL_RELIEF)
def test_a_relief_fixture_is_solved_as_a_footprint(fixture_id: str) -> None:
    """The roofs are hidden from the solver, and the answer is judged without them."""
    relief = instance_of(fixture_id)
    assert relief.regime is Regime.RELIEF
    result = solve(relief, SolverConfig(DFS, mode=Regime.FOOTPRINT), validate=True)
    assert result.status is SolveStatus.SOLVED
    assert result.regime is Regime.FOOTPRINT
    assert result.solutions[0].valid is True
    assert "roof_mismatch_mm" not in (result.solutions[0].residuals or {})
    with pytest.raises(ValueError, match="does not work in relief mode"):
        solve(relief, SolverConfig(DFS, mode=Regime.RELIEF))


# --- counts derived by hand ---------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", SYNTHETIC)
def test_synthetic_puzzles_have_the_solution_counts_worked_out_by_hand(fixture_id: str) -> None:
    """``assemblies`` distinct tilings, and ``canonical`` of them up to turning the tray.

    The solver counts an assembly once however its congruent pieces are
    labelled and however a symmetric piece is turned, which is the convention
    of the counts in ``synthetic.py``.
    """
    expected = corpus.key(fixture_id)["solutionCount"]
    instance = instance_of(fixture_id)
    result = solve(
        instance, SolverConfig(DFS, mode=Regime.FOOTPRINT, max_solutions=None), validate=True
    )
    assert result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    seen = instance.as_regime("footprint")
    found = placed(seen, result)
    assert len(found) == expected["assemblies"]
    for i, first in enumerate(found):
        for second in found[i + 1 :]:
            assert not assemblies.same(first, second), "one assembly returned twice"
    assert len(assemblies.orbits(instance.target, found)) == expected["canonical"]
    assert any(assemblies.same(a, keyed(fixture_id)) for a in found)


def test_the_orbit_count_can_tell_one_assembly_from_two() -> None:
    """Guard the helper behind the count above: unrelated assemblies are separate orbits."""
    square = [(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)]
    halves = [[(-2, -2), (0, -2), (0, 2), (-2, 2)], [(0, -2), (2, -2), (2, 2), (0, 2)]]
    across = [[(-2, -2), (2, -2), (2, 0), (-2, 0)], [(-2, 0), (2, 0), (2, 2), (-2, 2)]]
    thirds = [[(-2, -2), (-1, -2), (-1, 2), (-2, 2)], [(-1, -2), (2, -2), (2, 2), (-1, 2)]]
    assert assemblies.orbits(square, [halves, across, thirds]) == [[0, 1], [2]]
    assert not assemblies.same(halves, across)
    assert assemblies.same(halves, halves[::-1])
