"""The Rust geometry against Shapely and the test oracle, on random convex polygons.

None of the expected values comes from ``_native``: areas, distances and
predicates are Shapely's, placements and roof heights are those of
``support.geometry``, and angles are computed here by another formula.
"""

import math
from typing import Any

import shapely
from hypothesis import assume, example, given
from hypothesis import strategies as st

from maxplus_solvers import _native
from maxplus_solvers.validation import penetration_depth
from support import geometry
from support.strategies import convex_polygons, poses, roofs

Polygon = list[tuple[float, float]]

# Poses close enough together that two polygons often meet.
near = st.fixed_dictionaries(
    {
        "x": st.floats(-40.0, 40.0),
        "y": st.floats(-40.0, 40.0),
        "theta": st.floats(-math.pi, math.pi),
    }
)
points = st.tuples(st.floats(-100.0, 100.0), st.floats(-100.0, 100.0))

LENGTH_TOL = 1e-9  # mm
AREA_TOL = 1e-6  # mm², on areas of up to a few thousand


def pose_tuple(pose: Any) -> tuple[float, float, float]:
    return (pose["x"], pose["y"], pose["theta"])


def roof_tuple(roof: Any) -> tuple[float, float, float]:
    return (roof["z0"], roof["gx"], roof["gy"])


@given(convex_polygons(), poses)
def test_area_centroid_and_placement_agree_with_the_oracle(polygon: Polygon, pose: Any) -> None:
    assert _native.is_convex_ccw(polygon)
    assert not _native.is_convex_ccw(polygon[::-1])
    assert math.isclose(_native.signed_area(polygon), geometry.area(polygon), abs_tol=AREA_TOL)
    expected = geometry.place_polygon(polygon, pose)
    moved = _native.transform(polygon, pose_tuple(pose))
    assert geometry.same_polygon(moved, expected, LENGTH_TOL)
    assert math.dist(_native.centroid(moved), geometry.centroid(expected)) <= LENGTH_TOL
    assert math.isclose(
        _native.signed_area(moved), shapely.Polygon(expected).area, abs_tol=AREA_TOL
    )


@given(convex_polygons(), convex_polygons(), near, near)
def test_intersection_area_agrees_with_shapely(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    expected = shapely.Polygon(pa).intersection(shapely.Polygon(pb)).area
    assert math.isclose(_native.intersection_area(pa, pb), expected, abs_tol=AREA_TOL)
    assert math.isclose(_native.intersection_area(pb, pa), expected, abs_tol=AREA_TOL)
    assert math.isclose(
        _native.outside_area(pa, pb),
        shapely.Polygon(pa).difference(shapely.Polygon(pb)).area,
        abs_tol=AREA_TOL,
    )


# Found by CI on Linux. The two results are the same triangle to one unit in the
# last place, and GEOS 3.14 reports that such a pair shares no area at all. So the
# two polygons are compared by distance and by area, never by overlaying them.
ONE_ULP_APART: Polygon = [
    (5.000000000000001, -5.921189464667502e-16),
    (-2.4999999999999987, 4.1948105495808745),
    (-2.5000000000000018, -4.1948105495808745),
]


@given(convex_polygons(), convex_polygons(), near, near)
@example(
    a=ONE_ULP_APART,
    b=ONE_ULP_APART,
    pose_a={"x": 0.865457123523327, "y": 3.0, "theta": 0.0},
    pose_b={"x": 0.0, "y": 0.0, "theta": 0.0},
)
def test_the_intersection_polygon_is_shapelys(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    expected = shapely.Polygon(pa).intersection(shapely.Polygon(pb))
    assume(expected.area > 1.0)
    shared = shapely.Polygon(_native.intersection(pa, pb))
    assert shapely.hausdorff_distance(shared, expected) <= LENGTH_TOL
    assert math.isclose(shared.area, expected.area, abs_tol=AREA_TOL)
    assert geometry.area(_native.intersection(pa, pb)) > 0.0, "counter-clockwise"


@given(convex_polygons(), convex_polygons(), near, near)
def test_penetration_depth_agrees_with_the_validator_and_with_shapely(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    depth = _native.penetration_depth(pa, pb)
    assert math.isclose(depth, penetration_depth(pa, pb), abs_tol=LENGTH_TOL)
    sa, sb = shapely.Polygon(pa), shapely.Polygon(pb)
    if depth > 1e-6:
        assert sa.intersection(sb).area > 0.0
    elif depth < -1e-6:
        assert not sa.intersects(sb)
        # The widest gap along an edge normal is at most the distance between the
        # polygons, and equals it unless the nearest points are two corners.
        assert sa.distance(sb) >= -depth - LENGTH_TOL


@given(convex_polygons(), convex_polygons(), near, near, st.floats(0.05, 0.95))
def test_a_slide_shorter_than_the_depth_never_separates(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any, fraction: float
) -> None:
    """No slide along an edge normal shorter than the penetration depth clears the overlap."""
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    depth = _native.penetration_depth(pa, pb)
    assume(depth > 1e-3)
    sa = shapely.Polygon(pa)
    cleared = []
    for polygon in (pa, pb):
        for i, p in enumerate(polygon):
            q = polygon[(i + 1) % len(polygon)]
            length = math.dist(p, q)
            nx, ny = (q[1] - p[1]) / length, -(q[0] - p[0]) / length
            for sign in (1.0, -1.0):
                short = [
                    (x + sign * nx * depth * fraction, y + sign * ny * depth * fraction)
                    for x, y in pb
                ]
                assert sa.intersection(shapely.Polygon(short)).area > 0.0
                full = [(x + sign * nx * depth, y + sign * ny * depth) for x, y in pb]
                cleared.append(sa.intersection(shapely.Polygon(full)).area)
    assert min(cleared) <= AREA_TOL, "sliding by the depth itself separates along some normal"


@given(convex_polygons(), poses, points)
def test_point_containment_and_distance_agree_with_shapely(
    polygon: Polygon, pose: Any, point: tuple[float, float]
) -> None:
    placed = geometry.place_polygon(polygon, pose)
    shape = shapely.Polygon(placed)
    here = shapely.Point(point)
    assert math.isclose(
        _native.point_outside_depth(point, placed), here.distance(shape), abs_tol=LENGTH_TOL
    )
    if here.distance(shape.exterior) > LENGTH_TOL:
        assert _native.contains_point(placed, point) == shape.covers(here)


@given(convex_polygons(), convex_polygons(), near, near)
def test_outside_depth_is_the_farthest_vertex_by_shapely(
    a: Polygon, b: Polygon, pose_a: Any, pose_b: Any
) -> None:
    pa, pb = geometry.place_polygon(a, pose_a), geometry.place_polygon(b, pose_b)
    container = shapely.Polygon(pb)
    expected = max(shapely.Point(vertex).distance(container) for vertex in pa)
    assert math.isclose(_native.outside_depth(pa, pb), expected, abs_tol=LENGTH_TOL)


def interior_angle(polygon: Polygon, i: int) -> float:
    """The angle between the two sides that leave vertex ``i``."""
    bx, by = polygon[i]
    ax, ay = polygon[i - 1]
    cx, cy = polygon[(i + 1) % len(polygon)]
    ux, uy, vx, vy = ax - bx, ay - by, cx - bx, cy - by
    return math.atan2(abs(ux * vy - uy * vx), ux * vx + uy * vy)


@given(convex_polygons(), roofs)
def test_edge_signatures_agree_with_the_oracle(polygon: Polygon, roof: Any) -> None:
    rest = {"x": 0.0, "y": 0.0, "theta": 0.0}
    signatures = _native.edge_signatures(polygon, roof_tuple(roof))
    bare = _native.edge_signatures(polygon)
    n = len(polygon)
    assert len(signatures) == len(bare) == n
    for i, (signature, plain) in enumerate(zip(signatures, bare, strict=True)):
        p, q = polygon[i], polygon[(i + 1) % n]
        length = math.dist(p, q)
        assert math.isclose(signature.length, length, abs_tol=LENGTH_TOL)
        assert math.isclose(signature.angle_start, interior_angle(polygon, i), abs_tol=1e-9)
        assert math.isclose(signature.angle_end, interior_angle(polygon, (i + 1) % n), abs_tol=1e-9)
        h0, h1 = geometry.roof_height(roof, rest, p), geometry.roof_height(roof, rest, q)
        assert signature.height_start is not None and signature.height_end is not None
        assert signature.slope_along is not None and signature.slope_across is not None
        assert math.isclose(signature.height_start, h0, abs_tol=LENGTH_TOL)
        assert math.isclose(signature.height_end, h1, abs_tol=LENGTH_TOL)
        assert math.isclose(signature.slope_along, (h1 - h0) / length, abs_tol=1e-9)
        # One millimetre out from the middle of the edge, the roof is this much higher.
        mid = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
        out = (mid[0] + (q[1] - p[1]) / length, mid[1] - (q[0] - p[0]) / length)
        assert not shapely.Polygon(polygon).covers(shapely.Point(out))
        rise = geometry.roof_height(roof, rest, out) - geometry.roof_height(roof, rest, mid)
        assert math.isclose(signature.slope_across, rise, abs_tol=1e-9)
        # Without a roof the footprint part is the same and the rest is absent.
        assert (plain.length, plain.angle_start, plain.angle_end) == (
            signature.length,
            signature.angle_start,
            signature.angle_end,
        )
        assert plain.height_start is None and plain.slope_across is None


@given(roofs, poses, points)
def test_roof_height_agrees_with_the_oracle(
    roof: Any, pose: Any, point: tuple[float, float]
) -> None:
    assert math.isclose(
        _native.roof_height(roof_tuple(roof), pose_tuple(pose), point),
        geometry.roof_height(roof, pose, point),
        abs_tol=LENGTH_TOL,
    )


@given(roofs, roofs, poses, poses, points, points)
def test_seam_mismatch_is_the_largest_step_anywhere_on_the_segment(
    roof_a: Any, roof_b: Any, pose_a: Any, pose_b: Any, p0: Any, p1: Any
) -> None:
    def step(t: float) -> float:
        p = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
        return geometry.roof_height(roof_a, pose_a, p) - geometry.roof_height(roof_b, pose_b, p)

    sampled = max(abs(step(k / 20.0)) for k in range(21))
    arguments = (roof_tuple(roof_a), pose_tuple(pose_a), roof_tuple(roof_b), pose_tuple(pose_b))
    assert math.isclose(_native.seam_mismatch(*arguments, p0, p1), sampled, abs_tol=LENGTH_TOL)
    length = math.dist(p0, p1)
    assume(length > 1e-3)
    drift = _native.tangential_gradient_mismatch(*arguments, p0, p1)
    assert math.isclose(drift * length, step(1.0) - step(0.0), abs_tol=1e-7)
