"""Elementary polygon arithmetic for the data layer.

Models, the sanitizer and the importers need areas, centroids and rotations to
build and check instances. That is bookkeeping, not search geometry: solvers use
the Rust kernel through ``_native``, and the validator uses Shapely.
"""

import math
from collections.abc import Sequence

Vec2 = tuple[float, float]

# A turn whose sine is below this is treated as no turn at all.
MIN_TURN_SINE = 1e-9
# Edges shorter than this, in millimetres, are degenerate.
MIN_EDGE_MM = 1e-9
# How far a full circuit of turns may differ from 2*pi, in radians.
WINDING_TOL = 1e-6


def signed_area(polygon: Sequence[Vec2]) -> float:
    """Shoelace area: positive when the vertices run counter-clockwise."""
    twice = 0.0
    for i, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(i + 1) % len(polygon)]
        twice += x0 * y1 - x1 * y0
    return twice / 2.0


def centroid(polygon: Sequence[Vec2]) -> Vec2:
    """Area centroid of a simple polygon with non-zero area."""
    twice = cx = cy = 0.0
    for i, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(i + 1) % len(polygon)]
        cross = x0 * y1 - x1 * y0
        twice += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (3.0 * twice), cy / (3.0 * twice))


def rotate(p: Vec2, theta: float) -> Vec2:
    """Rotate a point or vector counter-clockwise by ``theta`` radians about the origin."""
    s, c = math.sin(theta), math.cos(theta)
    return (c * p[0] - s * p[1], s * p[0] + c * p[1])


def convexity_defect(polygon: Sequence[Vec2]) -> str | None:
    """Why ``polygon`` is not a strictly convex counter-clockwise polygon, or ``None`` if it is.

    Every vertex must turn left, and the turns must add up to one full circuit,
    which excludes star polygons whose vertices all turn left.
    """
    n = len(polygon)
    if n < 3:
        return f"has {n} vertices, needs at least 3"
    for x, y in polygon:
        if not (math.isfinite(x) and math.isfinite(y)):
            return "has a non-finite coordinate"
    turning = 0.0
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        cx, cy = polygon[(i + 2) % n]
        ex, ey = bx - ax, by - ay
        fx, fy = cx - bx, cy - by
        le, lf = math.hypot(ex, ey), math.hypot(fx, fy)
        if le < MIN_EDGE_MM or lf < MIN_EDGE_MM:
            return f"has a degenerate edge at vertex {i}"
        cross = ex * fy - ey * fx
        if cross <= MIN_TURN_SINE * le * lf:
            return f"does not turn left at vertex {(i + 1) % n} (clockwise, reflex or collinear)"
        turning += math.atan2(cross, ex * fx + ey * fy)
    if abs(turning - 2.0 * math.pi) > WINDING_TOL:
        return "winds around more than once"
    return None
