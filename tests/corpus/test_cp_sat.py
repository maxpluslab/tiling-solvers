"""Phase 6 exit criterion: CP-SAT and the Rust search return the same assemblies.

On every fixture, in its own regime, ``cp_sat.placements`` and
``rust.contact_dfs`` are both run to the end, and the two sets of assemblies
are compared polygon by polygon with the test oracle. Both exhaust on every
fixture, so the comparison leaves none out.

The agreement is less than it sounds and more than nothing. CP-SAT chooses
among the placements a run of the same search listed, so it cannot find an
assembly the search has no placements for. What it checks is the search's
choosing: its bookkeeping of what is placed, its pruning, its duplicate
removal. The model is built from pairwise geometry alone and solved by code
that shares none of that.

The counts pinned here are findings, relative to the listed placements and in
``f64`` with tolerances.
"""

from typing import Any

import pytest

from maxplus_solvers import PuzzleInstance, Regime, SolverConfig, SolveResult, SolveStatus, solve
from support import assemblies, corpus, geometry

CP_SAT = "cp_sat.placements"
DFS = "rust.contact_dfs"

PIECES = {entry["id"]: entry["pieceCount"] for entry in corpus.index()["fixtures"]}
CORPUS = corpus.fixture_ids(kind="corpus")
FLAT = corpus.fixture_ids(kind="corpus", regime="footprint")
RELIEF = corpus.fixture_ids(kind="corpus", regime="relief")
SYNTHETIC = corpus.fixture_ids(kind="synthetic")
SMALL = [f for f in FLAT if PIECES[f] <= 11]
# Listing the placements of these is a whole search of tens of seconds, and the
# model has thousands of them.
SLOW = {"new1-flat", "new2-flat", "rat2-flat"}
# As in test_rust_contact_dfs.py. Not in this table: one.
ASSEMBLIES = {"rat1-flat": 101, "rat2-flat": 2}


def marked(fixture_ids: list[str]) -> list[Any]:
    return [
        pytest.param(f, marks=pytest.mark.slow) if f in SLOW else pytest.param(f)
        for f in fixture_ids
    ]


def instance_of(fixture_id: str) -> PuzzleInstance:
    return PuzzleInstance.from_dict(corpus.fixture(fixture_id))


def whole(mode: Regime, solver: str = CP_SAT, **options: Any) -> SolverConfig:
    return SolverConfig(solver, mode=mode, max_solutions=None, options=options)


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


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


def test_the_exit_criterion_covers_every_fixture() -> None:
    assert len(CORPUS) == 16 and len(SYNTHETIC) == 4
    assert set(FLAT) >= SLOW | set(ASSEMBLIES)


# --- the exit criterion -------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", marked(CORPUS + SYNTHETIC))
def test_cp_sat_and_the_search_return_the_same_assemblies(fixture_id: str) -> None:
    instance = instance_of(fixture_id)
    chosen = solve(instance, whole(instance.regime), validate=True)
    searched = solve(instance, whole(instance.regime, DFS))
    assert chosen.status is SolveStatus.SOLVED
    # Both ran to the end: this fixture is not left out of the comparison.
    assert chosen.exhaustive and searched.exhaustive
    assert not chosen.candidates_proven_complete
    assert chosen.candidate_set == (
        "corner-contact-relief-reachable/1"
        if instance.regime is Regime.RELIEF
        else "corner-contact-reachable/1"
    )
    assert all(solution.valid is True for solution in chosen.solutions)

    found = placed(instance, chosen)
    # One of each family of turns from either solver; which member is each solver's choice.
    assert same_up_to_turns(instance, found, placed(instance, searched))
    if fixture_id in CORPUS:
        assert len(found) == ASSEMBLIES.get(fixture_id, 1)
    # No assembly is returned twice, in any orientation of the tray.
    assert all(len(orbit) == 1 for orbit in assemblies.orbits(instance.target, found))
    # The answer key is among them, in one orientation.
    centre = geometry.centroid(instance.target)
    key = assemblies.world(corpus.fixture(fixture_id), corpus.key(fixture_id)["poses"])
    turns = [assemblies.turned(key, t, centre) for t in assemblies.tray_turns(instance.target)]
    assert sum(any(assemblies.same(k, a) for k in turns) for a in found) == 1

    # The listing search is the search: same rules, same tree.
    for count in ("nodes", "backtracks", "placements", "candidates_generated"):
        assert chosen.metrics[count] == searched.metrics[count], count
    assert chosen.metrics["solutions"] == len(found)


@pytest.mark.parametrize("fixture_id", SMALL + [f.removesuffix("-flat") for f in SMALL])
def test_counting_every_orientation_the_two_agree_as_well(fixture_id: str) -> None:
    instance = instance_of(fixture_id)
    chosen = solve(instance, whole(instance.regime, tray_rotations="all"), validate=True)
    searched = solve(instance, whole(instance.regime, DFS, tray_rotations="all"))
    assert chosen.exhaustive and searched.exhaustive
    assert all(solution.valid is True for solution in chosen.solutions)
    assert chosen.metrics["duplicates"] == 0
    found = placed(instance, chosen)
    assert same_set(found, placed(instance, searched))
    # The tray is a square and no assembly here is its own turn: four of each.
    orbits = assemblies.orbits(instance.target, found)
    assert all(len(orbit) == 4 for orbit in orbits)
    assert len(orbits) == ASSEMBLIES.get(fixture_id, 1)


# --- the switches -------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", [f for f in SMALL if f != "rat1-flat"] + ["rat1", "new3"])
def test_no_switch_changes_what_is_chosen(fixture_id: str) -> None:
    """The listing rules and the coverage constraints change the model, never the answer.

    ``rat1-flat`` is left to the test below: without coverage CP-SAT does not
    finish it in a minute.
    """
    instance = instance_of(fixture_id)
    reference = placed(instance, solve(instance, whole(instance.regime)))
    assert reference
    switches = ("anchor", "cavity_pruning", "closure_pruning", "coverage")
    variants: list[dict[str, Any]] = [{switch: False} for switch in switches]
    variants.append(dict.fromkeys(switches, False))
    variants.append({"targeted_probes": True})
    for options in variants:
        result = solve(instance, whole(instance.regime, **options), validate=True)
        assert result.exhaustive, options
        assert all(solution.valid is True for solution in result.solutions), options
        assert same_up_to_turns(instance, placed(instance, result), reference), options


def test_without_the_anchor_the_turns_are_found_and_recognised() -> None:
    """``rat1-flat``: 404 choices, 303 of them turns of the other 101."""
    instance = instance_of("rat1-flat")
    anchored = solve(instance, whole(instance.regime))
    free = solve(instance, whole(instance.regime, anchor=False), validate=True)
    assert free.exhaustive
    assert len(free.solutions) == 101 and free.metrics["duplicates"] == 303
    assert anchored.metrics["duplicates"] == 0
    assert free.metrics["model_placements"] > anchored.metrics["model_placements"]
    assert same_up_to_turns(instance, placed(instance, free), placed(instance, anchored))


# --- what the model looks like ------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", [f for f in CORPUS if f not in SLOW])
def test_the_list_is_far_shorter_than_the_search_that_made_it(fixture_id: str) -> None:
    """A finding: the search puts the same few placements down again and again.

    Every placement listed was placed, so the list is no longer than the
    count of placements made. On the footprints it is much shorter.
    """
    instance = instance_of(fixture_id)
    metrics = solve(instance, whole(instance.regime)).metrics
    assert PIECES[fixture_id] <= metrics["model_placements"] <= metrics["placements"]
    # Overlaps are stated at points, in cliques, and the grid leaves some as pairs. With
    # a probe for each of those, nearly all become cliques and nothing else changes.
    assert metrics["model_cliques"] > 0
    targeted = solve(instance, whole(instance.regime, targeted_probes=True)).metrics
    assert targeted["model_placements"] == metrics["model_placements"]
    assert targeted["model_pairs"] <= metrics["model_pairs"]
    assert targeted["model_cliques"] >= metrics["model_cliques"]


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_under_roofs_the_choice_takes_no_search(fixture_id: str) -> None:
    """A finding: in relief, propagation alone settles the choice."""
    instance = instance_of(fixture_id)
    result = solve(instance, whole(instance.regime))
    assert result.exhaustive and len(result.solutions) == 1
    assert result.metrics["sat_conflicts"] == 0
