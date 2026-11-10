"""Hypothesis strategies for geometric inputs, as JSON-shaped data."""

import math

from hypothesis import strategies as st

from support import geometry

Point = tuple[float, float]


@st.composite
def convex_polygons(draw: st.DrawFn, min_vertices: int = 3, max_vertices: int = 8) -> list[Point]:
    """Strictly convex counter-clockwise polygons centred on their area centroid.

    Vertices lie on a circle at angles kept at least 0.3 rad apart, which is
    convex by construction; an axis stretch then varies the shape. Sizes are in
    the range of real pieces, a few to a few tens of millimetres.
    """
    n = draw(st.integers(min_vertices, max_vertices))
    weights = [draw(st.floats(0.05, 1.0)) for _ in range(n)]
    spare = 2 * math.pi - 0.3 * n
    gaps = [0.3 + w * spare / sum(weights) for w in weights]
    if max(gaps) > 0.9 * math.pi:
        # A gap near a half turn would put the centre almost on an edge.
        gaps = [2 * math.pi / n] * n
    radius = draw(st.floats(5.0, 40.0))
    stretch = draw(st.floats(0.4, 1.0))
    angle = draw(st.floats(0.0, 2 * math.pi))
    points = []
    for gap in gaps:
        points.append((radius * math.cos(angle), stretch * radius * math.sin(angle)))
        angle += gap
    cx, cy = geometry.centroid(points)
    return [(x - cx, y - cy) for x, y in points]


poses = st.fixed_dictionaries(
    {
        "x": st.floats(-100.0, 100.0),
        "y": st.floats(-100.0, 100.0),
        "theta": st.floats(-math.pi, math.pi),
    }
)

roofs = st.fixed_dictionaries(
    {"z0": st.floats(5.0, 50.0), "gx": st.floats(-1.0, 1.0), "gy": st.floats(-1.0, 1.0)}
)

seeds = st.integers(0, 2**32 - 1)
