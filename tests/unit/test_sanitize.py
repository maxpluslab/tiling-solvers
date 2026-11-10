"""The sanitizer on small hand-checkable cases. Random inputs are in tests/property."""

import json
import math
import random

import pytest

from maxplus_solvers.models import Pose, Regime, Roof, ValidationConstants
from maxplus_solvers.sanitize import (
    AnswerKey,
    SolvedAssembly,
    SolvedPiece,
    _shuffled,
    derive_seed,
    sanitize,
    vertex_set_distance,
)
from support import geometry

SQUARE = ((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0))
TRIANGLE = ((-4.0, -4.0), (2.0, -4.0), (2.0, 8.0))
TARGET = ((-72.0, -72.0), (72.0, -72.0), (72.0, 72.0), (-72.0, 72.0))
CONSTANTS = ValidationConstants(1e-6, 0.006, 0.006, 0.012, 3.0, 0.02, 0.05)
FLAT_CONSTANTS = ValidationConstants(1e-6, 0.006, 0.006, 0.012, 3.0, 0.02)


def assembly(puzzle_id: str = "toy", roofs: bool = True, n: int = 6) -> SolvedAssembly:
    """Squares and triangles side by side. It need not tile: the sanitizer does not care."""
    pieces = tuple(
        SolvedPiece(
            source_id=f"{'ABCDEFGH'[i]}x",
            polygon=SQUARE if i % 2 else TRIANGLE,
            pose=Pose(10.0 * i, -5.0 * i, 0.0),
            roof=Roof(10.0 + i, 0.1 * i, -0.2) if roofs else None,
        )
        for i in range(n)
    )
    return SolvedAssembly(
        id=puzzle_id,
        target=TARGET,
        pieces=pieces,
        span_mm=144.0,
        validation=CONSTANTS if roofs else FLAT_CONSTANTS,
        relief_mm=35.0 if roofs else None,
        tropical={"convention": "max"} if roofs else None,
    )


# --- pinned randomness ----------------------------------------------------------
# Regression values, recorded once from this implementation. They guard the one
# thing no independent oracle can: that seeds keep meaning the same thing across
# Python versions and platforms. If they change, every fixture changes.


def test_the_per_puzzle_seed_is_pinned() -> None:
    assert derive_seed(20261109, "new2") == 6817999159551575417
    assert derive_seed(20261109, "new2-flat") == 15281772611622009385


def test_the_shuffle_is_pinned() -> None:
    assert _shuffled(random.Random(12345), 8) == [2, 7, 6, 5, 1, 4, 0, 3]


# --- the distance that defines "solved orientation" ------------------------------


def test_vertex_set_distance_of_a_square_turned_an_eighth() -> None:
    turned = tuple(
        (
            x * math.cos(math.pi / 4) - y * math.sin(math.pi / 4),
            x * math.sin(math.pi / 4) + y * math.cos(math.pi / 4),
        )
        for x, y in SQUARE
    )
    # Each corner moves along a circle of radius 10*sqrt(2) by 45 degrees: chord 2 r sin(22.5°).
    expected = 2 * 10 * math.sqrt(2) * math.sin(math.pi / 8)
    assert vertex_set_distance(turned, SQUARE) == pytest.approx(expected, abs=1e-12)


def test_a_square_turned_a_quarter_is_the_same_vertex_set() -> None:
    turned = tuple((-y, x) for x, y in SQUARE)
    assert vertex_set_distance(turned, SQUARE) == pytest.approx(0.0, abs=1e-12)


# --- what sanitize does ------------------------------------------------------------


def test_ids_are_opaque_and_ordered() -> None:
    instance, key = sanitize(assembly(), seed=1)
    assert [p.id for p in instance.pieces] == ["p00", "p01", "p02", "p03", "p04", "p05"]
    assert sorted(key.source_ids.values()) == ["Ax", "Bx", "Cx", "Dx", "Ex", "Fx"]
    assert list(key.poses) == [p.id for p in instance.pieces]


def test_pieces_do_not_stay_in_construction_order() -> None:
    orders = set()
    for seed in range(20):
        _, key = sanitize(assembly(), seed=seed)
        orders.add(tuple(key.source_ids.values()))
    assert len(orders) >= 19, "twenty seeds should give twenty orders, bar a coincidence"
    assert ("Ax", "Bx", "Cx", "Dx", "Ex", "Fx") not in orders


def test_the_starting_vertex_moves() -> None:
    """Over many seeds every vertex of a triangle gets to be first."""
    first_edge_lengths = set()
    for seed in range(40):
        instance, _ = sanitize(assembly(n=1), seed=seed)
        a, b = instance.pieces[0].polygon[:2]
        first_edge_lengths.add(round(math.dist(a, b), 6))
    # The triangle's sides are 6, 12 and sqrt(180).
    assert first_edge_lengths == {6.0, 12.0, round(math.sqrt(180.0), 6)}


def test_no_piece_is_left_in_its_solved_orientation_even_a_symmetric_one() -> None:
    """A square has four solved orientations; the stored one must avoid them all."""
    for seed in range(200):
        instance, key = sanitize(assembly(n=2), seed=seed)
        for piece in instance.pieces:
            stored = list(piece.polygon)
            solved = geometry.place_polygon(
                stored, {"x": 0.0, "y": 0.0, "theta": key.poses[piece.id].theta}
            )
            radius = max(math.hypot(x, y) for x, y in stored)
            assert geometry.vertex_set_distance(stored, solved) >= 0.1 * radius


def test_the_key_puts_every_piece_back() -> None:
    solved = assembly()
    instance, key = sanitize(solved, seed=3)
    by_source = {p.source_id: p for p in solved.pieces}
    for piece in instance.pieces:
        original = by_source[key.source_ids[piece.id]]
        expected = [(x + original.pose.x, y + original.pose.y) for x, y in original.polygon]
        placed = geometry.place_polygon(piece.polygon, key.poses[piece.id].to_dict())
        assert geometry.same_polygon(placed, expected, tol=1e-9)


def test_the_roof_turns_with_the_piece() -> None:
    solved = assembly()
    instance, key = sanitize(solved, seed=3)
    by_source = {p.source_id: p for p in solved.pieces}
    for piece in instance.pieces:
        original = by_source[key.source_ids[piece.id]]
        assert original.roof is not None and piece.roof is not None
        for u, v in original.polygon:
            world = (u + original.pose.x, v + original.pose.y)
            expected = original.roof.z0 + original.roof.gx * u + original.roof.gy * v
            actual = geometry.roof_height(
                piece.roof.to_dict(), key.poses[piece.id].to_dict(), world
            )
            assert actual == pytest.approx(expected, abs=1e-9)


def test_the_same_seed_gives_the_same_bytes_and_another_seed_does_not() -> None:
    first = json.dumps(sanitize(assembly(), seed=5)[0].to_dict())
    assert json.dumps(sanitize(assembly(), seed=5)[0].to_dict()) == first
    assert json.dumps(sanitize(assembly(), seed=6)[0].to_dict()) != first


def test_a_puzzle_and_its_flat_twin_get_unrelated_rotations() -> None:
    """Otherwise a flat attempt would transfer to the relief puzzle pose for pose."""
    _, relief_key = sanitize(assembly("toy"), seed=5)
    _, flat_key = sanitize(assembly("toy-flat", roofs=False), seed=5)
    relief_angles = {relief_key.source_ids[i]: p.theta for i, p in relief_key.poses.items()}
    flat_angles = {flat_key.source_ids[i]: p.theta for i, p in flat_key.poses.items()}
    assert all(abs(relief_angles[s] - flat_angles[s]) > 1e-6 for s in relief_angles)


def test_the_seed_is_in_the_key_and_not_in_the_instance() -> None:
    seed = 918273645
    instance, key = sanitize(assembly(), seed=seed)
    assert key.seed == seed
    text = json.dumps(instance.to_dict())
    assert str(seed) not in text
    assert str(derive_seed(seed, "toy")) not in text
    assert "seed" not in text.lower()


def test_the_key_is_bound_to_its_instance() -> None:
    instance, key = sanitize(assembly(), seed=5)
    assert key.instance_id == instance.id
    assert key.instance_hash == instance.instance_hash()
    assert AnswerKey.from_dict(json.loads(json.dumps(key.to_dict()))) == key


# --- regimes ---------------------------------------------------------------------


def test_the_default_regime_follows_the_roofs() -> None:
    assert sanitize(assembly(), seed=1)[0].regime is Regime.RELIEF
    assert sanitize(assembly(roofs=False), seed=1)[0].regime is Regime.FOOTPRINT


def test_regimes_of_one_puzzle_share_their_geometry() -> None:
    relief, relief_key = sanitize(assembly(), seed=9, regime="relief")
    flat, flat_key = sanitize(assembly(), seed=9, regime="footprint")
    aware, aware_key = sanitize(assembly(), seed=9, regime="tropical-aware")
    assert flat == relief.as_regime("footprint")
    assert aware.as_regime("relief") == relief
    assert flat_key.poses == relief_key.poses == aware_key.poses
    assert len({flat_key.instance_hash, relief_key.instance_hash, aware_key.instance_hash}) == 3


def test_a_footprint_instance_of_a_relief_puzzle_has_no_trace_of_the_relief() -> None:
    flat, _ = sanitize(assembly(), seed=9, regime="footprint")
    doc = flat.to_dict()
    assert "reliefMm" not in doc and "tropical" not in doc
    assert "roofMismatch" not in doc["validation"]
    assert all("roof" not in piece for piece in doc["pieces"])


def test_the_tropical_aware_instance_maps_pieces_to_terms() -> None:
    aware, key = sanitize(assembly(), seed=9, regime="tropical-aware")
    assert aware.tropical == {
        "construction": {"convention": "max"},
        "pieceTerms": dict(key.source_ids),
    }


def test_only_the_tropical_aware_instance_carries_source_ids() -> None:
    for regime in ("footprint", "relief"):
        text = json.dumps(sanitize(assembly(), seed=9, regime=regime)[0].to_dict())
        assert not any(f'"{name}x"' in text for name in "ABCDEF")
        assert "convention" not in text


def test_regimes_that_need_missing_data_are_refused() -> None:
    with pytest.raises(ValueError, match="roof"):
        sanitize(assembly(roofs=False), seed=1, regime="relief")
    with pytest.raises(ValueError, match="roof"):
        sanitize(assembly(roofs=False), seed=1, regime="tropical-aware")
    no_construction = SolvedAssembly(
        "toy", TARGET, assembly().pieces, 144.0, CONSTANTS, relief_mm=35.0
    )
    with pytest.raises(ValueError, match="construction"):
        sanitize(no_construction, seed=1, regime="tropical-aware")
