"""The Rust geometry kernel through ``_native``, on inputs small enough to work out by hand."""

import math
from typing import Any

import pytest

import maxplus_solvers
from maxplus_solvers import _native

UNIT_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
SQUARE = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
REST = (0.0, 0.0, 0.0)


def shifted(polygon: list[tuple[float, float]], dx: float, dy: float) -> list[tuple[float, float]]:
    return [(x + dx, y + dy) for x, y in polygon]


def test_version_matches_the_package() -> None:
    assert _native.version() == maxplus_solvers.__version__
    assert maxplus_solvers.__version__.count(".") == 2


# --- polygons -----------------------------------------------------------------------------


def test_signed_area_is_positive_counter_clockwise() -> None:
    assert _native.signed_area(UNIT_SQUARE) == pytest.approx(1.0, abs=1e-12)
    assert _native.signed_area(UNIT_SQUARE[::-1]) == pytest.approx(-1.0, abs=1e-12)


def test_polygons_may_be_lists_or_tuples_of_ints() -> None:
    # Legs 4 and 3: half of 12.
    assert _native.signed_area([(0, 0), (4, 0), (0, 3)]) == pytest.approx(6.0, abs=1e-12)
    assert _native.signed_area([[0, 0], [4, 0], [0, 3]]) == pytest.approx(6.0, abs=1e-12)


def test_centroid_of_a_right_triangle_is_a_third_along_each_leg() -> None:
    assert _native.centroid([(0, 0), (6, 0), (0, 3)]) == pytest.approx((2.0, 1.0), abs=1e-12)


def test_convexity() -> None:
    assert _native.is_convex_ccw(SQUARE)
    assert not _native.is_convex_ccw(SQUARE[::-1])
    assert not _native.is_convex_ccw(SQUARE[:2])
    # A dent at the bottom.
    assert not _native.is_convex_ccw([(-3, -3), (0, -1), (3, -3), (3, 3), (-3, 3)])
    # A vertex in the middle of a side.
    assert not _native.is_convex_ccw([(0, 0), (1, 0), (2, 0), (2, 2), (0, 2)])


def test_transform_turns_then_shifts() -> None:
    # A quarter turn takes (1, 0) to (0, 1) and (0, 1) to (-1, 0); then add (10, 20).
    moved = _native.transform([(1, 0), (0, 1), (-1, -1)], (10.0, 20.0, math.pi / 2))
    assert moved[0] == pytest.approx((10.0, 21.0), abs=1e-12)
    assert moved[1] == pytest.approx((9.0, 20.0), abs=1e-12)
    assert moved[2] == pytest.approx((11.0, 19.0), abs=1e-12)
    assert all(isinstance(point, tuple) for point in moved)


def test_containment_includes_the_boundary() -> None:
    assert _native.contains_point(SQUARE, (1.0, 1.0))
    assert _native.contains_point(SQUARE, (2.0, 1.0))
    assert _native.contains_point(SQUARE, (0.0, 0.0))
    assert not _native.contains_point(SQUARE, (2.001, 1.0))


def test_outside_depth_is_euclidean_beyond_a_corner() -> None:
    # 3 right of and 4 above the corner (2, 2): 5 away, though only 4 past the nearer wall.
    assert _native.point_outside_depth((5.0, 6.0), SQUARE) == pytest.approx(5.0, abs=1e-12)
    assert _native.point_outside_depth((5.0, 1.0), SQUARE) == pytest.approx(3.0, abs=1e-12)
    assert _native.point_outside_depth((1.0, 1.0), SQUARE) == 0.0
    assert _native.outside_depth(shifted(SQUARE, 0.5, 0.0), SQUARE) == pytest.approx(0.5, abs=1e-12)
    assert _native.outside_depth(SQUARE, SQUARE) == 0.0


# --- pairs of polygons --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [
        (0.7, 0.0, 0.3),  # overlap 0.3 wide: slide 0.3 to separate
        (0.7, 0.9, 0.1),  # 0.3 by 0.1: the short way out is 0.1
        (1.0, 0.0, 0.0),  # sharing an edge
        (1.0, 1.0, 0.0),  # sharing a corner
        (1.5, 0.0, -0.5),  # half a unit apart
        (0.0, 0.0, 1.0),  # coincident
    ],
)
def test_penetration_depth_of_two_unit_squares(dx: float, dy: float, expected: float) -> None:
    other = shifted(UNIT_SQUARE, dx, dy)
    assert _native.penetration_depth(UNIT_SQUARE, other) == pytest.approx(expected, abs=1e-12)
    assert _native.penetration_depth(other, UNIT_SQUARE) == pytest.approx(expected, abs=1e-12)


def test_a_nested_square_is_as_deep_as_the_way_out() -> None:
    """A unit square 3 from the left wall of a 10 by 10: leaving takes 4, not the shared 1."""
    big = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    small = shifted(UNIT_SQUARE, 3.0, 4.5)
    assert _native.penetration_depth(big, small) == pytest.approx(4.0, abs=1e-12)


def test_overlapping_squares_share_a_rectangle() -> None:
    # Shifted by (1.5, 0.5): the shared part is 0.5 wide and 1.5 high.
    other = shifted(SQUARE, 1.5, 0.5)
    assert _native.intersection_area(SQUARE, other) == pytest.approx(0.75, abs=1e-12)
    assert _native.outside_area(other, SQUARE) == pytest.approx(4.0 - 0.75, abs=1e-12)
    shared = _native.intersection(SQUARE, other)
    corners = [(1.5, 0.5), (1.5, 2.0), (2.0, 0.5), (2.0, 2.0)]
    assert len(shared) == 4
    for found, corner in zip(sorted(shared), corners, strict=True):
        assert found == pytest.approx(corner, abs=1e-12)
    assert _native.is_convex_ccw(shared)


def test_a_square_and_a_diamond_share_an_octagon() -> None:
    # The diamond |x-1| + |y-1| <= 1.5 cuts a corner triangle with legs 0.5 off each corner.
    diamond = [(1.0, -0.5), (2.5, 1.0), (1.0, 2.5), (-0.5, 1.0)]
    assert len(_native.intersection(SQUARE, diamond)) == 8
    assert _native.intersection_area(SQUARE, diamond) == pytest.approx(3.5, abs=1e-12)


def test_polygons_that_only_touch_or_are_apart_share_nothing() -> None:
    assert _native.intersection_area(SQUARE, shifted(SQUARE, 2.0, 0.0)) == 0.0
    assert _native.intersection_area(SQUARE, shifted(SQUARE, 2.0, 2.0)) == 0.0
    assert _native.intersection(SQUARE, shifted(SQUARE, 5.0, 0.0)) == []


# --- edges --------------------------------------------------------------------------------


def test_edge_signatures_of_a_right_isosceles_triangle() -> None:
    first, second, third = _native.edge_signatures([(0, 0), (2, 0), (0, 2)])
    assert first.length == pytest.approx(2.0, abs=1e-12)
    assert first.angle_start == pytest.approx(math.pi / 2, abs=1e-12)
    assert first.angle_end == pytest.approx(math.pi / 4, abs=1e-12)
    assert second.length == pytest.approx(math.sqrt(8.0), abs=1e-12)
    assert second.angle_start == pytest.approx(math.pi / 4, abs=1e-12)
    assert third.angle_end == pytest.approx(math.pi / 2, abs=1e-12)
    assert first.height_start is None and first.height_end is None
    assert first.slope_along is None and first.slope_across is None


def test_edge_signatures_of_a_roofed_square() -> None:
    """z = 10 + 0.5 x over [-1, 1]^2: 9.5 along the left side, 10.5 along the right."""
    square = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    bottom, right, top, left = _native.edge_signatures(square, (10.0, 0.5, 0.0))
    # Left to right along the bottom: climbs 1 mm in 2 mm, level across.
    assert (bottom.height_start, bottom.height_end) == pytest.approx((9.5, 10.5), abs=1e-12)
    assert bottom.slope_along == pytest.approx(0.5, abs=1e-12)
    assert bottom.slope_across == pytest.approx(0.0, abs=1e-12)
    # Up the right side: level along, still rising outwards.
    assert (right.height_start, right.height_end) == pytest.approx((10.5, 10.5), abs=1e-12)
    assert right.slope_along == pytest.approx(0.0, abs=1e-12)
    assert right.slope_across == pytest.approx(0.5, abs=1e-12)
    assert top.slope_along == pytest.approx(-0.5, abs=1e-12)
    assert left.slope_across == pytest.approx(-0.5, abs=1e-12)


def test_an_edge_signature_is_read_only_and_prints_its_fields() -> None:
    signature = _native.edge_signatures(SQUARE)[0]
    with pytest.raises(AttributeError):
        signature.length = 3.0  # pyright: ignore[reportAttributeAccessIssue]
    assert repr(signature).startswith("EdgeSignature(length=2.0, ")
    assert repr(signature).endswith("slope_along=None, slope_across=None)")


# --- roofs --------------------------------------------------------------------------------

# Two strips that meet in a ridge at x = 0: each is 20 high at its centre, 36 from
# the seam, and rises towards it at 0.25, so both reach 29 there.
LEFT, LEFT_POSE = (20.0, 0.25, 0.0), (-36.0, 0.0, 0.0)
RIGHT, RIGHT_POSE = (20.0, -0.25, 0.0), (36.0, 0.0, 0.0)
SEAM = ((0.0, -72.0), (0.0, 72.0))


def test_roof_height_follows_the_piece() -> None:
    assert _native.roof_height(LEFT, LEFT_POSE, (0.0, 17.0)) == pytest.approx(29.0, abs=1e-12)
    # Turned a quarter, the slope runs along world y: 4 mm up from the centre is 1 mm higher.
    turned = (-36.0, 0.0, math.pi / 2)
    assert _native.roof_height(LEFT, turned, (-36.0, 4.0)) == pytest.approx(21.0, abs=1e-12)
    assert _native.world_gradient(LEFT, turned) == pytest.approx((0.0, 0.25), abs=1e-12)


def test_a_ridge_is_continuous_though_the_gradients_differ() -> None:
    assert _native.seam_mismatch(LEFT, LEFT_POSE, RIGHT, RIGHT_POSE, *SEAM) == pytest.approx(
        0.0, abs=1e-12
    )
    assert _native.tangential_gradient_mismatch(
        LEFT, LEFT_POSE, RIGHT, RIGHT_POSE, *SEAM
    ) == pytest.approx(0.0, abs=1e-12)
    assert _native.world_gradient(LEFT, LEFT_POSE) != _native.world_gradient(RIGHT, RIGHT_POSE)


def test_a_half_turned_strip_leaves_a_step_the_gradient_test_cannot_see() -> None:
    # Half-turned, the right strip falls towards the seam: 20 - 9 = 11 against 29.
    turned = (36.0, 0.0, math.pi)
    assert _native.seam_mismatch(LEFT, LEFT_POSE, RIGHT, turned, *SEAM) == pytest.approx(
        18.0, abs=1e-9
    )
    # The step is the same all along the seam, so the roofs do not drift apart.
    assert _native.tangential_gradient_mismatch(
        LEFT, LEFT_POSE, RIGHT, turned, *SEAM
    ) == pytest.approx(0.0, abs=1e-12)


def test_a_tilt_along_the_seam_shows_in_both_tests() -> None:
    # 0.01 mm per mm along the seam: nothing in the middle, 0.72 mm at either end, 72 mm away.
    tilted = (20.0, -0.25, 0.01)
    assert _native.seam_mismatch(LEFT, LEFT_POSE, tilted, RIGHT_POSE, *SEAM) == pytest.approx(
        0.72, abs=1e-12
    )
    assert _native.tangential_gradient_mismatch(
        LEFT, LEFT_POSE, tilted, RIGHT_POSE, *SEAM
    ) == pytest.approx(-0.01, abs=1e-12)


# --- refused input ------------------------------------------------------------------------

TWO = [(0.0, 0.0), (1.0, 0.0)]


@pytest.mark.parametrize(
    "call",
    [
        lambda: _native.centroid(TWO),
        lambda: _native.transform(TWO, REST),
        lambda: _native.contains_point(TWO, (0.0, 0.0)),
        lambda: _native.point_outside_depth((0.0, 0.0), TWO),
        lambda: _native.outside_depth(TWO, SQUARE),
        lambda: _native.outside_depth(SQUARE, TWO),
        lambda: _native.penetration_depth(TWO, SQUARE),
        lambda: _native.penetration_depth(SQUARE, TWO),
        lambda: _native.intersection(SQUARE, TWO),
        lambda: _native.intersection_area(TWO, SQUARE),
        lambda: _native.outside_area(SQUARE, []),
        lambda: _native.edge_signatures(TWO),
    ],
)
def test_a_polygon_with_fewer_than_three_vertices_is_refused(call: Any) -> None:
    with pytest.raises(ValueError, match="at least 3 vertices"):
        call()


def test_a_segment_without_direction_is_refused() -> None:
    with pytest.raises(ValueError, match="no direction"):
        _native.tangential_gradient_mismatch(
            LEFT, LEFT_POSE, RIGHT, RIGHT_POSE, (1.0, 1.0), (1.0, 1.0)
        )
    # The height comparison needs no direction.
    assert _native.seam_mismatch(
        LEFT, LEFT_POSE, RIGHT, RIGHT_POSE, (0.0, 1.0), (0.0, 1.0)
    ) == pytest.approx(0.0, abs=1e-12)


def test_malformed_arguments_are_refused() -> None:
    with pytest.raises(ValueError, match="length 2"):
        _native.signed_area([(0.0, 0.0, 0.0)] * 3)
    with pytest.raises(ValueError, match="length 3"):
        _native.transform(SQUARE, (0.0, 0.0))  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        _native.signed_area([("a", "b")] * 3)  # pyright: ignore[reportArgumentType]
