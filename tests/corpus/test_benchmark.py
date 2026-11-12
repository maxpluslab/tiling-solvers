"""Phase 7 exit criterion: one command reproduces a results table for the whole corpus.

``maxplus-bench run benchmarks/manifests/corpus.toml --no-times`` runs every
registered solver on every corpus puzzle and prints the table committed as
``benchmarks/results/corpus.md``. The table holds statuses, solution counts
and search counts, which a deterministic solver reproduces exactly; times and
CP-SAT's own counts belong to a machine and are not in it.

The other tests here hold the committed manifests to what the runner accepts,
and the difficulty proxies to what can be said about them without a search.
"""

import importlib
import itertools
from pathlib import Path
from typing import Any

import pytest

from maxplus_solvers import PuzzleInstance, solvers
from maxplus_solvers.experiments import benchmark, proxies, report
from maxplus_solvers.experiments.cli import main, proxy_table
from maxplus_solvers.experiments.manifest import expand, fixture_ids, load
from support import corpus

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "benchmarks" / "manifests"
RESULTS = ROOT / "benchmarks" / "results"
CORPUS = corpus.fixture_ids(kind="corpus")
FLAT = corpus.fixture_ids(kind="corpus", regime="footprint")
RELIEF = corpus.fixture_ids(kind="corpus", regime="relief")
HASHES = {entry["id"]: entry["instanceHash"] for entry in corpus.index()["fixtures"]}
# Where the corpus manifest stops a search that would not end.
NODE_LIMIT = 1_500_000


def by(records: list[dict[str, Any]], solver: str) -> dict[str, dict[str, Any]]:
    return {record["fixture"]: record for record in records if record["solver"] == solver}


# --- the exit criterion -------------------------------------------------------------------


@pytest.mark.slow
def test_one_command_reproduces_the_corpus_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, table = tmp_path / "corpus.jsonl", tmp_path / "corpus.md"
    arguments = ["run", str(MANIFESTS / "corpus.toml"), "--fixtures", str(corpus.FIXTURES)]
    code = main([*arguments, "--out", str(out), "--table", str(table), "--no-times", "--quiet"])
    assert code == 0, "some run could not be made"
    produced = table.read_text(encoding="utf-8")
    assert capsys.readouterr().out == produced
    assert produced == (RESULTS / "corpus.md").read_text(encoding="utf-8")

    records = benchmark.read(out)
    # The whole corpus, across all registered solvers.
    assert {record["solver"] for record in records} == set(solvers.available())
    assert sorted(by(records, "rust.contact_dfs")) == sorted(CORPUS)
    assert sorted(by(records, "cp_sat.placements")) == sorted(CORPUS)
    # The prototype's list was fixed before cor1 joined the corpus; it would stop there too.
    assert sorted(by(records, "python.contact_dfs")) == sorted(set(FLAT) - corpus.UNFINISHED)
    for record in records:
        # Whatever was returned passes the validator.
        assert record["status"] in ("solved", "interrupted"), record["fixture"]
        assert record["validSolutions"] == record["solutions"], record["fixture"]
        # Enough to run it again.
        assert record["solverVersion"]
        assert record["config"]["tolerances"]["contactNoiseMm"] > 0
        assert record["config"]["seed"] == 0
        assert record["instanceHash"] == HASHES[record["fixture"]]
    # The two production solvers finish everything but cor1-flat, stopped at the node
    # limit before it found anything; the prototype is stopped on the largest.
    for solver in ("rust.contact_dfs", "cp_sat.placements"):
        results = by(records, solver)
        unfinished = sorted(f for f, record in results.items() if not record["exhaustive"])
        assert unfinished == sorted(corpus.UNFINISHED), solver
        for fixture in unfinished:
            assert results[fixture]["status"] == "interrupted"
            assert results[fixture]["metrics"]["nodes"] == NODE_LIMIT
        # The limit is far above what any finished search needed.
        finished = [r["metrics"]["nodes"] for f, r in results.items() if f not in unfinished]
        assert max(finished) < NODE_LIMIT / 1.4
    prototype = by(records, "python.contact_dfs")
    stopped = [fixture for fixture, record in prototype.items() if not record["exhaustive"]]
    assert sorted(stopped) == ["new1-flat", "new2-flat", "rat2-flat"]
    assert all(prototype[fixture]["metrics"]["nodes"] == 50_000 for fixture in stopped)


def test_the_committed_table_is_the_reproducible_kind() -> None:
    lines = (RESULTS / "corpus.md").read_text(encoding="utf-8").splitlines()
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert header[:4] == ["Fixture", "Pieces", "Solver", "Mode"]
    assert not [title for title in header if title.endswith(", s") or "SAT" in title]
    # 18 + 18 + 8 runs, a header and a rule.
    assert len(lines) == 44 + 2


# --- the committed manifests --------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(MANIFESTS.glob("*.toml")), ids=lambda p: p.stem)
def test_every_committed_manifest_can_be_run(path: Path) -> None:
    manifest = load(path)
    assert manifest.name == path.stem
    assert manifest.description
    index = corpus.index()
    runs = list(expand(manifest, fixture_ids(manifest, index)))
    assert runs
    known = {entry["id"] for entry in index["fixtures"]}
    for run in runs:
        assert run.fixture in known
        # Every option a manifest sets is one the solver has.
        module = importlib.import_module(solvers.get(run.solver).run.__module__)
        defaults = getattr(module, "DEFAULTS", None)
        if defaults is not None:
            assert set(run.options) <= set(defaults), (path.name, run.solver, run.options)


def test_the_manifests_the_documents_name_exist() -> None:
    assert {path.stem for path in MANIFESTS.glob("*.toml")} == {
        "corpus",
        "edge_to_edge",
        "factorial",
        "smoke",
        "tolerance",
    }


def test_the_smoke_manifest_runs_every_solver(tmp_path: Path) -> None:
    records = benchmark.run(load(MANIFESTS / "smoke.toml"), corpus.FIXTURES, tmp_path / "s.jsonl")
    assert {record["solver"] for record in records} == set(solvers.available())
    assert all(record["status"] == "solved" for record in records)
    assert all(record["validSolutions"] == record["solutions"] for record in records)
    # One assembly up to turns for the production solvers; the prototype counts all four.
    assert {(record["solver"], record["solutions"]) for record in records} == {
        ("rust.contact_dfs", 1),
        ("cp_sat.placements", 1),
        ("python.contact_dfs", 4),
    }
    assert report.table(records, times=False).count("\n") == len(records) + 2


def test_the_factorial_manifest_crosses_what_the_brief_asks_for() -> None:
    """Flat against relief x tolerance x heuristic x family, on every construction."""
    manifest = load(MANIFESTS / "factorial.toml")
    runs = list(expand(manifest, fixture_ids(manifest, corpus.index())))
    assert {run.fixture for run in runs} == set(CORPUS)
    assert len({run.contact_scale for run in runs}) >= 3
    assert {run.options.get("order") for run in runs} >= {"matched-edges", "generated", "random"}
    assert {run.options.get("lookahead") for run in runs} >= {True, False}
    assert {run.max_solutions for run in runs} == {None, 1}
    assert len({run.seed for run in runs if run.options.get("order") == "random"}) >= 5


def test_the_tolerance_manifest_is_a_grid_in_two_tolerances() -> None:
    manifest = load(MANIFESTS / "tolerance.toml")
    runs = list(expand(manifest, fixture_ids(manifest, corpus.index())))
    grid = {
        (run.contact_scale, run.options["roof_tolerance_mm"])
        for run in runs
        if "roof_tolerance_mm" in run.options
    }
    scales = sorted({scale for scale, _ in grid})
    roofs = sorted({roof for _, roof in grid})
    assert len(scales) >= 4 and len(roofs) >= 4
    assert len(grid) == len(scales) * len(roofs)
    # Only puzzles with roofs have a roof tolerance to vary.
    assert {run.fixture for run in runs if "roof_tolerance_mm" in run.options} == set(RELIEF)
    # Geometric spacing: each step of the contact axis multiplies the tolerance.
    single = sorted({run.contact_scale for run in runs if not run.options})
    assert len(single) >= 6
    assert all(b / a >= 2 for a, b in itertools.pairwise(single))


# --- difficulty proxies -------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_roofs_thin_the_edge_graph(fixture_id: str) -> None:
    """A finding the proxies can state without a search.

    As footprints almost every edge could lie against almost every other; a
    roof leaves an edge a handful of mates. The polygons of a relief puzzle and
    its flat twin are the same up to rotation, so the counts of pieces and
    edges agree.
    """
    roofed = proxies.static(PuzzleInstance.from_dict(corpus.fixture(fixture_id)))
    flat = proxies.static(PuzzleInstance.from_dict(corpus.fixture(f"{fixture_id}-flat")))
    assert (roofed.pieces, roofed.edges) == (flat.pieces, flat.edges)
    assert roofed.mean_degree < flat.mean_degree / 4
    assert flat.unique_mate_fraction == 0.0
    assert roofed.symmetry_count <= flat.symmetry_count
    # The tray is a square in both.
    assert roofed.tray_turns == flat.tray_turns == 4


def test_the_proxy_table_has_a_row_for_every_corpus_puzzle() -> None:
    table, correlations = proxy_table(corpus.FIXTURES)
    lines = table.splitlines()
    assert len(lines) == len(CORPUS) + 2
    assert all(f"`{fixture_id}`" in table for fixture_id in CORPUS)
    assert "Source rating" in lines[0] and "Nodes" not in lines[0]
    assert "Spearman with source_diversity: footprint" in correlations
