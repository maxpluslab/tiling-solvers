"""Phase 8 exit criterion: assuming edge to edge finds exactly the edge-to-edge assemblies.

Every tropical puzzle is cut from a polyhedral complex, so its pieces meet edge
to edge: no vertex of a piece lies inside another piece's edge. Told to assume
this, ``rust.contact_dfs`` refuses placements that make a T, and uses two rules
that follow: a piece edge lies only against an equally long edge of another
piece, and an edge with no such partner stays on the tray.

For every corpus fixture the search is run to its end without the assumption
and with it, the two rules on and off. What the assumed searches find is
exactly what the plain search finds that the independent oracle
(``support.geometry.is_edge_to_edge``, by twin edges) calls edge to edge; the
answer key is among it and the validator passes all of it. ``cor1-flat``, whose
plain search has not been seen to end, is tested apart: everything the assumed
search returns is valid and edge to edge by the oracle, and the key is among it. The counts are
relative to the candidates the search generates, in ``f64`` with tolerances.
"""

from pathlib import Path
from typing import Any

import pytest

from maxplus_solvers import (
    Assumption,
    PuzzleInstance,
    Regime,
    SolverConfig,
    SolveResult,
    SolveStatus,
    solve,
)
from maxplus_solvers.experiments import benchmark, proxies
from maxplus_solvers.experiments.cli import main
from support import assemblies, corpus, geometry

DFS = "rust.contact_dfs"
E2E = (Assumption.EDGE_TO_EDGE,)
# Twin edges are found to this, in mm: far above rounding, far below any feature.
TWIN_MM = 1e-6

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "benchmarks" / "manifests"
RESULTS = ROOT / "benchmarks" / "results"
EVERY = corpus.fixture_ids(kind="corpus")
CORPUS = [f for f in EVERY if f not in corpus.UNFINISHED]
# Assemblies found assuming nothing, up to turning the tray, where not one (phase 5).
ASSEMBLIES = {"rat1-flat": 101, "rat2-flat": 2}
# Assemblies found assuming edge to edge, where not one.
EDGE_TO_EDGE_ASSEMBLIES = {"cor1-flat": 48}
# Where a search assuming nothing stops in the committed table (benchmarks/manifests).
NODE_LIMIT = 1_500_000
# Whole plain searches of these take tens of seconds.
SLOW = {"new1-flat", "new2-flat"}
RULES = [
    {"equal_edges": True, "wall_edges": True},
    {"equal_edges": True, "wall_edges": False},
    {"equal_edges": False, "wall_edges": True},
    {"equal_edges": False, "wall_edges": False},
]


def marked(fixture_ids: list[str]) -> list[Any]:
    return [
        pytest.param(f, marks=pytest.mark.slow) if f in SLOW else pytest.param(f)
        for f in fixture_ids
    ]


def instance_of(fixture_id: str) -> PuzzleInstance:
    return PuzzleInstance.from_dict(corpus.fixture(fixture_id))


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


def same_set(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(sum(assemblies.same(x, y) for y in b) == 1 for x in a)


def test_every_answer_key_meets_edge_to_edge() -> None:
    """The premise, on what the generator made: no corpus puzzle has a T."""
    for fixture_id in EVERY:
        instance = corpus.fixture(fixture_id)
        target = instance["target"]["vertices"]
        world = assemblies.world(instance, corpus.key(fixture_id)["poses"])
        assert geometry.is_edge_to_edge(world, target, TWIN_MM), fixture_id


@pytest.mark.parametrize("fixture_id", marked(CORPUS))
def test_the_assumption_finds_exactly_the_edge_to_edge_assemblies(fixture_id: str) -> None:
    instance = instance_of(fixture_id)
    plain = solve(instance, SolverConfig(DFS, mode=instance.regime, max_solutions=None))
    assert plain.exhaustive
    edge_to_edge = [
        assembly
        for assembly in placed(instance, plain)
        if geometry.is_edge_to_edge(assembly, instance.target, TWIN_MM)
    ]
    key = assemblies.world(corpus.fixture(fixture_id), corpus.key(fixture_id)["poses"])
    turns = [
        assemblies.turned(key, turn, geometry.centroid(instance.target))
        for turn in assemblies.tray_turns(instance.target)
    ]

    for rules in RULES:
        config = SolverConfig(
            DFS, mode=instance.regime, max_solutions=None, assumptions=E2E, options=rules
        )
        result = solve(instance, config, validate=True)
        assert result.status is SolveStatus.SOLVED, rules
        assert result.exhaustive, rules
        assert result.assumptions == E2E
        assert result.candidate_set.endswith("-edge-to-edge/1")
        found = placed(instance, result)
        assert same_set(found, edge_to_edge), (rules, len(found), len(edge_to_edge))
        assert all(solution.valid is True for solution in result.solutions), rules
        assert sum(any(assemblies.same(k, a) for k in turns) for a in found) == 1, rules
        # The assumption only takes work away.
        assert result.metrics["nodes"] <= plain.metrics["nodes"], rules


def test_where_the_plain_search_does_not_end_the_assumed_one_does() -> None:
    """``cor1-flat``: 48 edge-to-edge assemblies, the answer key among them.

    Its plain search was stopped at 3 000 000 nodes, so there is nothing to
    compare against; what is checked is what can be checked one assembly at a
    time. The count is relative to the candidates, like every count here: the
    corrugated columns change places without making a T.
    """
    instance = instance_of("cor1-flat")
    target = instance.target
    for rules in RULES:
        config = SolverConfig(DFS, max_solutions=None, assumptions=E2E, options=rules)
        result = solve(instance, config, validate=True)
        assert result.status is SolveStatus.SOLVED and result.exhaustive, rules
        found = placed(instance, result)
        assert len(found) == EDGE_TO_EDGE_ASSEMBLIES["cor1-flat"], rules
        assert all(solution.valid is True for solution in result.solutions), rules
        assert all(geometry.is_edge_to_edge(a, target, TWIN_MM) for a in found), rules
        assert all(len(orbit) == 1 for orbit in assemblies.orbits(target, found)), rules
        key = assemblies.world(corpus.fixture("cor1-flat"), corpus.key("cor1-flat")["poses"])
        centre = geometry.centroid(target)
        turns = [assemblies.turned(key, t, centre) for t in assemblies.tray_turns(target)]
        assert sum(any(assemblies.same(k, a) for k in turns) for a in found) == 1, rules


@pytest.mark.parametrize("fixture_id", ["rat1-flat", "rat2-flat"])
def test_the_footprints_with_several_assemblies_have_one_that_meets_edge_to_edge(
    fixture_id: str,
) -> None:
    """rat1-flat has 101 assemblies and rat2-flat 2 (phase 5); only the answer has no T."""
    instance = instance_of(fixture_id)
    config = SolverConfig(DFS, max_solutions=None, assumptions=E2E)
    assert len(solve(instance, config).solutions) == 1


# --- the committed table and the edge graph -----------------------------------------------


@pytest.mark.slow
def test_one_command_reproduces_the_edge_to_edge_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, table = tmp_path / "edge_to_edge.jsonl", tmp_path / "edge_to_edge.md"
    arguments = ["run", str(MANIFESTS / "edge_to_edge.toml"), "--fixtures", str(corpus.FIXTURES)]
    code = main([*arguments, "--out", str(out), "--table", str(table), "--no-times", "--quiet"])
    assert code == 0, "some run could not be made"
    produced = table.read_text(encoding="utf-8")
    assert capsys.readouterr().out == produced
    assert produced == (RESULTS / "edge_to_edge.md").read_text(encoding="utf-8")
    records = benchmark.read(out)
    # Each corpus puzzle once assuming nothing, and four times assuming edge to edge.
    assert len(records) == 5 * len(EVERY)
    for record in records:
        fixture, assumed = record["fixture"], bool(record["config"]["assumptions"])
        if fixture in corpus.UNFINISHED and not assumed:
            assert record["status"] == "interrupted" and not record["exhaustive"], fixture
            assert record["metrics"]["nodes"] == NODE_LIMIT
            continue
        assert record["status"] == "solved" and record["exhaustive"], fixture
        expected = (EDGE_TO_EDGE_ASSEMBLIES if assumed else ASSEMBLIES).get(fixture, 1)
        assert record["validSolutions"] == record["solutions"] == expected, fixture


@pytest.mark.parametrize("fixture_id", EVERY)
def test_the_assumption_thins_the_edge_graph(fixture_id: str) -> None:
    """Without roofs an edge could lie against dozens of others; assuming edge to
    edge, against a few at most. That no contact of the answer key is lost is
    shown above, by the search finding the key with ``equal_edges`` on."""
    instance = instance_of(fixture_id)
    plain = proxies.static(instance)
    assumed = proxies.static(instance, edge_to_edge=True)
    assert assumed.edges == plain.edges
    assert assumed.mean_degree < plain.mean_degree
    if instance.regime is Regime.FOOTPRINT:
        assert assumed.mean_degree < plain.mean_degree / 10
