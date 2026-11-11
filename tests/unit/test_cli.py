"""The ``maxplus-solve`` command, run in process on hand-written instance files."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from maxplus_solvers import SolveResult, cli
from support import documents


@pytest.fixture
def strips(tmp_path: Path) -> Path:
    path = tmp_path / "strips.json"
    path.write_text(json.dumps(documents.footprint()), encoding="utf-8")
    return path


@pytest.fixture
def unfillable(tmp_path: Path) -> Path:
    doc = documents.footprint()
    doc["pieces"][1]["polygon"] = [[-30.0, -72.0], [30.0, -72.0], [30.0, 72.0], [-30.0, 72.0]]
    path = tmp_path / "unfillable.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_solved_puzzle_exits_zero_and_says_what_is_claimed(
    strips: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(strips)]) == cli.SOLVED
    out = capsys.readouterr().out
    assert "rust.contact_dfs" in out and "(footprint): solved" in out
    assert "stopped before its end" in out
    assert "first solution after" in out and "search finished after" not in out
    assert "not proven complete" in out
    assert "solution 1: 2 pieces, not validated" in out


def test_all_solutions_with_validation(strips: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Upright and lying are a quarter turn of the tray apart: one assembly, or two."""
    assert cli.main([str(strips), "--max-solutions", "all", "--validate"]) == cli.SOLVED
    out = capsys.readouterr().out
    assert "ran to its end" in out
    assert "solution 1: 2 pieces, valid" in out and "solution 2" not in out
    assert "first solution after" in out and "search finished after" in out

    arguments = [str(strips), "--max-solutions", "all", "--validate"]
    assert cli.main([*arguments, "--option", "tray_rotations=all"]) == cli.SOLVED
    out = capsys.readouterr().out
    assert "solution 2: 2 pieces, valid" in out and "solution 3" not in out

    assert cli.main([*arguments, "--solver", "python.contact_dfs"]) == cli.SOLVED
    out = capsys.readouterr().out
    assert "python.contact_dfs" in out and "solution 2: 2 pieces, valid" in out


def test_json_output_is_a_result_document(strips: Path, capsys: pytest.CaptureFixture[str]) -> None:
    arguments = ["--json", "--seed", "5", "--max-solutions", "2"]
    options = ["--option", "tray_rotations=all", "--option", "lookahead=false"]
    assert cli.main([str(strips), *arguments, *options]) == cli.SOLVED
    result = SolveResult.from_dict(json.loads(capsys.readouterr().out))
    assert len(result.solutions) == 2
    assert result.config is not None
    assert (result.config.seed, result.config.max_solutions) == (5, 2)
    # A word stays a word, and JSON is read as JSON.
    assert result.config.options == {"tray_rotations": "all", "lookahead": False}


def test_no_solution_exits_one(unfillable: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([str(unfillable), "--max-solutions", "all"]) == cli.NOT_SOLVED
    assert "no_solution_found" in capsys.readouterr().out


def test_a_fixture_is_found_by_id(
    strips: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAXPLUS_FIXTURES", str(strips.parent))
    assert cli.main(["strips"]) == cli.SOLVED
    assert "solved" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--solver", "rust.nothing"], "invalid choice"),
        (["--mode", "relief"], "cannot turn a footprint instance"),
        (["--solver", "python.contact_dfs", "--mode", "relief"], "does not work in relief mode"),
        (["--option", "nonsense=1"], "unknown options nonsense"),
        (["--option", "lookahead"], "must be NAME=VALUE"),
        (["--option", "lookahead=perhaps"], "lookahead must be true or false"),
        (["--max-solutions", "0"], "must be at least 1"),
        (["--time-limit", "-1"], "time_limit_s must be positive"),
    ],
)
def test_bad_arguments_are_usage_errors(
    strips: Path, arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main([str(strips), *arguments])
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err


def test_a_missing_puzzle_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["no-such-puzzle"])
    assert stopped.value.code == 2
    assert "neither a file nor a fixture id" in capsys.readouterr().err


def test_an_invalid_solution_exits_three(
    strips: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A solver whose answer fails validation must not look like a success."""
    from dataclasses import replace

    from maxplus_solvers import Pose, Solution, solvers

    real = solvers.get("rust.contact_dfs")

    def overlapping(instance, config):  # type: ignore[no-untyped-def]
        result = real.run(instance, config)
        stacked = {piece.id: Pose(0.0, 0.0, 0.0) for piece in instance.pieces}
        return replace(result, solutions=(Solution(stacked),))

    monkeypatch.setitem(solvers._REGISTRY, real.name, replace(real, run=overlapping))
    assert cli.main([str(strips), "--validate"]) == cli.INVALID
    assert "INVALID" in capsys.readouterr().out


def test_the_command_is_installed(strips: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "maxplus_solvers.cli", str(strips), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(done.stdout)["status"] == "solved"
