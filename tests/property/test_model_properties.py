"""Properties of the data layer's polygon checks and of the JSON writer."""

import json
import math
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from maxplus_solvers import _polygon
from maxplus_solvers.io.instance import format_json
from maxplus_solvers.models import Pose
from support import geometry
from support.strategies import convex_polygons, poses

Polygon = list[tuple[float, float]]


@given(convex_polygons())
def test_convex_polygons_are_accepted_and_their_reverse_is_not(polygon: Polygon) -> None:
    assert geometry.is_convex_ccw(polygon), "the strategy must produce convex polygons"
    assert _polygon.convexity_defect(polygon) is None
    assert _polygon.convexity_defect(polygon[::-1]) is not None


@given(convex_polygons(min_vertices=4), st.data())
def test_swapping_two_neighbours_breaks_convexity(polygon: Polygon, data: st.DataObject) -> None:
    """With four or more vertices, exchanging adjacent ones makes the outline cross itself."""
    i = data.draw(st.integers(0, len(polygon) - 1))
    j = (i + 1) % len(polygon)
    polygon[i], polygon[j] = polygon[j], polygon[i]
    assert not geometry.is_convex_ccw(polygon)
    assert _polygon.convexity_defect(polygon) is not None


@given(convex_polygons(), poses)
def test_area_and_centroid_agree_with_the_oracle_and_move_rigidly(
    polygon: Polygon, pose: Any
) -> None:
    assert math.isclose(_polygon.signed_area(polygon), geometry.area(polygon), abs_tol=1e-9)
    moved = [Pose(**pose).apply(p) for p in polygon]
    expected = geometry.place_polygon(polygon, pose)
    assert all(math.dist(a, b) < 1e-9 for a, b in zip(moved, expected, strict=True))
    assert math.isclose(_polygon.signed_area(moved), geometry.area(polygon), abs_tol=1e-6)
    cx, cy = _polygon.centroid(moved)
    # The polygon is centred, so its centroid lands on the translation.
    assert math.hypot(cx - pose["x"], cy - pose["y"]) < 1e-9
    assert _polygon.convexity_defect(moved) is None


@given(poses, st.tuples(st.floats(-200.0, 200.0), st.floats(-200.0, 200.0)))
def test_to_local_inverts_apply(pose: Any, point: tuple[float, float]) -> None:
    p = Pose(**pose)
    assert math.dist(p.to_local(p.apply(point)), point) < 1e-9
    assert math.dist(p.apply(p.to_local(point)), point) < 1e-9


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(10**12), 10**12)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4)
    ),
    max_leaves=20,
)


@given(json_values)
def test_the_writer_loses_nothing(value: Any) -> None:
    text = format_json(value)
    assert json.loads(text) == value
    assert "\r" not in text
    assert format_json(json.loads(text)) == text
