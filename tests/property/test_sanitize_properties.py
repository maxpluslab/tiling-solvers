"""Properties of the sanitizer over random pieces, poses, roofs and seeds.

Everything is checked on the JSON the sanitizer produces, with the test oracle.
"""

import math
import re
from typing import Any

import jsonschema
from hypothesis import assume, given
from hypothesis import strategies as st

from maxplus_solvers.models import Pose, PuzzleInstance, Roof, ValidationConstants
from maxplus_solvers.sanitize import SolvedAssembly, SolvedPiece, sanitize
from support import corpus, geometry
from support.strategies import convex_polygons, poses, roofs, seeds

TOL = 1e-9
TARGET = ((-200.0, -200.0), (200.0, -200.0), (200.0, 200.0), (-200.0, 200.0))
VALIDATOR = jsonschema.Draft202012Validator(corpus.schema())

raw_pieces = st.lists(st.tuples(convex_polygons(), poses, roofs), min_size=1, max_size=12)
puzzle_ids = st.text("abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)


def assemble(
    puzzle_id: str, raw: list[tuple[Any, Any, Any]], solved_theta: bool = False
) -> SolvedAssembly:
    pieces = tuple(
        SolvedPiece(
            source_id=f"s{i}",
            polygon=tuple(polygon),
            pose=Pose(pose["x"], pose["y"], 0.0 if solved_theta else pose["theta"]),
            roof=Roof(**roof),
        )
        for i, (polygon, pose, roof) in enumerate(raw)
    )
    return SolvedAssembly(
        id=puzzle_id,
        target=TARGET,
        pieces=pieces,
        span_mm=400.0,
        validation=ValidationConstants(1e-6, 0.006, 0.006, 0.012, 3.0, 0.02, 0.05),
        relief_mm=35.0,
        tropical={"terms": []},
    )


@given(puzzle_ids, raw_pieces, seeds)
def test_the_key_puts_every_piece_back_where_it_was(
    puzzle_id: str, raw: list[Any], seed: int
) -> None:
    instance, key = sanitize(assemble(puzzle_id, raw), seed)
    doc, key_doc = instance.to_dict(), key.to_dict()
    for piece in doc["pieces"]:
        polygon, pose, _ = raw[int(key_doc["sourceIds"][piece["id"]][1:])]
        expected = geometry.place_polygon(polygon, pose)
        placed = geometry.place_polygon(piece["polygon"], key_doc["poses"][piece["id"]])
        assert geometry.same_polygon(placed, expected, tol=TOL)


@given(puzzle_ids, raw_pieces, seeds)
def test_the_roof_surface_does_not_move(puzzle_id: str, raw: list[Any], seed: int) -> None:
    instance, key = sanitize(assemble(puzzle_id, raw), seed)
    doc, key_doc = instance.to_dict(), key.to_dict()
    for piece in doc["pieces"]:
        polygon, pose, roof = raw[int(key_doc["sourceIds"][piece["id"]][1:])]
        for vertex in polygon:
            world = geometry.place(vertex, pose)
            before = geometry.roof_height(roof, pose, world)
            after = geometry.roof_height(piece["roof"], key_doc["poses"][piece["id"]], world)
            assert math.isclose(before, after, abs_tol=TOL)


@given(puzzle_ids, raw_pieces, seeds)
def test_pieces_stay_valid_pieces(puzzle_id: str, raw: list[Any], seed: int) -> None:
    instance, key = sanitize(assemble(puzzle_id, raw), seed)
    doc, key_doc = instance.to_dict(), key.to_dict()
    for piece in doc["pieces"]:
        polygon, _, roof = raw[int(key_doc["sourceIds"][piece["id"]][1:])]
        assert geometry.is_convex_ccw(piece["polygon"])
        assert len(piece["polygon"]) == len(polygon)
        cx, cy = geometry.centroid(piece["polygon"])
        assert math.hypot(cx, cy) < TOL
        assert math.isclose(geometry.area(piece["polygon"]), geometry.area(polygon), abs_tol=1e-7)
        # A rotation keeps the height at the centroid and the steepness of the roof.
        assert piece["roof"]["z0"] == roof["z0"]
        assert math.isclose(
            math.hypot(piece["roof"]["gx"], piece["roof"]["gy"]),
            math.hypot(roof["gx"], roof["gy"]),
            abs_tol=TOL,
        )


@given(puzzle_ids, raw_pieces, seeds)
def test_ids_are_an_opaque_relabelling(puzzle_id: str, raw: list[Any], seed: int) -> None:
    instance, key = sanitize(assemble(puzzle_id, raw), seed)
    ids = [piece.id for piece in instance.pieces]
    assert ids == sorted(ids)
    assert all(re.fullmatch(r"p\d{2}", i) for i in ids)
    assert list(key.poses) == ids
    assert sorted(key.source_ids.values()) == sorted(f"s{i}" for i in range(len(raw)))
    assert key.instance_hash == instance.instance_hash()


@given(puzzle_ids, raw_pieces, seeds)
def test_no_piece_is_stored_as_it_lies_in_the_solution(
    puzzle_id: str, raw: list[Any], seed: int
) -> None:
    """With every reference theta zero, as in the corpus, no stored polygon is the solved one."""
    instance, key = sanitize(assemble(puzzle_id, raw, solved_theta=True), seed)
    for piece in instance.pieces:
        stored = list(piece.polygon)
        turn = {"x": 0.0, "y": 0.0, "theta": key.poses[piece.id].theta}
        radius = max(math.hypot(x, y) for x, y in stored)
        assert (
            geometry.vertex_set_distance(stored, geometry.place_polygon(stored, turn))
            >= 0.1 * radius
        )


@given(puzzle_ids, raw_pieces, seeds, seeds)
def test_the_output_is_a_function_of_the_seed(
    puzzle_id: str, raw: list[Any], seed: int, other: int
) -> None:
    assume(seed != other)
    solved = assemble(puzzle_id, raw)
    first, first_key = sanitize(solved, seed)
    again, again_key = sanitize(solved, seed)
    assert first.to_dict() == again.to_dict()
    assert first_key.to_dict() == again_key.to_dict()
    different, _ = sanitize(solved, other)
    assert different.to_dict()["pieces"] != first.to_dict()["pieces"]


@given(puzzle_ids, raw_pieces, seeds, st.sampled_from(["footprint", "relief", "tropical-aware"]))
def test_every_regime_satisfies_the_schema_and_round_trips(
    puzzle_id: str, raw: list[Any], seed: int, regime: str
) -> None:
    instance, _ = sanitize(assemble(puzzle_id, raw), seed, regime)
    doc = instance.to_dict()
    VALIDATOR.validate(doc)
    assert PuzzleInstance.from_dict(doc) == instance
    assert ("tropical" in doc) == (regime == "tropical-aware")
    assert all(("roof" in piece) == (regime != "footprint") for piece in doc["pieces"])
