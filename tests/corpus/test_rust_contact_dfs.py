"""Phase 5 exit criterion: ``rust.contact_dfs`` solves and validates the corpus fixtures.

Each fixture is searched to the end in its own regime. That was all 16 when the
phase closed; ``cor1``, added since, is searched to the end with its roofs and
not without them, and ``cor1-flat`` is tested for what an unfinished search can
say. Every assembly returned
passes the independent validator, the answer key is among them, and the times
to the first solution and to the end of the search are reported separately. On
the fixtures the Python prototype can finish, the two solvers find the same
assemblies, and with its additions switched off the Rust search does exactly
the prototype's work.

The counts pinned here are findings about the corpus, relative to the
candidates the search generates and in ``f64`` with tolerances. They are what
the search finds, not proven numbers of solutions.
"""

from typing import Any

import pytest

from maxplus_solvers import PuzzleInstance, Regime, SolverConfig, SolveResult, SolveStatus, solve
from maxplus_solvers.validation import validate_solution
from support import assemblies, corpus, geometry

DFS = "rust.contact_dfs"
PROTOTYPE = "python.contact_dfs"
SWITCHES = ("anchor", "cavity_pruning", "closure_pruning", "lookahead")
# The Rust search doing only what the prototype does, in the prototype's order.
AS_THE_PROTOTYPE = {
    "tray_rotations": "all",
    "anchor": False,
    "cavity_pruning": False,
    "closure_pruning": False,
    "lookahead": False,
    "order": "generated",
}

PIECES = {entry["id"]: entry["pieceCount"] for entry in corpus.index()["fixtures"]}
EVERY = corpus.fixture_ids(kind="corpus")
CORPUS = [f for f in EVERY if f not in corpus.UNFINISHED]
FLAT = [f for f in corpus.fixture_ids(kind="corpus", regime="footprint") if f in CORPUS]
RELIEF = corpus.fixture_ids(kind="corpus", regime="relief")
SYNTHETIC = corpus.fixture_ids(kind="synthetic")
# What the prototype finishes in seconds: the footprints of up to 11 pieces.
SMALL = [f for f in FLAT if PIECES[f] <= 11]
# Whole searches of these take tens of seconds.
SLOW = {"new1-flat", "new2-flat"}
# Relief puzzles built to be hard for this search (cor1: level creases at shared heights).
HARD_RELIEF = {"cor1"}

# Assemblies found by the whole search, up to turning the tray. Not in this table: one.
# rat1-flat's 101 is the prototype's 404 in four orientations each (phase 4).
ASSEMBLIES = {"rat1-flat": 101, "rat2-flat": 2}


def marked(fixture_ids: list[str]) -> list[Any]:
    return [
        pytest.param(f, marks=pytest.mark.slow) if f in SLOW else pytest.param(f)
        for f in fixture_ids
    ]


def instance_of(fixture_id: str) -> PuzzleInstance:
    return PuzzleInstance.from_dict(corpus.fixture(fixture_id))


def whole(mode: Regime, solver: str = DFS, **options: Any) -> SolverConfig:
    """A search to the end, in the given regime."""
    return SolverConfig(solver, mode=mode, max_solutions=None, options=options)


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


def keyed(fixture_id: str) -> list[Any]:
    return assemblies.world(corpus.fixture(fixture_id), corpus.key(fixture_id)["poses"])


def turns_of_the_key(fixture_id: str, instance: PuzzleInstance, found: list[Any]) -> int:
    """How many of the assemblies found are the answer key in some orientation of the tray."""
    centre = geometry.centroid(instance.target)
    turned = [
        assemblies.turned(keyed(fixture_id), turn, centre)
        for turn in assemblies.tray_turns(instance.target)
    ]
    return sum(any(assemblies.same(key, assembly) for key in turned) for assembly in found)


def same_set(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(sum(assemblies.same(x, y) for y in b) == 1 for x in a)


def test_the_exit_criterion_covers_the_whole_corpus() -> None:
    assert len(EVERY) == 18 and len(FLAT) == 8 and len(RELIEF) == 9
    assert sorted(CORPUS) == sorted(FLAT + RELIEF)
    # Only footprints are left out, and only those named.
    assert sorted(set(EVERY) - set(CORPUS)) == sorted(corpus.UNFINISHED) == ["cor1-flat"]
    assert set(RELIEF) >= HARD_RELIEF
    assert sorted(SMALL) == ["new3-flat", "new4-flat", "new5-flat", "rat1-flat", "rev2-flat"]
    assert set(FLAT) >= SLOW | set(ASSEMBLIES)


# --- the exit criterion -------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", marked(CORPUS))
def test_every_fixture_is_solved_and_validated_in_its_own_regime(fixture_id: str) -> None:
    instance = instance_of(fixture_id)
    result = solve(instance, whole(instance.regime), validate=True)
    assert result.status is SolveStatus.SOLVED
    assert result.regime is instance.regime
    assert result.exhaustive
    assert not result.candidates_proven_complete
    assert result.candidate_set == (
        "corner-contact-relief/1" if instance.regime is Regime.RELIEF else "corner-contact/1"
    )
    for solution in result.solutions:
        assert solution.valid is True
        # Checked again here, without going through solve().
        report = validate_solution(instance, solution.poses)
        assert report.solved, report.failed
        # An exact assembly, not one that merely squeezes inside the tolerances.
        assert report.worst_overlap_depth_mm == pytest.approx(0.0, abs=1e-9)
        assert report.worst_outside_mm == pytest.approx(0.0, abs=1e-9)
        assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)
        if instance.regime is Regime.RELIEF:
            assert report.worst_roof_mismatch_mm == pytest.approx(0.0, abs=1e-9)

    found = placed(instance, result)
    # The answer key is found, once.
    assert turns_of_the_key(fixture_id, instance, found) == 1
    # No assembly is returned twice, in any orientation of the tray.
    assert all(len(orbit) == 1 for orbit in assemblies.orbits(instance.target, found))
    assert len(found) == ASSEMBLIES.get(fixture_id, 1)

    # The two times are separate numbers, and in order.
    metrics = result.metrics
    assert metrics["solutions"] == len(found)
    assert 0.0 <= metrics["first_solution_s"] <= metrics["exhausted_s"]
    assert metrics["exhausted_s"] == metrics["wall_time_s"]


@pytest.mark.parametrize("fixture_id", [f for f in CORPUS if f not in SLOW])
def test_the_first_solution_is_reported_before_the_search_is_finished(fixture_id: str) -> None:
    """Stopped at its first solution, the search claims a solution and nothing more."""
    instance = instance_of(fixture_id)
    result = solve(instance, SolverConfig(DFS, mode=instance.regime), validate=True)
    assert result.status is SolveStatus.SOLVED
    (solution,) = result.solutions
    assert solution.valid is True
    assert not result.exhaustive
    assert result.metrics["first_solution_s"] >= 0.0
    assert "exhausted_s" not in result.metrics


def test_a_search_that_is_stopped_claims_nothing_about_the_rest() -> None:
    """``cor1-flat``: 27 footprints, stopped at a node limit before any assembly.

    What it found by then is pinned (a regression value: no oracle knows where
    the search is after 200 000 nodes). The finding is that it found nothing:
    without roofs and without the edge-to-edge assumption, the corrugated
    columns leave the search wandering for a long way.
    """
    instance = instance_of("cor1-flat")
    result = solve(instance, whole(instance.regime, node_limit=200_000), validate=True)
    assert result.status is SolveStatus.INTERRUPTED
    assert not result.exhaustive
    assert "exhausted_s" not in result.metrics
    assert result.metrics["nodes"] == 200_000
    assert result.solutions == ()


# --- against the prototype ----------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", SMALL)
def test_the_solution_set_is_the_prototypes(fixture_id: str) -> None:
    """Counting every orientation, the two searches return the same assemblies.

    Counting each once, the Rust search returns one assembly out of every four
    of the prototype's: the tray is a square and no assembly here is its own
    rotation.
    """
    instance = instance_of(fixture_id)
    prototype = placed(instance, solve(instance, whole(Regime.FOOTPRINT, PROTOTYPE)))
    every = placed(instance, solve(instance, whole(instance.regime, tray_rotations="all")))
    assert same_set(every, prototype)

    once = placed(instance, solve(instance, whole(instance.regime)))
    orbits = assemblies.orbits(instance.target, prototype)
    assert len(once) == len(orbits)
    for orbit in orbits:
        members = [prototype[i] for i in orbit]
        assert sum(any(assemblies.same(a, m) for m in members) for a in once) == 1


@pytest.mark.parametrize("fixture_id", SMALL)
def test_with_its_additions_off_the_search_does_the_prototypes_work(fixture_id: str) -> None:
    """Same nodes, same backtracks, same candidates: one algorithm written twice.

    The prototype's counts come from Python driving single geometry calls, the
    Rust counts from one call that runs the whole search.
    """
    instance = instance_of(fixture_id)
    prototype = solve(instance, whole(Regime.FOOTPRINT, PROTOTYPE)).metrics
    bare = solve(instance, whole(instance.regime, **AS_THE_PROTOTYPE)).metrics
    for count in (
        "nodes",
        "backtracks",
        "backtrack_depth",
        "placements",
        "max_depth",
        "candidates_generated",
        "rejected_outside",
        "rejected_overlap",
        "solutions",
    ):
        assert bare[count] == prototype[count], count


# --- the rules can be switched off --------------------------------------------------------


@pytest.mark.parametrize("fixture_id", SMALL + [f.removesuffix("-flat") for f in SMALL])
def test_no_rule_changes_what_the_whole_search_finds(fixture_id: str) -> None:
    """Pruning, lookahead, the anchor and the order change the work, never the answer."""
    instance = instance_of(fixture_id)
    on = dict.fromkeys(SWITCHES, True)
    reference_result = solve(instance, whole(instance.regime, **on))
    reference = placed(instance, reference_result)
    assert reference
    variants: list[dict[str, Any]] = [{**on, switch: False} for switch in SWITCHES]
    variants.append(dict.fromkeys(SWITCHES, False))
    variants.append({**on, "order": "generated"})
    variants.append({**on, "order": "random"})
    for options in variants:
        result = solve(instance, whole(instance.regime, **options))
        assert result.exhaustive, options
        assert same_set(placed(instance, result), reference), options
    # Nor does any rule cost nodes: with everything off the search visits at least as many.
    bare = solve(instance, whole(instance.regime, **dict.fromkeys(SWITCHES, False)))
    assert bare.metrics["nodes"] >= reference_result.metrics["nodes"]


@pytest.mark.parametrize("fixture_id", ["new3-flat", "rat1"])
def test_a_random_order_is_fixed_by_its_seed(fixture_id: str) -> None:
    instance = instance_of(fixture_id)

    def run(seed: int) -> SolveResult:
        return solve(
            instance,
            SolverConfig(DFS, mode=instance.regime, seed=seed, options={"order": "random"}),
        )

    first, again = run(7), run(7)
    assert placed(instance, first) == placed(instance, again)
    assert first.metrics["nodes"] == again.metrics["nodes"]
    # Other seeds reach a valid first solution by other routes.
    nodes = {run(seed).metrics["nodes"] for seed in range(8)}
    assert len(nodes) > 1


# --- what the roofs do --------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", [f for f in RELIEF if f not in HARD_RELIEF])
def test_the_roofs_leave_one_assembly_and_a_short_search(fixture_id: str) -> None:
    """A finding: in relief every corpus puzzle has one assembly, found almost directly.

    The bound on nodes is loose on purpose. With every rule off the largest
    whole search is 146 nodes (``rat2``, 20 pieces); the footprint twins take
    up to a million. It is the roofs that make these puzzles easy, not the
    pruning.
    """
    instance = instance_of(fixture_id)
    result = solve(instance, whole(instance.regime, **dict.fromkeys(SWITCHES, False)))
    assert result.exhaustive
    assert len(result.solutions) == 1
    assert result.metrics["nodes"] <= 200
    assert result.metrics["rejected_roof"] > 0


def test_level_creases_make_a_relief_puzzle_hard() -> None:
    """``cor1``, made to be hard with its roofs on: one assembly, at ten times the cost.

    Its ridges and valleys each stand at one height across a row, so the walls
    along them look alike. Every other relief puzzle in the corpus takes at
    most 200 nodes with every rule off; this one, of 27 pieces, more than 1 000.
    """
    instance = instance_of("cor1")
    result = solve(instance, whole(instance.regime, **dict.fromkeys(SWITCHES, False)))
    assert result.exhaustive
    assert len(result.solutions) == 1
    assert result.metrics["nodes"] > 1_000


def test_a_relief_puzzle_seen_as_a_footprint_has_its_twins_assemblies() -> None:
    """``rat1`` with its roofs hidden: 101 assemblies again, from other stored rotations."""
    relief = instance_of("rat1")
    result = solve(relief, whole(Regime.FOOTPRINT), validate=True)
    assert result.regime is Regime.FOOTPRINT
    assert result.exhaustive
    assert all(solution.valid for solution in result.solutions)
    assert len(result.solutions) == ASSEMBLIES["rat1-flat"]
    assert "roof_mismatch_mm" not in (result.solutions[0].residuals or {})
    # The keyed assembly is one of them. Its poses here need not continue the roofs: six
    # of the pieces are their own half turn as footprints, and a footprint search is free
    # to return either way round.
    assert turns_of_the_key("rat1", relief, placed(relief, result)) == 1


# --- counts derived by hand ---------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", SYNTHETIC)
def test_synthetic_puzzles_have_the_solution_counts_worked_out_by_hand(fixture_id: str) -> None:
    """``canonical`` assemblies counting each once, ``assemblies`` counting every orientation.

    The counts are for footprints and are derived in ``synthetic.py``.
    """
    expected = corpus.key(fixture_id)["solutionCount"]
    instance = instance_of(fixture_id)
    seen = instance.as_regime("footprint")
    key = keyed(fixture_id)

    once = solve(instance, whole(Regime.FOOTPRINT), validate=True)
    assert once.exhaustive
    assert all(solution.valid for solution in once.solutions)
    assert len(once.solutions) == expected["canonical"]
    assert turns_of_the_key(fixture_id, instance, placed(seen, once)) == 1

    every = solve(instance, whole(Regime.FOOTPRINT, tray_rotations="all"), validate=True)
    assert every.exhaustive
    found = placed(seen, every)
    assert len(found) == expected["assemblies"]
    for i, first in enumerate(found):
        for second in found[i + 1 :]:
            assert not assemblies.same(first, second), "one assembly returned twice"
    assert any(assemblies.same(assembly, key) for assembly in found)


def test_the_ridge_has_one_assembly_in_relief_however_turns_are_counted() -> None:
    """Two rectangles under one ridge: by hand, each half goes on its own side.

    As footprints the halves stand in four ways (side by side or one above
    the other, in either order). The ridge runs one way across the tray, so
    in relief only the keyed arrangement remains; turning the tray turns the
    pieces' roofs with them, which is the same assembly seen from another
    side and not a second one.
    """
    fixture_id = "syn-two-rectangles-ridge"
    instance = instance_of(fixture_id)
    assert instance.regime is Regime.RELIEF
    once = solve(instance, whole(instance.regime), validate=True)
    assert once.exhaustive and len(once.solutions) == 1
    assert once.solutions[0].valid is True
    assert turns_of_the_key(fixture_id, instance, placed(instance, once)) == 1
