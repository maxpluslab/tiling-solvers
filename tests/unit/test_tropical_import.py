"""The source importer, on a hand-made puzzle so the suite needs no other repository.

``tests/data/source/mini`` is a 12 mm square cut into a 6 by 12 strip (``Ab``) and
two triangles (``Ac``, ``Bd``) along the line y = 2x - 6. Its roof is the
continuous piecewise-affine surface

    Ab: 10 + x/2        Bd: 10 - x/2        Ac: 11.5 - x + y/4

so heights at world points can be worked out by hand.
"""

import copy
import json
from typing import Any

import jsonschema
import pytest

from maxplus_solvers.io.tropical import SOURCE_REPOSITORY, import_puzzle, read_source
from maxplus_solvers.models import InstanceError, Regime
from support import corpus, geometry

WORLD = {
    "Ab": [(0.0, -6.0), (0.0, 6.0), (-6.0, 6.0), (-6.0, -6.0)],
    "Ac": [(0.0, -6.0), (6.0, -6.0), (6.0, 6.0)],
    "Bd": [(0.0, -6.0), (6.0, 6.0), (0.0, 6.0)],
}
HEIGHT = {
    "Ab": lambda x, y: 10.0 + 0.5 * x,
    "Ac": lambda x, y: 11.5 - x + 0.25 * y,
    "Bd": lambda x, y: 10.0 - 0.5 * x,
}
LEAKS = ("reference", "provenance", "scramble", "name", "description", "thickness", "poses")


@pytest.fixture
def source() -> dict[str, Any]:
    return read_source(corpus.MINI_SOURCE)


def flat_variant(source: dict[str, Any]) -> dict[str, Any]:
    """What the generator publishes as the tiling variant of the same construction."""
    flat = copy.deepcopy(source)
    flat["id"] = "mini-flat"
    flat["variant"] = "tiling"
    del flat["geometry"]["reliefMm"], flat["geometry"]["minThicknessMm"]
    del flat["validation"]["roofMismatch"]
    for piece in flat["pieces"]:
        del piece["roof"]
        piece["thickness"] = 12.0
    return flat


def test_the_mini_source_is_what_its_description_says(source: dict[str, Any]) -> None:
    """Guard the hand-made file itself, with the oracle only."""
    poses = {p["id"]: p for p in source["reference"]["poses"]}
    for piece in source["pieces"]:
        cx, cy = geometry.centroid(piece["polygon"])
        assert abs(cx) < 1e-12 and abs(cy) < 1e-12
        placed = geometry.place_polygon(piece["polygon"], poses[piece["id"]])
        assert geometry.same_polygon(placed, WORLD[piece["id"]], tol=1e-12)
        for x, y in placed:
            height = geometry.roof_height(piece["roof"], poses[piece["id"]], (x, y))
            assert height == pytest.approx(HEIGHT[piece["id"]](x, y), abs=1e-12)
    assert sum(geometry.area(p["polygon"]) for p in source["pieces"]) == pytest.approx(144.0)


def test_a_relief_puzzle_imports_as_relief(source: dict[str, Any]) -> None:
    instance, key = import_puzzle(source, seed=11, commit="abc123")
    assert instance.id == "mini"
    assert instance.regime is Regime.RELIEF
    assert instance.span_mm == 12.0
    assert instance.relief_mm == 6.0
    assert list(instance.target) == [(-6.0, -6.0), (6.0, -6.0), (6.0, 6.0), (-6.0, 6.0)]
    assert instance.validation.to_dict() == source["validation"]
    assert instance.rules.to_dict() == {"translate": True, "rotate": "continuous-z", "flip": False}
    assert sorted(key.source_ids.values()) == ["Ab", "Ac", "Bd"]


def test_the_source_reference_is_recorded(source: dict[str, Any]) -> None:
    instance, _ = import_puzzle(source, seed=11, commit="abc123")
    assert instance.source is not None
    assert instance.source.to_dict() == {
        "repository": SOURCE_REPOSITORY,
        "commit": "abc123",
        "puzzleId": "mini",
        "geometryHash": "mini-geometry-hash",
    }


def test_the_key_reproduces_the_reference_assembly(source: dict[str, Any]) -> None:
    instance, key = import_puzzle(source, seed=11, commit="abc123")
    for piece in instance.pieces:
        placed = geometry.place_polygon(piece.polygon, key.poses[piece.id].to_dict())
        assert geometry.same_polygon(placed, WORLD[key.source_ids[piece.id]], tol=1e-9)


def test_roof_heights_survive_the_import(source: dict[str, Any]) -> None:
    instance, key = import_puzzle(source, seed=11, commit="abc123")
    for piece in instance.pieces:
        name = key.source_ids[piece.id]
        assert piece.roof is not None
        for x, y in WORLD[name]:
            height = geometry.roof_height(
                piece.roof.to_dict(), key.poses[piece.id].to_dict(), (x, y)
            )
            assert height == pytest.approx(HEIGHT[name](x, y), abs=1e-9)


@pytest.mark.parametrize("regime", ["footprint", "relief"])
def test_nothing_that_gives_the_answer_away_is_imported(
    source: dict[str, Any], regime: str
) -> None:
    instance, _ = import_puzzle(source, seed=11, commit="abc123", regime=regime)
    text = json.dumps(instance.to_dict())
    for word in (*LEAKS, '"tropical"', "numerator", "Mini", '"Ab"', '"Ac"', '"Bd"'):
        assert word not in text, word
    jsonschema.Draft202012Validator(corpus.schema()).validate(instance.to_dict())


def test_a_flat_puzzle_imports_as_footprint(source: dict[str, Any]) -> None:
    instance, key = import_puzzle(flat_variant(source), seed=11, commit="abc123")
    assert instance.id == "mini-flat"
    assert instance.regime is Regime.FOOTPRINT
    assert instance.relief_mm is None
    assert all(piece.roof is None for piece in instance.pieces)
    for piece in instance.pieces:
        placed = geometry.place_polygon(piece.polygon, key.poses[piece.id].to_dict())
        assert geometry.same_polygon(placed, WORLD[key.source_ids[piece.id]], tol=1e-9)


def test_a_flat_puzzle_cannot_be_imported_with_roofs(source: dict[str, Any]) -> None:
    for regime in ("relief", "tropical-aware"):
        with pytest.raises(ValueError, match="roof"):
            import_puzzle(flat_variant(source), seed=11, commit="abc123", regime=regime)


def test_the_tropical_aware_import_keeps_the_construction_apart(source: dict[str, Any]) -> None:
    aware, key = import_puzzle(source, seed=11, commit="abc123", regime="tropical-aware")
    assert aware.regime is Regime.TROPICAL_AWARE
    assert aware.tropical is not None
    assert aware.tropical["construction"] == source["tropical"]
    assert aware.tropical["pieceTerms"] == dict(key.source_ids)
    jsonschema.Draft202012Validator(corpus.schema()).validate(aware.to_dict())
    # Everything outside the `tropical` field is the plain relief instance.
    relief, _ = import_puzzle(source, seed=11, commit="abc123")
    assert aware.as_regime("relief") == relief


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("format version", lambda d: d.update(formatVersion=2)),
        ("variant", lambda d: d.update(variant="relief-v2")),
        ("units", lambda d: d["geometry"].update(units="in")),
        ("model", lambda d: d["geometry"].update(model="spherical")),
        ("target type", lambda d: d["geometry"]["target"].update(type="circle")),
        ("snapping", lambda d: d["rules"].update(snap=True)),
        ("flipping", lambda d: d["rules"].update(flip=True)),
        (
            "a pose without a piece",
            lambda d: d["reference"]["poses"].append({"id": "Zz", "x": 0, "y": 0, "theta": 0}),
        ),
    ],
)
def test_an_unfamiliar_source_is_refused_not_guessed_at(
    source: dict[str, Any], name: str, change: Any
) -> None:
    change(source)
    with pytest.raises(InstanceError):
        import_puzzle(source, seed=11, commit="abc123")
