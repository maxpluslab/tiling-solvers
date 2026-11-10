"""Instance files on disk, and ``load_puzzle``."""

import json
from pathlib import Path

import pytest

from maxplus_solvers import InstanceError, PuzzleInstance, Regime, load_puzzle
from maxplus_solvers.api import FIXTURES_ENV
from maxplus_solvers.io.instance import dump_instance, format_json, load_instance, save_instance
from support import documents


def test_formatting_keeps_a_coordinate_pair_on_one_line() -> None:
    text = format_json({"polygon": [[1.5, -2.0], [3.0, 4.0]], "empty": [], "none": {}})
    assert text == (
        '{\n  "polygon": [\n    [1.5, -2.0],\n    [3.0, 4.0]\n  ],\n  "empty": [],\n  "none": {}\n}'
    )


def test_formatting_refuses_nan() -> None:
    with pytest.raises(ValueError):
        format_json({"x": float("nan")})


def test_save_then_load_gives_the_same_instance(tmp_path: Path) -> None:
    instance = PuzzleInstance.from_dict(documents.with_source(documents.relief()))
    path = tmp_path / "nested" / "strips.json"
    save_instance(instance, path)
    assert load_instance(path) == instance
    assert json.loads(path.read_text(encoding="utf-8")) == instance.to_dict()


def test_files_are_written_with_lf_and_a_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "strips.json"
    save_instance(PuzzleInstance.from_dict(documents.footprint()), path)
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"}\n")
    assert raw.decode("utf-8") == dump_instance(PuzzleInstance.from_dict(documents.footprint()))


def test_loading_names_the_file_that_is_wrong(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(InstanceError, match=r"broken\.json"):
        load_instance(broken)

    doc = documents.footprint()
    doc["reference"] = {"poses": []}
    leaking = tmp_path / "leaking.json"
    leaking.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(InstanceError, match=r"leaking\.json.*reference"):
        load_instance(leaking)


# --- load_puzzle --------------------------------------------------------------


@pytest.fixture
def fixtures_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    save_instance(PuzzleInstance.from_dict(documents.relief()), tmp_path / "strips.json")
    monkeypatch.setenv(FIXTURES_ENV, str(tmp_path))
    return tmp_path


def test_load_puzzle_takes_a_path(fixtures_dir: Path) -> None:
    for path in (fixtures_dir / "strips.json", str(fixtures_dir / "strips.json")):
        assert load_puzzle(path).to_dict() == documents.relief()


def test_load_puzzle_takes_a_fixture_id(fixtures_dir: Path) -> None:
    assert load_puzzle("strips").to_dict() == documents.relief()


def test_load_puzzle_looks_under_the_current_directory_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FIXTURES_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    instance = PuzzleInstance.from_dict(documents.footprint())
    save_instance(instance, tmp_path / "benchmarks" / "fixtures" / "strips.json")
    assert load_puzzle("strips") == instance


def test_load_puzzle_can_reduce_the_regime_but_not_raise_it(fixtures_dir: Path) -> None:
    flat = load_puzzle("strips", regime="footprint")
    assert flat.regime is Regime.FOOTPRINT
    assert flat.to_dict() == documents.footprint()
    with pytest.raises(InstanceError):
        load_puzzle("strips", regime="tropical-aware")


def test_load_puzzle_reports_an_unknown_id(fixtures_dir: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no-such-puzzle"):
        load_puzzle("no-such-puzzle")
