"""The experiments package on inputs small enough to check by hand.

Manifests are expanded and counted by hand; the runner is run on the three
strips of ``support.documents``, whose assemblies are known; tables and rank
correlations are compared with values written out here.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from maxplus_solvers import PuzzleInstance, SolverConfig, solve
from maxplus_solvers.experiments import benchmark, proxies, report
from maxplus_solvers.experiments.cli import main
from maxplus_solvers.experiments.manifest import ManifestError, expand, fixture_ids, load, parse
from support import documents

INDEX = {
    "fixtures": [
        {"id": "strips", "kind": "corpus", "regime": "footprint", "construction": "strips"},
        {"id": "strips-relief", "kind": "corpus", "regime": "relief", "construction": "strips"},
        {"id": "toy", "kind": "synthetic", "regime": "footprint"},
    ]
}


def manifest_of(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "hand",
        "fixtures": ["corpus"],
        "runs": [{"solver": "rust.contact_dfs"}],
    }
    data.update(changes)
    return data


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """A fixture directory holding the three strips, with and without roofs."""
    flat = documents.three_strips()
    flat["id"] = "strips"
    roofed = documents.three_strips_relief()
    roofed["id"] = "strips-relief"
    entries = []
    for doc in (flat, roofed):
        (tmp_path / f"{doc['id']}.json").write_text(json.dumps(doc), encoding="utf-8")
        entries.append(
            {
                "id": doc["id"],
                "kind": "corpus",
                "regime": doc["regime"],
                "pieceCount": 3,
                "construction": "strips",
                "sourceDifficulty": {"diversity": 1.0, "x": 0.5, "rating": 1},
            }
        )
    (tmp_path / "index.json").write_text(json.dumps({"fixtures": entries}), encoding="utf-8")
    return tmp_path


# --- manifests ----------------------------------------------------------------------------


def test_a_block_stands_for_the_product_of_its_factors() -> None:
    """2 modes x 2 scales x 3 seeds x 2 orders x 1 lookahead = 24 runs a fixture, by hand."""
    manifest = parse(
        manifest_of(
            runs=[
                {
                    "solver": "rust.contact_dfs",
                    "mode": ["own", "footprint"],
                    "contact_scale": [1.0, 10.0],
                    "seeds": [0, 1, 2],
                    "max_solutions": 1,
                    "time_limit_s": 5,
                    "options": {"order": ["generated", "random"], "lookahead": True},
                }
            ]
        )
    )
    runs = list(expand(manifest, ["a", "b"]))
    assert len(runs) == 2 * 24
    assert [run.fixture for run in runs] == ["a"] * 24 + ["b"] * 24
    # The order is fixed: mode, then scale, then seed, then the options as written.
    assert [(r.mode, r.contact_scale, r.seed, r.options["order"]) for r in runs[:3]] == [
        ("own", 1.0, 0, "generated"),
        ("own", 1.0, 0, "random"),
        ("own", 1.0, 1, "generated"),
    ]
    assert runs[23].mode == "footprint" and runs[23].contact_scale == 10.0
    assert all(run.options["lookahead"] is True for run in runs)
    assert all(run.max_solutions == 1 and run.time_limit_s == 5.0 for run in runs)
    assert len({(r.mode, r.contact_scale, r.seed, r.options["order"]) for r in runs[:24]}) == 24


def test_a_plain_block_is_one_whole_search_per_fixture() -> None:
    manifest = parse(manifest_of())
    (run,) = expand(manifest, ["a"])
    assert (run.mode, run.seed, run.contact_scale, run.options) == ("own", 0, 1.0, {})
    assert run.max_solutions is None and run.time_limit_s is None
    assert manifest.validate is True


def test_groups_name_fixtures_by_kind_in_index_order() -> None:
    assert fixture_ids(parse(manifest_of(fixtures=["corpus"])), INDEX) == [
        "strips",
        "strips-relief",
    ]
    assert fixture_ids(parse(manifest_of(fixtures=["synthetic"])), INDEX) == ["toy"]
    assert fixture_ids(parse(manifest_of(fixtures=["all"])), INDEX) == [
        "strips",
        "strips-relief",
        "toy",
    ]
    assert fixture_ids(parse(manifest_of(fixtures=["toy", "strips"])), INDEX) == ["strips", "toy"]


def test_a_block_can_keep_to_some_of_the_fixtures() -> None:
    manifest = parse(
        manifest_of(
            fixtures=["all"],
            runs=[
                {"solver": "rust.contact_dfs"},
                {"solver": "python.contact_dfs", "fixtures": ["toy"]},
            ],
        )
    )
    runs = list(expand(manifest, fixture_ids(manifest, INDEX)))
    assert [(r.solver, r.fixture) for r in runs] == [
        ("rust.contact_dfs", "strips"),
        ("rust.contact_dfs", "strips-relief"),
        ("rust.contact_dfs", "toy"),
        ("python.contact_dfs", "toy"),
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": ""}, "needs a name"),
        ({"fixtures": []}, "expected a list of fixture ids or groups"),
        ({"fixtures": "corpus"}, "expected a list of fixture ids or groups"),
        ({"runs": []}, "at least one"),
        ({"colour": "red"}, "unknown keys colour"),
        ({"validate": "yes"}, "expected true or false"),
        ({"runs": [{"solver": "rust.magic"}]}, "is not registered"),
        ({"runs": [{"solver": "rust.contact_dfs", "nodes": 3}]}, "unknown keys nodes"),
        ({"runs": [{"solver": "rust.contact_dfs", "mode": "tall"}]}, "neither 'own' nor a regime"),
        ({"runs": [{"solver": "rust.contact_dfs", "max_solutions": 0}]}, "positive integer or"),
        ({"runs": [{"solver": "rust.contact_dfs", "time_limit_s": -1}]}, "positive number"),
        ({"runs": [{"solver": "rust.contact_dfs", "seeds": [-1]}]}, "is not a seed"),
        ({"runs": [{"solver": "rust.contact_dfs", "seeds": []}]}, "empty list"),
        ({"runs": [{"solver": "rust.contact_dfs", "contact_scale": [0]}]}, "positive number"),
        ({"runs": [{"solver": "rust.contact_dfs", "options": {"order": []}}]}, "empty list"),
    ],
)
def test_a_manifest_it_does_not_understand_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        parse(manifest_of(**changes))


def test_a_fixture_nobody_has_is_refused() -> None:
    with pytest.raises(ManifestError, match="'nowhere' is neither a fixture id nor a group"):
        fixture_ids(parse(manifest_of(fixtures=["nowhere"])), INDEX)
    block = {"solver": "rust.contact_dfs", "fixtures": ["nowhere"]}
    with pytest.raises(ManifestError, match="'nowhere' is not a fixture id"):
        fixture_ids(parse(manifest_of(runs=[block])), INDEX)


def test_a_manifest_file_that_is_not_toml_says_where(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("name = \n", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"broken\.toml"):
        load(path)


# --- the runner ---------------------------------------------------------------------------


def run_hand(fixtures_dir: Path, **changes: Any) -> list[dict[str, Any]]:
    return benchmark.run(parse(manifest_of(**changes)), fixtures_dir)


def test_a_record_says_what_was_run_and_what_came_of_it(fixtures_dir: Path) -> None:
    flat, roofed = run_hand(fixtures_dir)
    # The strips stand in 6 orders, 3 up to the tray's half turn; one order under roofs.
    assert (flat["fixture"], flat["mode"], flat["solutions"]) == ("strips", "footprint", 3)
    assert (roofed["fixture"], roofed["mode"], roofed["solutions"]) == (
        "strips-relief",
        "relief",
        1,
    )
    for record in (flat, roofed):
        assert record["manifest"] == "hand"
        assert record["status"] == "solved" and record["exhaustive"] is True
        assert record["validSolutions"] == record["solutions"]
        assert record["candidatesProvenComplete"] is False
        assert record["pieces"] == 3 and record["construction"] == "strips"
        assert record["solverVersion"].count(".") == 2
        assert set(record["environment"]) == {"python", "platform"}
        assert record["metrics"]["nodes"] > 0
        assert record["worstResiduals"]["overlap_depth_mm"] == pytest.approx(0.0, abs=1e-9)
    assert flat["candidateSet"] == "corner-contact/1"
    assert roofed["worstResiduals"]["roof_mismatch_mm"] == pytest.approx(0.0, abs=1e-9)
    # The hash is of the instance as the solver saw it.
    instance = PuzzleInstance.from_dict(documents.three_strips())
    assert flat["instanceHash"] != instance.instance_hash(), "the id is part of the hash"
    renamed = documents.three_strips()
    renamed["id"] = "strips"
    assert flat["instanceHash"] == PuzzleInstance.from_dict(renamed).instance_hash()


def test_a_record_is_enough_to_run_it_again(fixtures_dir: Path) -> None:
    block = {
        "solver": "rust.contact_dfs",
        "seeds": [5],
        "contact_scale": [10.0],
        "options": {"order": "random", "tray_rotations": "all"},
    }
    (record, _) = run_hand(fixtures_dir, runs=[block])
    config = SolverConfig.from_dict(record["config"])
    assert (config.seed, config.max_solutions) == (5, None)
    assert config.options == {"order": "random", "tray_rotations": "all"}
    # The contact noise is 1e-6 of the 120 mm span, times ten; the rest is the player's.
    assert config.tolerances is not None
    assert config.tolerances.contact_noise_mm == pytest.approx(1.2e-3, abs=1e-12)
    assert config.tolerances.overlap_depth_mm == pytest.approx(0.006 * 120.0, abs=1e-12)
    assert record["contactScale"] == 10.0

    doc = documents.three_strips()
    doc["id"] = "strips"
    again = solve(PuzzleInstance.from_dict(doc), config)
    assert again.instance_hash == record["instanceHash"]
    assert len(again.solutions) == record["solutions"] == 6
    for count in ("nodes", "backtracks", "backtrack_depth", "placements", "candidates_generated"):
        assert again.metrics[count] == record["metrics"][count], count


def test_a_regime_the_fixture_lacks_is_left_out(fixtures_dir: Path) -> None:
    """Asking for relief: the footprint fixture has none, and is not run."""
    records = run_hand(fixtures_dir, runs=[{"solver": "rust.contact_dfs", "mode": "relief"}])
    assert [record["fixture"] for record in records] == ["strips-relief"]
    # Asking for footprint runs both, the roofed one with its roofs hidden.
    records = run_hand(fixtures_dir, runs=[{"solver": "rust.contact_dfs", "mode": "footprint"}])
    assert [(r["fixture"], r["mode"], r["solutions"]) for r in records] == [
        ("strips", "footprint", 3),
        ("strips-relief", "footprint", 3),
    ]
    assert records[1]["fixtureRegime"] == "relief"
    assert "roof_mismatch_mm" not in records[1]["worstResiduals"]


def test_a_run_that_cannot_be_made_is_recorded_and_the_rest_goes_on(fixtures_dir: Path) -> None:
    """The prototype has no relief regime: an error for the roofed strips, not a crash."""
    records = run_hand(
        fixtures_dir,
        runs=[
            {"solver": "python.contact_dfs"},
            {"solver": "rust.contact_dfs", "options": {"speed": "fast"}},
        ],
    )
    assert [(r["solver"], r["fixture"], r["status"]) for r in records] == [
        ("python.contact_dfs", "strips", "solved"),
        ("python.contact_dfs", "strips-relief", "error"),
        ("rust.contact_dfs", "strips", "error"),
        ("rust.contact_dfs", "strips-relief", "error"),
    ]
    assert "does not work in relief mode" in records[1]["error"]
    assert "unknown options speed" in records[2]["error"]
    assert "metrics" not in records[1]


def test_without_validation_nothing_is_called_valid(fixtures_dir: Path) -> None:
    (flat, _) = run_hand(fixtures_dir, validate=False)
    assert flat["solutions"] == 3
    assert flat["validSolutions"] is None and flat["worstResiduals"] == {}


def test_limits_are_passed_on(fixtures_dir: Path) -> None:
    block = {"solver": "rust.contact_dfs", "max_solutions": 1, "options": {"node_limit": 1}}
    (flat, _) = run_hand(fixtures_dir, runs=[block])
    assert flat["status"] == "interrupted" and flat["exhaustive"] is False
    assert flat["metrics"]["nodes"] == 1
    first = run_hand(fixtures_dir, runs=[{"solver": "rust.contact_dfs", "max_solutions": 1}])[0]
    assert first["solutions"] == 1 and first["exhaustive"] is False


def test_results_are_written_as_json_lines_and_read_back(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out" / "hand.jsonl"
    out.parent.mkdir()
    seen: list[str] = []
    records = benchmark.run(
        parse(manifest_of()), fixtures_dir, out, progress=lambda r: seen.append(r["fixture"])
    )
    assert seen == ["strips", "strips-relief"]
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(line.startswith("{") for line in lines)
    assert benchmark.read(out) == records


# --- tables -------------------------------------------------------------------------------


def record_of(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fixture": "strips",
        "pieces": 3,
        "solver": "rust.contact_dfs",
        "mode": "footprint",
        "contactScale": 1.0,
        "config": {"seed": 0, "options": {}},
        "status": "solved",
        "exhaustive": True,
        "solutions": 3,
        "validSolutions": 3,
        "metrics": {
            "nodes": 1200,
            "backtracks": 8,
            "backtrack_depth": 20,
            "candidates_generated": 3000,
            "first_solution_s": 0.25,
            "wall_time_s": 1.5,
        },
    }
    record.update(changes)
    return record


def test_a_table_has_a_row_for_each_run() -> None:
    cells = report.rows([record_of()])
    assert cells[0][:4] == ["Fixture", "Pieces", "Solver", "Mode"]
    row = dict(zip(cells[0], cells[1], strict=True))
    assert row["Fixture"] == "`strips`" and row["Solver"] == "`rust.contact_dfs`"
    assert (row["Status"], row["Whole search"], row["Solutions"], row["Valid"]) == (
        "solved",
        "yes",
        "3",
        "3",
    )
    # 1200 with a thin space for thousands; 20 / 8 and 3000 / 1200 by hand.
    assert row["Nodes"] == "1 200"
    assert row["Mean dead-end depth"] == "2.50"
    assert row["Candidates per node"] == "2.50"
    assert (row["First solution, s"], row["Total, s"]) == ("0.25", "1.5")


def test_the_reproducible_table_has_no_times() -> None:
    header = report.rows([record_of()], times=False)[0]
    assert not [title for title in header if title.endswith(", s") or "SAT" in title]
    assert "Nodes" in header
    text = report.table([record_of()], times=False)
    assert text.count("\n") == 3 and text.splitlines()[1].startswith("| --- |")
    assert "1.5" not in text and "0.25" not in text


def test_settings_that_vary_become_columns() -> None:
    records = [
        record_of(config={"seed": 0, "options": {"order": "random", "lookahead": False}}),
        record_of(config={"seed": 1, "options": {"order": "generated", "lookahead": False}}),
        record_of(
            config={"seed": 1, "options": {"order": "generated", "lookahead": False}},
            contactScale=100.0,
        ),
    ]
    assert report.varied(records) == ["order", "seed", "contactScale"]
    cells = report.rows(records)
    assert cells[0][4:7] == ["order", "seed", "contactScale"]
    assert [row[4:7] for row in cells[1:]] == [
        ["random", "0", "1"],
        ["generated", "1", "1"],
        ["generated", "1", "100"],
    ]
    assert report.varied([record_of(), record_of()]) == []


def test_an_error_has_a_row_and_no_numbers() -> None:
    cells = report.rows([record_of(status="error", error="ValueError: no")])
    assert len(cells[1]) == len(cells[0])
    assert cells[1][4] == "error" and set(cells[1][5:]) == {""}


def test_a_search_with_no_dead_end_has_no_mean_depth() -> None:
    metrics = {"nodes": 4, "backtracks": 0, "backtrack_depth": 0, "candidates_generated": 8}
    cells = report.rows([record_of(metrics=metrics)], times=False)
    row = dict(zip(cells[0], cells[1], strict=True))
    assert row["Mean dead-end depth"] == "" and row["Candidates per node"] == "2.00"


# --- rank correlation ---------------------------------------------------------------------


def test_ranks_share_a_tie() -> None:
    assert report.ranks([10.0, 30.0, 20.0]) == [1.0, 3.0, 2.0]
    # The two 5s span ranks 2 and 3 and get 2.5 each.
    assert report.ranks([5.0, 1.0, 5.0, 9.0]) == [2.5, 1.0, 2.5, 4.0]


def test_spearman_by_hand() -> None:
    assert report.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0, abs=1e-12)
    assert report.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == pytest.approx(-1.0, abs=1e-12)
    # Ranks 1 2 3 4 5 against 2 1 4 3 5: d = 1 1 1 1 0, 1 - 6 * 4 / (5 * 24) = 0.8.
    assert report.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8, abs=1e-12)
    # With a tie. x ranks 1 2.5 2.5 4, y ranks 1 2 3 4: means 2.5, deviations
    # (-1.5, 0, 0, 1.5) and (-1.5, -0.5, 0.5, 1.5); 4.5 / sqrt(4.5 * 5) = 0.9487.
    assert report.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(
        4.5 / math.sqrt(22.5), abs=1e-12
    )


def test_spearman_declines_what_has_no_answer() -> None:
    assert report.spearman([1, 2], [2, 1]) is None
    assert report.spearman([3, 3, 3], [1, 2, 3]) is None
    with pytest.raises(ValueError, match="different sizes"):
        report.spearman([1, 2, 3], [1, 2])


# --- proxies ------------------------------------------------------------------------------


def test_tray_turns_by_hand() -> None:
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    rectangle = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]
    scalene = [(0.0, 0.0), (5.0, 0.0), (1.0, 3.0)]
    h = math.sqrt(3.0) / 2
    equilateral = [(0.0, 0.0), (1.0, 0.0), (0.5, h)]
    assert proxies.tray_turns(square, 1e-9) == 4
    assert proxies.tray_turns(rectangle, 1e-9) == 2
    assert proxies.tray_turns(scalene, 1e-9) == 1
    assert proxies.tray_turns(equilateral, 1e-9) == 3


def test_the_static_proxies_of_the_three_strips() -> None:
    """Three rectangles of different widths in a rectangular tray.

    12 edges. No two strips are congruent: 3 classes, 1 way to exchange. Each
    is its own half turn: 2 * 2 * 2 = 8 ways to turn pieces onto themselves.
    The tray has a half turn: 2. So 16 descriptions of one assembly.
    """
    found = proxies.static(PuzzleInstance.from_dict(documents.three_strips()))
    assert (found.pieces, found.edges, found.classes) == (3, 12, 3)
    assert (found.exchanges, found.piece_turns, found.tray_turns) == (1, 8, 2)
    assert found.symmetry_count == 16
    assert found.to_dict()["symmetry_count"] == 16
    # Every strip's 72 mm side can lie against the 72 mm sides of the other two.
    assert found.max_degree >= 4
    assert 0.0 <= found.unique_mate_fraction <= 1.0
    assert 0.0 < found.mean_tray_degree <= 4.0


def test_roofs_take_away_symmetry_and_mates() -> None:
    """Under a sloping roof a strip is no longer its own half turn: 1 * 1 * 1 turns."""
    flat = proxies.static(PuzzleInstance.from_dict(documents.three_strips()))
    roofed = proxies.static(PuzzleInstance.from_dict(documents.three_strips_relief()))
    assert roofed.piece_turns == 1 and roofed.symmetry_count == 2
    assert roofed.mean_degree < flat.mean_degree
    assert roofed.edges == flat.edges


def test_twins_can_change_places() -> None:
    doc = documents.three_strips()
    # Make the first two strips both 30 wide: 30 + 30 + 60 still fills the tray.
    for index in (0, 1):
        doc["pieces"][index]["polygon"] = [
            [-15.0, -36.0],
            [15.0, -36.0],
            [15.0, 36.0],
            [-15.0, 36.0],
        ]
    found = proxies.static(PuzzleInstance.from_dict(doc))
    assert (found.classes, found.exchanges) == (2, 2)


def test_the_dynamic_proxies_are_read_from_a_record() -> None:
    found = proxies.dynamic(record_of())
    assert found == {
        "mean_dead_end_depth": 2.5,
        "dead_end_depth_fraction": pytest.approx(2.5 / 3, abs=1e-12),
        "candidates_per_node": 2.5,
        "nodes": 1200,
    }
    assert proxies.dynamic(record_of(status="error", metrics={})) == {}


def test_correlations_use_the_fixtures_that_have_both() -> None:
    table = {
        "a": {"pieces": 1.0, "nodes": 10.0, "edges": 5.0},
        "b": {"pieces": 2.0, "nodes": 20.0, "edges": 4.0},
        "c": {"pieces": 3.0, "nodes": 30.0, "edges": 3.0},
        "d": {"pieces": 9.0, "edges": 0.0},
    }
    found = {name: (value, count) for name, value, count in proxies.correlations(table, "nodes")}
    assert found["pieces"] == (pytest.approx(1.0, abs=1e-12), 3)
    assert found["edges"] == (pytest.approx(-1.0, abs=1e-12), 3)
    assert "nodes" not in found
    # A proxy no fixture has is listed, without a coefficient.
    assert found["classes"] == (None, 0)
    assert set(found) == proxies.PROXY_NAMES - {"nodes"}


def test_every_proxy_has_a_name_the_correlations_know() -> None:
    static = proxies.static(PuzzleInstance.from_dict(documents.three_strips())).to_dict()
    assert set(static) <= proxies.PROXY_NAMES
    assert set(proxies.dynamic(record_of())) <= proxies.PROXY_NAMES


# --- the command --------------------------------------------------------------------------


def write_manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hand.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_command_runs_a_manifest_and_prints_its_table(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = write_manifest(
        tmp_path, 'name = "hand"\nfixtures = ["corpus"]\n[[runs]]\nsolver = "rust.contact_dfs"\n'
    )
    out, table = tmp_path / "r" / "hand.jsonl", tmp_path / "t" / "hand.md"
    arguments = ["run", str(manifest), "--fixtures", str(fixtures_dir), "--out", str(out)]
    code = main([*arguments, "--table", str(table), "--no-times"])
    assert code == 0
    printed = capsys.readouterr()
    assert printed.out == table.read_text(encoding="utf-8")
    assert "| `strips` | 3 | `rust.contact_dfs` | footprint | solved | yes | 3 | 3 |" in printed.out
    # Each run is reported as it ends, apart from the table.
    assert printed.err.count("solved") == 2
    assert len(benchmark.read(out)) == 2

    assert main(["table", str(out), "--no-times"]) == 0
    assert capsys.readouterr().out == table.read_text(encoding="utf-8")


def test_the_command_fails_when_a_run_could_not_be_made(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = write_manifest(
        tmp_path, 'name = "hand"\nfixtures = ["corpus"]\n[[runs]]\nsolver = "python.contact_dfs"\n'
    )
    out = tmp_path / "hand.jsonl"
    code = main(
        ["run", str(manifest), "--fixtures", str(fixtures_dir), "--out", str(out), "--quiet"]
    )
    assert code == 1
    assert "| error |" in capsys.readouterr().out


def test_the_command_refuses_a_manifest_it_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = write_manifest(tmp_path, 'name = "hand"\nfixtures = ["corpus"]\n')
    with pytest.raises(SystemExit) as stopped:
        main(["run", str(manifest)])
    assert stopped.value.code == 2
    assert "at least one" in capsys.readouterr().err


def test_the_proxies_command_prints_a_table_and_correlations(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["proxies", "--fixtures", str(fixtures_dir)]) == 0
    printed = capsys.readouterr().out
    assert "| `strips` | 3 | 12 |" in printed
    assert "Spearman with source_diversity: footprint" in printed
    # With results, the searches' own numbers join the table.
    out = tmp_path / "hand.jsonl"
    benchmark.run(parse(manifest_of()), fixtures_dir, out)
    assert main(["proxies", "--fixtures", str(fixtures_dir), "--results", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Mean dead-end depth" in printed and "Spearman with nodes: footprint" in printed
