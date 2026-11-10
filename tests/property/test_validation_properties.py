"""Properties of the validator, with Shapely's own predicates and hand formulas as the oracle."""

import math
from typing import Any

import shapely
from hypothesis import assume, given
from hypothesis import strategies as st

from maxplus_solvers import Piece, Pose, PuzzleInstance, Regime
from maxplus_solvers.models import ValidationConstants
from maxplus_solvers.validation import penetration_depth, validate_solution
from support import geometry
from support.strategies import convex_polygons, poses

Polygon = list[tuple[float, float]]
EPS = 1e-6

SQUARE = ((-36.0, -36.0), (36.0, -36.0), (36.0, 36.0), (-36.0, 36.0))
TRAY = ((-72.0, -72.0), (72.0, -72.0), (72.0, 72.0), (-72.0, 72.0))
CENTRES = {"sw": (-36.0, -36.0), "se": (36.0, -36.0), "ne": (36.0, 36.0), "nw": (-36.0, 36.0)}
SQUARES = PuzzleInstance(
    id="squares",
    regime=Regime.FOOTPRINT,
    target=TRAY,
    pieces=tuple(Piece(name, SQUARE) for name in CENTRES),
    span_mm=144.0,
    validation=ValidationConstants(1e-6, 0.006, 0.006, 0.012, 3.0, 0.02),
)

# Poses close enough together that the two polygons often meet.
near = st.fixed_dictionaries(
    {
        "x": st.floats(-40.0, 40.0),
        "y": st.floats(-40.0, 40.0),
        "theta": st.floats(-math.pi, math.pi),
    }
)


@given(convex_polygons(), convex_polygons(), near, near)
def test_depth_is_symmetric(a: Polygon, b: Polygon, pose_a: Any, pose_b: Any) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    assert math.isclose(penetration_depth(pa, pb), penetration_depth(pb, pa), abs_tol=1e-9)


@given(convex_polygons(), convex_polygons(), near, near, poses)
def test_depth_does_not_change_under_a_common_rigid_motion(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any, motion: Any
) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    qa, qb = geometry.place_polygon(pa, motion), geometry.place_polygon(pb, motion)
    assert math.isclose(penetration_depth(pa, pb), penetration_depth(qa, qb), abs_tol=1e-7)


@given(convex_polygons(), convex_polygons(), near, near)
def test_the_sign_of_the_depth_agrees_with_shapely(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    """Convex polygons overlap exactly when no edge normal separates them."""
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    depth = penetration_depth(pa, pb)
    assume(abs(depth) > EPS)
    sa, sb = shapely.Polygon(pa), shapely.Polygon(pb)
    if depth > 0:
        assert sa.intersection(sb).area > 0
    else:
        assert sa.intersection(sb).area == 0
        # The gap along one normal cannot exceed the true distance.
        assert sa.distance(sb) >= -depth - 1e-9


@given(convex_polygons(), convex_polygons(), near, near)
def test_sliding_apart_by_the_depth_separates(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    """Sliding by the depth along some edge normal leaves no shared area."""
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    depth = penetration_depth(pa, pb)
    assume(depth > EPS)
    sa = shapely.Polygon(pa)
    remaining = []
    for polygon in (pa, pb):
        for i, (px, py) in enumerate(polygon):
            qx, qy = polygon[(i + 1) % len(polygon)]
            length = math.hypot(qx - px, qy - py)
            nx, ny = (qy - py) / length, -(qx - px) / length
            for sign in (1.0, -1.0):
                slid = [(x + sign * nx * depth, y + sign * ny * depth) for x, y in pb]
                remaining.append(sa.intersection(shapely.Polygon(slid)).area)
    assert min(remaining) < 1e-6
    # And nothing shorter along those normals does: at 90% of the depth they still overlap.
    still = []
    for polygon in (pa, pb):
        for i, (px, py) in enumerate(polygon):
            qx, qy = polygon[(i + 1) % len(polygon)]
            length = math.hypot(qx - px, qy - py)
            nx, ny = (qy - py) / length, -(qx - px) / length
            for sign in (1.0, -1.0):
                slid = [(x + sign * nx * 0.9 * depth, y + sign * ny * 0.9 * depth) for x, y in pb]
                still.append(sa.intersection(shapely.Polygon(slid)).area)
    assert min(still) > 0


def squares_with(piece: str, dx: float, dy: float) -> dict[str, Pose]:
    out = {name: Pose(x, y, 0.0) for name, (x, y) in CENTRES.items()}
    x, y = CENTRES[piece]
    out[piece] = Pose(x + dx, y + dy, 0.0)
    return out


@given(st.sampled_from(sorted(CENTRES)), st.floats(0.01, 60.0), st.booleans())
def test_a_square_pushed_inwards_overlaps_by_what_it_moved(
    piece: str, d: float, along_x: bool
) -> None:
    """One of four squares moved d towards a neighbour: depth d, 72*d overlapped and vacated."""
    x, y = CENTRES[piece]
    dx, dy = (-math.copysign(d, x), 0.0) if along_x else (0.0, -math.copysign(d, y))
    report = validate_solution(SQUARES, squares_with(piece, dx, dy))
    assert math.isclose(report.worst_overlap_depth_mm, d, abs_tol=1e-9)
    assert math.isclose(report.overlap_area_mm2, 72.0 * d, abs_tol=1e-6)
    assert math.isclose(report.uncovered_area_mm2, 72.0 * d, abs_tol=1e-6)
    assert report.worst_outside_mm == 0.0
    assert report.no_overlap == (d <= 0.864)
    assert report.area == (72.0 * d <= 248.832)


@given(st.sampled_from(sorted(CENTRES)), st.floats(0.01, 200.0), st.booleans())
def test_a_square_pushed_outwards_sticks_out_by_what_it_moved(
    piece: str, d: float, along_x: bool
) -> None:
    x, y = CENTRES[piece]
    dx, dy = (math.copysign(d, x), 0.0) if along_x else (0.0, math.copysign(d, y))
    report = validate_solution(SQUARES, squares_with(piece, dx, dy))
    lost = 72.0 * min(d, 72.0)
    assert math.isclose(report.worst_outside_mm, d, abs_tol=1e-9)
    assert math.isclose(report.outside_area_mm2, lost, abs_tol=1e-6)
    assert math.isclose(report.uncovered_area_mm2, lost, abs_tol=1e-6)
    assert report.overlaps == ()
    assert report.inside == (d <= 0.864)


@given(st.sampled_from(sorted(CENTRES)), st.floats(-math.pi, math.pi))
def test_the_verdict_is_all_checks_together(piece: str, turn: float) -> None:
    poses_ = squares_with(piece, 0.0, 0.0)
    poses_[piece] = Pose(*CENTRES[piece], turn)
    report = validate_solution(SQUARES, poses_)
    assert report.solved == (report.no_overlap and report.inside and report.area and report.roof)
    assert report.solved == (report.failed == ())
    # A square fits its place only near a multiple of a quarter turn.
    off = abs(math.remainder(turn, math.pi / 2))
    if off > math.radians(3.0):
        assert not report.solved
    if off < math.radians(0.5):
        assert report.solved
