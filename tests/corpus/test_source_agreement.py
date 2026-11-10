"""The fixtures against the puzzles they were imported from.

These need a checkout of tropical-puzzle-lab: beside this repository, or at the
path in ``TROPICAL_PUZZLE_LAB``. Without one they are skipped locally and fail in CI.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from support import corpus, geometry

pytestmark = pytest.mark.source

CORPUS = corpus.fixture_ids(kind="corpus")


def test_the_importer_reproduces_the_committed_fixtures(source_repo: Path) -> None:
    """Fails when the fixtures, the keys, the importer or the pinned source commit drift apart."""
    done = subprocess.run(
        [
            sys.executable,
            str(corpus.ROOT / "scripts" / "import_fixtures.py"),
            "--check",
            "--source",
            str(source_repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("fixture_id", CORPUS)
def test_the_key_is_the_source_reference_assembly(fixture_id: str, source_repo: Path) -> None:
    source = corpus.read_json(source_repo / "puzzles" / fixture_id / "puzzle.json")
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    assert fixture["source"]["geometryHash"] == source["geometryHash"]

    pieces = {piece["id"]: piece for piece in source["pieces"]}
    poses = {pose["id"]: pose for pose in source["reference"]["poses"]}
    assert sorted(key["sourceIds"].values()) == sorted(pieces)

    for piece in fixture["pieces"]:
        original = pieces[key["sourceIds"][piece["id"]]]
        reference = poses[original["id"]]
        expected = geometry.place_polygon(original["polygon"], reference)
        actual = geometry.place_polygon(piece["polygon"], key["poses"][piece["id"]])
        assert geometry.same_polygon(actual, expected, tol=1e-9), piece["id"]
        if "roof" in original:
            for vertex in expected:
                before = geometry.roof_height(original["roof"], reference, vertex)
                after = geometry.roof_height(piece["roof"], key["poses"][piece["id"]], vertex)
                assert after == pytest.approx(before, abs=1e-9), piece["id"]
        else:
            assert "roof" not in piece


@pytest.mark.parametrize("fixture_id", CORPUS)
def test_everything_else_in_the_source_was_left_behind(fixture_id: str, source_repo: Path) -> None:
    source = corpus.read_json(source_repo / "puzzles" / fixture_id / "puzzle.json")
    fixture = corpus.fixture(fixture_id)
    assert fixture["spanMm"] == source["geometry"]["spanMm"]
    assert fixture["target"]["vertices"] == source["geometry"]["target"]["vertices"]
    assert fixture["validation"] == source["validation"]
    assert fixture.get("reliefMm") == source["geometry"].get("reliefMm")
    carried = {"id", "formatVersion", "rules", "validation", "tropical", "pieces"}
    assert set(source) & set(fixture) <= carried
    assert "tropical" not in fixture
