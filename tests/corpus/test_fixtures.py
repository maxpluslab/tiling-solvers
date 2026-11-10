"""Every committed fixture, checked as it sits on disk. This is the phase 1 exit criterion.

A fixture must load, satisfy the schema, and give nothing away: no reference
poses, no construction data, no source piece ids, no seed, and no piece stored
in the orientation it has in the solution. The answer keys are held to the same
standard from the other side: they must actually solve their fixture.

Raw JSON and the test oracle only, apart from the tests that are about the loader.
"""

import json
import math
import re
from typing import Any

import jsonschema
import pytest

from maxplus_solvers import PuzzleInstance, Regime, load_puzzle
from support import corpus, geometry

ALL = corpus.fixture_ids()
CORPUS = corpus.fixture_ids(kind="corpus")
SYNTHETIC = corpus.fixture_ids(kind="synthetic")
RELIEF = corpus.fixture_ids(regime="relief")

# Keys that would carry the answer or the construction, anywhere in a fixture.
FORBIDDEN_KEYS = {
    "reference", "poses", "pose", "theta", "tropical", "construction", "pieceTerms", "terms",
    "numerator", "denominator", "provenance", "recipe", "recipeHash", "scramble", "seed",
    "defaultSeed", "sanitizer", "name", "description", "notes", "thickness", "sourceIds",
    "solutionCount",
}  # fmt: skip
MM = 1e-9


def keys_in(document: Any) -> set[str]:
    if isinstance(document, dict):
        return set(document).union(*(keys_in(v) for v in document.values()))
    if isinstance(document, list):
        return set().union(*(keys_in(v) for v in document))
    return set()


def placed(fixture: dict[str, Any], key: dict[str, Any]) -> dict[str, list[tuple[float, float]]]:
    return {
        piece["id"]: geometry.place_polygon(piece["polygon"], key["poses"][piece["id"]])
        for piece in fixture["pieces"]
    }


# --- the collection --------------------------------------------------------------


def test_the_corpus_is_complete() -> None:
    """Eight constructions in two variants, and the four synthetics."""
    constructions = ["new1", "new2", "new3", "new4", "new5", "rat1", "rat2", "rev2"]
    assert sorted(CORPUS) == sorted(constructions + [f"{c}-flat" for c in constructions])
    assert sorted(SYNTHETIC) == [
        "syn-four-squares", "syn-four-triangles", "syn-two-rectangles", "syn-two-rectangles-ridge",
    ]  # fmt: skip
    counts = {entry["id"]: entry["pieceCount"] for entry in corpus.index()["fixtures"]}
    assert {c: counts[c] for c in constructions} == {
        "new1": 16, "new2": 16, "new3": 9, "new4": 9, "new5": 6, "rat1": 11, "rat2": 20, "rev2": 9,
    }  # fmt: skip


def test_files_and_manifest_agree() -> None:
    on_disk = sorted(p.stem for p in corpus.FIXTURES.glob("*.json") if p.name != "index.json")
    assert on_disk == sorted(ALL)
    assert sorted(p.stem for p in corpus.KEYS.glob("*.json")) == sorted(ALL)
    for entry in corpus.index()["fixtures"]:
        fixture = corpus.fixture(entry["id"])
        assert entry["regime"] == fixture["regime"]
        assert entry["pieceCount"] == len(fixture["pieces"])
        assert entry["instanceHash"] == corpus.key(entry["id"])["instanceHash"]


def test_flat_variants_are_footprint_and_the_others_relief() -> None:
    for fixture_id in CORPUS:
        expected = "footprint" if fixture_id.endswith("-flat") else "relief"
        assert corpus.fixture(fixture_id)["regime"] == expected


# --- loading -----------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_fixture_satisfies_the_schema(fixture_id: str) -> None:
    jsonschema.Draft202012Validator(corpus.schema()).validate(corpus.fixture(fixture_id))


@pytest.mark.parametrize("fixture_id", ALL)
def test_fixture_loads_and_is_canonical(fixture_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAXPLUS_FIXTURES", str(corpus.FIXTURES))
    instance = load_puzzle(fixture_id)
    assert isinstance(instance, PuzzleInstance)
    assert instance.id == fixture_id
    # Loading and writing back reproduces the file: nothing is lost or reordered.
    assert instance.to_dict() == corpus.fixture(fixture_id)
    assert load_puzzle(corpus.FIXTURES / f"{fixture_id}.json") == instance
    assert load_puzzle(fixture_id, regime="footprint").regime is Regime.FOOTPRINT


@pytest.mark.parametrize("fixture_id", ALL)
def test_key_is_bound_to_its_fixture(fixture_id: str) -> None:
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    assert key["instanceId"] == fixture_id
    assert key["instanceHash"] == PuzzleInstance.from_dict(fixture).instance_hash()
    assert sorted(key["poses"]) == sorted(piece["id"] for piece in fixture["pieces"])
    assert sorted(key["sourceIds"]) == sorted(key["poses"])


# --- nothing leaks -------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_fixture_has_no_field_that_could_carry_the_answer(fixture_id: str) -> None:
    assert keys_in(corpus.fixture(fixture_id)) & FORBIDDEN_KEYS == set()


@pytest.mark.parametrize("fixture_id", ALL)
def test_piece_ids_are_opaque(fixture_id: str) -> None:
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    ids = [piece["id"] for piece in fixture["pieces"]]
    assert ids == [f"p{i:02d}" for i in range(len(ids))]
    # No source id appears as a JSON string anywhere in the fixture.
    text = json.dumps(fixture)
    for source_id in key["sourceIds"].values():
        assert f'"{source_id}"' not in text


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_seed_is_not_in_the_fixture(fixture_id: str) -> None:
    seed = corpus.key(fixture_id)["sanitizer"]["seed"]
    assert re.search(rf"(?<!\d){seed}(?!\d)", json.dumps(corpus.fixture(fixture_id))) is None


@pytest.mark.parametrize("fixture_id", [f for f in ALL if len(corpus.fixture(f)["pieces"]) >= 6])
def test_pieces_are_not_in_construction_order(fixture_id: str) -> None:
    order = list(corpus.key(fixture_id)["sourceIds"].values())
    assert order != sorted(order)
    assert order != sorted(order, reverse=True)


@pytest.mark.parametrize("fixture_id", ALL)
def test_no_piece_is_stored_in_its_solved_orientation(fixture_id: str) -> None:
    """Turning a stored polygon by its key angle must move it visibly.

    Measured between vertex sets, so that a symmetric piece counts as solved in
    each of its equivalent orientations. A tenth of the circumradius is a turn of
    about six degrees.
    """
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    for piece in fixture["pieces"]:
        turn = {"x": 0.0, "y": 0.0, "theta": key["poses"][piece["id"]]["theta"]}
        solved = geometry.place_polygon(piece["polygon"], turn)
        radius = max(math.hypot(x, y) for x, y in piece["polygon"])
        distance = geometry.vertex_set_distance(piece["polygon"], solved)
        assert distance >= 0.1 * radius, piece["id"]


@pytest.mark.parametrize("fixture_id", CORPUS)
def test_a_puzzle_and_its_flat_twin_are_sanitized_independently(fixture_id: str) -> None:
    if fixture_id.endswith("-flat"):
        return
    key, twin = corpus.key(fixture_id), corpus.key(f"{fixture_id}-flat")
    angle = {key["sourceIds"][i]: pose["theta"] for i, pose in key["poses"].items()}
    twin_angle = {twin["sourceIds"][i]: pose["theta"] for i, pose in twin["poses"].items()}
    assert sorted(angle) == sorted(twin_angle)
    assert all(abs(angle[s] - twin_angle[s]) > 1e-6 for s in angle)
    assert list(key["sourceIds"].values()) != list(twin["sourceIds"].values())


# --- the geometry is sound -------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_polygons_are_convex_counter_clockwise_and_centred(fixture_id: str) -> None:
    fixture = corpus.fixture(fixture_id)
    assert geometry.is_convex_ccw(fixture["target"]["vertices"])
    for piece in fixture["pieces"]:
        assert geometry.is_convex_ccw(piece["polygon"]), piece["id"]
        cx, cy = geometry.centroid(piece["polygon"])
        assert math.hypot(cx, cy) < MM, piece["id"]


@pytest.mark.parametrize("fixture_id", CORPUS)
def test_corpus_puzzles_have_the_published_tray_and_tolerances(fixture_id: str) -> None:
    fixture = corpus.fixture(fixture_id)
    assert fixture["spanMm"] == 144.0
    assert fixture["target"]["vertices"] == [
        [-72.0, -72.0],
        [72.0, -72.0],
        [72.0, 72.0],
        [-72.0, 72.0],
    ]
    assert min(len(p["polygon"]) for p in fixture["pieces"]) >= 3
    assert max(len(p["polygon"]) for p in fixture["pieces"]) <= 8
    expected = {
        "contactNoise": 1e-06, "overlapDepth": 0.006, "outsideDepth": 0.006,
        "areaError": 0.012, "edgeAngleDeg": 3, "edgeMinOverlap": 0.02,
    }  # fmt: skip
    if fixture["regime"] == "relief":
        expected["roofMismatch"] = 0.05
    assert fixture["validation"] == expected
    assert re.fullmatch(r"[0-9a-f]{40}", fixture["source"]["commit"])
    assert fixture["source"]["commit"] == corpus.index()["source"]["commit"]
    assert fixture["source"]["puzzleId"] == fixture_id
    assert re.fullmatch(r"[0-9a-f]{64}", fixture["source"]["geometryHash"])


# --- the keys solve their fixtures --------------------------------------------------------
# A light check here: areas, containment and roof continuity at shared corners.
# The full completion check, with pairwise overlap, is the validator's job in phase 2.


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_keyed_assembly_fills_the_target(fixture_id: str) -> None:
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    target = fixture["target"]["vertices"]
    total = 0.0
    for polygon in placed(fixture, key).values():
        total += geometry.area(polygon)
        for vertex in polygon:
            assert geometry.outside_depth(vertex, target) < MM
    assert total == pytest.approx(geometry.area(target), abs=1e-6)


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_the_keyed_roofs_meet_at_every_shared_corner(fixture_id: str) -> None:
    """Where pieces share a corner, their roofs have one height there.

    This fails if a roof gradient was not turned together with its piece.
    """
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    roofs = {piece["id"]: piece["roof"] for piece in fixture["pieces"]}
    corners: list[tuple[tuple[float, float], str]] = [
        (vertex, piece_id)
        for piece_id, polygon in placed(fixture, key).items()
        for vertex in polygon
    ]
    shared = 0
    for i, (point, first) in enumerate(corners):
        for other_point, second in corners[i + 1 :]:
            if first == second or math.dist(point, other_point) > 1e-6:
                continue
            shared += 1
            a = geometry.roof_height(roofs[first], key["poses"][first], point)
            b = geometry.roof_height(roofs[second], key["poses"][second], point)
            assert a == pytest.approx(b, abs=1e-6), (first, second)
    assert shared >= len(fixture["pieces"]) - 1, "too few shared corners for this to mean anything"


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_roof_heights_stay_within_the_relief(fixture_id: str) -> None:
    fixture, key = corpus.fixture(fixture_id), corpus.key(fixture_id)
    heights = [
        geometry.roof_height(piece["roof"], key["poses"][piece["id"]], vertex)
        for piece in fixture["pieces"]
        for vertex in geometry.place_polygon(piece["polygon"], key["poses"][piece["id"]])
    ]
    assert max(heights) - min(heights) == pytest.approx(fixture["reliefMm"], abs=1e-6)
    assert min(heights) > 0


# --- synthetics --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_id", "canonical", "assemblies"),
    [
        ("syn-two-rectangles", 1, 4),
        ("syn-two-rectangles-ridge", 1, 4),
        ("syn-four-squares", 1, 1),
        ("syn-four-triangles", 1, 1),
    ],
)
def test_synthetic_keys_record_their_solution_counts(
    fixture_id: str, canonical: int, assemblies: int
) -> None:
    assert corpus.key(fixture_id)["solutionCount"] == {
        "canonical": canonical,
        "assemblies": assemblies,
    }
    assert "source" not in corpus.fixture(fixture_id)


@pytest.mark.parametrize("fixture_id", CORPUS)
def test_corpus_keys_claim_no_solution_count(fixture_id: str) -> None:
    """Uniqueness of the corpus puzzles is an open question, not a recorded fact."""
    assert "solutionCount" not in corpus.key(fixture_id)
