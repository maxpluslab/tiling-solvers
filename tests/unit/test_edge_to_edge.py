"""The edge-to-edge assumption, on puzzles whose assemblies can be listed by hand.

Two 72 by 144 mm strips fill the 144 mm tray in one way, side by side, meeting
along a whole edge. A 144 by 72 mm block and two 72 mm squares also fill it in
one way, and in that one the squares' shared corner is in the middle of the
block's edge (``support.documents.block_and_squares``). The assumption keeps
the first and has nothing to return for the second.
"""

import json
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
    cli,
    solve,
)
from maxplus_solvers.experiments import report
from maxplus_solvers.experiments.manifest import ManifestError, expand, parse
from support import documents, geometry

DFS = "rust.contact_dfs"
E2E = (Assumption.EDGE_TO_EDGE,)
TRAY = [(-72.0, -72.0), (72.0, -72.0), (72.0, 72.0), (-72.0, 72.0)]


def strips() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.footprint())


def block_and_squares() -> PuzzleInstance:
    return PuzzleInstance.from_dict(documents.block_and_squares())


def everything(assumptions: tuple[Assumption, ...] = (), **options: Any) -> SolverConfig:
    return SolverConfig(DFS, max_solutions=None, assumptions=assumptions, options=options)


def placed(instance: PuzzleInstance, result: SolveResult) -> list[Any]:
    return [
        [piece.world_polygon(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]


# --- the oracle ---------------------------------------------------------------------------


def test_the_oracle_tells_a_t_from_a_shared_edge() -> None:
    left = [(-72.0, -72.0), (0.0, -72.0), (0.0, 72.0), (-72.0, 72.0)]
    right = [(0.0, -72.0), (72.0, -72.0), (72.0, 72.0), (0.0, 72.0)]
    assert geometry.is_edge_to_edge([left, right], TRAY, 1e-6)
    # The right half cut across: its two parts' shared corner (0, 0) is inside left's edge.
    lower = [(0.0, -72.0), (72.0, -72.0), (72.0, 0.0), (0.0, 0.0)]
    upper = [(0.0, 0.0), (72.0, 0.0), (72.0, 72.0), (0.0, 72.0)]
    assert not geometry.is_edge_to_edge([left, lower, upper], TRAY, 1e-6)
    # An edge with no twin at all, in the open: a piece missing.
    assert not geometry.is_edge_to_edge([left], TRAY, 1e-6)


# --- what the search finds ----------------------------------------------------------------


def test_two_strips_are_found_with_the_assumption_and_without() -> None:
    instance = strips()
    plain = solve(instance, everything())
    assumed = solve(instance, everything(E2E))
    assert placed(instance, plain) == placed(instance, assumed)
    assert len(assumed.solutions) == 1
    assert geometry.is_edge_to_edge(placed(instance, assumed)[0], TRAY, 1e-6)


def test_a_block_and_two_squares_fit_only_in_a_t() -> None:
    instance = block_and_squares()
    plain = solve(instance, everything(), validate=True)
    assert plain.status is SolveStatus.SOLVED and len(plain.solutions) == 1
    assert plain.solutions[0].valid is True
    assert not geometry.is_edge_to_edge(placed(instance, plain)[0], TRAY, 1e-6)
    for equal_edges in (True, False):
        for wall_edges in (True, False):
            options = {"equal_edges": equal_edges, "wall_edges": wall_edges}
            assumed = solve(instance, everything(E2E, **options))
            assert assumed.status is SolveStatus.NO_SOLUTION_FOUND, options
            assert assumed.exhaustive, options


def test_the_rules_that_follow_from_the_assumption_are_counted() -> None:
    assumed = solve(block_and_squares(), everything(E2E))
    # The block has no partner for its long edges, so it never leaves the wall;
    # along the wall the squares can only stand where they make a T with it.
    assert assumed.metrics["rejected_wall"] > 0
    without_rules = solve(block_and_squares(), everything(E2E, wall_edges=False))
    assert without_rules.metrics["rejected_wall"] == 0
    assert without_rules.metrics["rejected_junction"] > 0
    # Without the assumption the counts are not there at all, rather than zero.
    plain = solve(block_and_squares(), everything())
    assert "rejected_junction" not in plain.metrics and "rejected_wall" not in plain.metrics


# --- what a result records ----------------------------------------------------------------


def test_a_result_names_its_assumption_and_its_own_candidate_set() -> None:
    plain = solve(strips(), everything())
    assumed = solve(strips(), everything(E2E))
    assert plain.assumptions == () and plain.candidate_set == "corner-contact/1"
    assert assumed.assumptions == E2E
    assert assumed.candidate_set == "corner-contact-edge-to-edge/1"
    relief = solve(
        PuzzleInstance.from_dict(documents.relief()),
        SolverConfig(DFS, mode=Regime.RELIEF, max_solutions=None, assumptions=E2E),
    )
    assert relief.candidate_set == "corner-contact-relief-edge-to-edge/1"
    again = SolveResult.from_dict(json.loads(json.dumps(assumed.to_dict())))
    assert again == assumed
    assert again.config is not None and again.config.assumptions == E2E


def test_a_record_from_before_assumptions_reads_as_making_none() -> None:
    document = solve(strips(), everything()).to_dict()
    del document["assumptions"]
    assert document["config"] is not None
    del document["config"]["assumptions"]
    old = SolveResult.from_dict(document)
    assert old.assumptions == () and old.config is not None and old.config.assumptions == ()


def test_assumptions_are_kept_in_one_order_and_once() -> None:
    config = SolverConfig(DFS, assumptions=("edge-to-edge", Assumption.EDGE_TO_EDGE))  # type: ignore[arg-type]
    assert config.assumptions == E2E


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda: SolverConfig(DFS, assumptions=("convex",)), "convex"),  # type: ignore[arg-type]
        (lambda: SolverConfig(DFS, assumptions="edge-to-edge"), "not one string"),  # type: ignore[arg-type]
    ],
)
def test_an_assumption_that_is_not_one_is_refused(make: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make()


def test_its_rules_mean_nothing_without_the_assumption() -> None:
    with pytest.raises(ValueError, match="only mean something under the edge-to-edge"):
        solve(strips(), everything(equal_edges=False))
    with pytest.raises(ValueError, match="wall_edges must be true or false"):
        solve(strips(), everything(E2E, wall_edges="yes"))


@pytest.mark.parametrize("solver", ["python.contact_dfs", "cp_sat.placements"])
def test_a_solver_that_cannot_make_the_assumption_refuses_it(solver: str) -> None:
    with pytest.raises(ValueError, match="cannot assume edge-to-edge"):
        solve(strips(), SolverConfig(solver, assumptions=E2E))


# --- the command line and the experiments -------------------------------------------------


def test_the_command_line_takes_the_assumption_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "block.json"
    path.write_text(json.dumps(documents.block_and_squares()), encoding="utf-8")
    assert cli.main([str(path), "--max-solutions", "all"]) == cli.SOLVED
    capsys.readouterr()
    code = cli.main([str(path), "--max-solutions", "all", "--assume", "edge-to-edge"])
    assert code == cli.NOT_SOLVED
    out = capsys.readouterr().out
    assert "corner-contact-edge-to-edge/1" in out
    assert "assuming edge-to-edge" in out


def test_a_manifest_crosses_the_assumption_with_its_other_factors() -> None:
    data = {
        "name": "hand",
        "fixtures": ["corpus"],
        "runs": [{"solver": DFS, "assume": ["none", "edge-to-edge"], "seeds": [0, 1]}],
    }
    runs = list(expand(parse(data), ["toy"]))
    assert [(r.assume, r.seed) for r in runs] == [
        ("none", 0),
        ("none", 1),
        ("edge-to-edge", 0),
        ("edge-to-edge", 1),
    ]
    data["runs"][0]["assume"] = "convex"
    with pytest.raises(ManifestError, match="neither 'none' nor an assumption"):
        parse(data)


def test_a_table_always_shows_the_assumption_when_one_is_made() -> None:
    def record(assumptions: list[str]) -> dict[str, Any]:
        return {
            "fixture": "toy",
            "pieces": 2,
            "solver": DFS,
            "mode": "footprint",
            "contactScale": 1.0,
            "config": {"seed": 0, "options": {}, "assumptions": assumptions},
            "status": "solved",
            "exhaustive": True,
            "solutions": 1,
            "metrics": {"nodes": 3},
        }

    assert "assumes" not in report.rows([record([])])[0]
    # Shown even when every row makes the same one: those rows say something narrower.
    header, row = report.rows([record(["edge-to-edge"])])
    assert row[header.index("assumes")] == "edge-to-edge"
    header, *rows = report.rows([record([]), record(["edge-to-edge"])])
    assert [r[header.index("assumes")] for r in rows] == ["nothing", "edge-to-edge"]
