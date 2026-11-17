"""Phase 7 exit criterion: one command reproduces a results table for the whole corpus.

``maxplus-bench run benchmarks/manifests/corpus.toml --no-times`` runs every
registered solver on every corpus puzzle and prints the table committed as
``benchmarks/results/corpus.md``. The table holds statuses, solution counts
and search counts, which a deterministic solver reproduces exactly; times and
CP-SAT's own counts belong to a machine and are not in it. The test runs the
same command ``--only`` on the fixtures that are cheap to search, and compares
their rows; the rows of the expensive footprints (``support/corpus.py``) are
checked by running the full command by hand.

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


def test_one_command_reproduces_the_corpus_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The committed table's rows, but for the footprints that are expensive to search.

    ``maxplus-bench run benchmarks/manifests/corpus.toml --no-times``
    reproduces the whole table; this runs the same manifest ``--only`` on the
    rest and compares those rows exactly. Left out are the expensive fixtures
    (``corpus.EXPENSIVE``: three footprints of a million nodes, and Pleat), and
    ``rat2-flat``, where CP-SAT takes over a minute.
    """
    cheap = [f for f in CORPUS if f not in corpus.EXPENSIVE_FOR_CP_SAT]
    committed = (RESULTS / "corpus.md").read_text(encoding="utf-8")
    out, table = tmp_path / "corpus.jsonl", tmp_path / "corpus.md"
    arguments = ["run", str(MANIFESTS / "corpus.toml"), "--fixtures", str(corpus.FIXTURES)]
    options = ["--out", str(out), "--table", str(table), "--no-times", "--quiet"]
    assert main([*arguments, *options, "--only", *cheap]) == 0, "some run could not be made"
    produced = table.read_text(encoding="utf-8")
    assert capsys.readouterr().out == produced
    assert produced == corpus.table_rows(committed, cheap)

    records = benchmark.read(out)
    # Those fixtures, across all registered solvers.
    assert {record["solver"] for record in records} == set(solvers.available())
    assert sorted(by(records, "rust.contact_dfs")) == sorted(cheap)
    assert sorted(by(records, "cp_sat.placements")) == sorted(cheap)
    assert sorted(by(records, "python.contact_dfs")) == sorted(set(FLAT) & set(cheap))
    for record in records:
        # Every search here ends, and whatever was returned passes the validator.
        assert record["status"] == "solved" and record["exhaustive"], record["fixture"]
        assert record["validSolutions"] == record["solutions"], record["fixture"]
        # Enough to run it again.
        assert record["solverVersion"]
        assert record["config"]["tolerances"]["contactNoiseMm"] > 0
        assert record["config"]["seed"] == 0
        assert record["instanceHash"] == HASHES[record["fixture"]]


def test_the_rows_the_suite_does_not_reproduce_say_what_the_documents_say() -> None:
    """What the committed table claims of the whole corpus, read from it.

    Not a reproduction: only the full command checks the expensive rows against
    a search. This holds the table to what the manifest and the documents say
    of it.
    """
    rows = corpus.table((RESULTS / "corpus.md").read_text(encoding="utf-8"))
    nodes = {(r["Solver"], r["Fixture"]): int(r["Nodes"].replace(" ", "")) for r in rows}
    for row in rows:
        assert row["Solutions"] == row["Valid"], (row["Solver"], row["Fixture"])
    # The two production solvers finish everything but cor1-flat and the Pleat footprints,
    # stopped at the node limit; the prototype is stopped on the largest.
    # CP-SAT is not given the Pleat footprints: it would enumerate every assembly of a
    # listing stopped at the limit (benchmarks/manifests/corpus.toml).
    given = {
        "`rust.contact_dfs`": set(CORPUS),
        "`cp_sat.placements`": set(CORPUS) - corpus.PLEAT_FLAT,
    }
    for solver, fixtures in given.items():
        mine = [row for row in rows if row["Solver"] == solver]
        assert sorted(row["Fixture"] for row in mine) == sorted(fixtures)
        unfinished = sorted(row["Fixture"] for row in mine if row["Whole search"] == "no")
        assert unfinished == sorted(corpus.UNFINISHED & fixtures), solver
        for fixture in unfinished:
            assert nodes[solver, fixture] == NODE_LIMIT
        # The limit is far above what any finished search needed.
        finished = [nodes[solver, row["Fixture"]] for row in mine if row["Whole search"] == "yes"]
        assert max(finished) < NODE_LIMIT / 1.4
    prototype = [row for row in rows if row["Solver"] == "`python.contact_dfs`"]
    # The prototype's list was fixed before cor1 joined the corpus; it would stop there too.
    assert sorted(row["Fixture"] for row in prototype) == sorted(set(FLAT) - corpus.UNFINISHED)
    stopped = sorted(row["Fixture"] for row in prototype if row["Whole search"] == "no")
    assert stopped == ["new1-flat", "new2-flat", "rat2-flat"]
    assert all(nodes["`python.contact_dfs`", fixture] == 50_000 for fixture in stopped)


def test_the_committed_table_is_the_reproducible_kind() -> None:
    lines = (RESULTS / "corpus.md").read_text(encoding="utf-8").splitlines()
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert header[:4] == ["Fixture", "Pieces", "Solver", "Mode"]
    assert not [title for title in header if title.endswith(", s") or "SAT" in title]
    # 28 + 23 + 8 runs, a header and a rule.
    assert len(lines) == 59 + 2


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
    # Only puzzles with roofs have a roof tolerance to vary. The grid was measured before
    # Pleat joined; its one assembly at 1.75 mm is in each puzzle's provenance instead.
    roofed = {run.fixture for run in runs if "roof_tolerance_mm" in run.options}
    assert roofed == set(RELIEF) - corpus.PLEAT
    # Geometric spacing: each step of the contact axis multiplies the tolerance.
    single = sorted({run.contact_scale for run in runs if not run.options})
    assert len(single) >= 6
    assert all(b / a >= 2 for a, b in itertools.pairwise(single))


# --- difficulty proxies -------------------------------------------------------------------


def static_pair(fixture_id: str) -> tuple[proxies.StaticProxies, proxies.StaticProxies]:
    roofed = proxies.static(PuzzleInstance.from_dict(corpus.fixture(fixture_id)))
    flat = proxies.static(PuzzleInstance.from_dict(corpus.fixture(f"{fixture_id}-flat")))
    return roofed, flat


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_roofs_thin_the_edge_graph(fixture_id: str) -> None:
    """A finding the proxies can state without a search.

    As footprints almost every edge could lie against almost every other; a
    roof leaves an edge a handful of mates. The polygons of a relief puzzle and
    its flat twin are the same up to rotation, so the counts of pieces and
    edges agree. Pleat was designed against this (the next test), and its
    roofs thin the graph 3.9 to 5 times where every other puzzle's do 6.5
    times or more.
    """
    roofed, flat = static_pair(fixture_id)
    assert (roofed.pieces, roofed.edges) == (flat.pieces, flat.edges)
    assert roofed.mean_degree < flat.mean_degree / (3 if fixture_id in corpus.PLEAT else 6)
    assert flat.unique_mate_fraction == 0.0
    assert roofed.symmetry_count <= flat.symmetry_count
    # The tray is a square in both.
    assert roofed.tray_turns == flat.tray_turns == 4


def test_pleat_roofs_leave_each_edge_many_mates() -> None:
    """The design of Pleat, seen by the proxies: two corner heights give every edge one of
    four height profiles, so a roof still leaves an edge many mates. Every Pleat puzzle has
    more than twice the mean degree of any other relief puzzle (16 to 24 against at most 6.7)."""
    degree = {f: static_pair(f)[0].mean_degree for f in RELIEF}
    others = max(d for f, d in degree.items() if f not in corpus.PLEAT)
    assert min(degree[f] for f in corpus.PLEAT) > 2 * others


def test_the_proxy_table_has_a_row_for_every_corpus_puzzle() -> None:
    table, correlations = proxy_table(corpus.FIXTURES)
    lines = table.splitlines()
    assert len(lines) == len(CORPUS) + 2
    assert all(f"`{fixture_id}`" in table for fixture_id in CORPUS)
    assert "Source rating" in lines[0] and "Nodes" not in lines[0]
    assert "Spearman with source_diversity: footprint" in correlations
