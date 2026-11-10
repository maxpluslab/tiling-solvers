"""A small geometric oracle for tests, written independently of ``maxplus_solvers``.

Plain Python on JSON-shaped data, with the formulas spelled out. Tests compute
expected values here, or by hand, and never with the package's own geometry.
"""

import math
from collections.abc import Mapping, Sequence

Point = tuple[float, float]


def area(polygon: Sequence[Sequence[float]]) -> float:
    """Signed shoelace area, positive when counter-clockwise."""
    n = len(polygon)
    twice = 0.0
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        twice += x0 * y1 - x1 * y0
    return twice / 2.0


def centroid(polygon: Sequence[Sequence[float]]) -> Point:
    """Area centroid, by fanning triangles out from the first vertex."""
    x0, y0 = polygon[0]
    total = cx = cy = 0.0
    for i in range(1, len(polygon) - 1):
        x1, y1 = polygon[i]
        x2, y2 = polygon[i + 1]
        a = ((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) / 2.0
        total += a
        cx += a * (x0 + x1 + x2) / 3.0
        cy += a * (y0 + y1 + y2) / 3.0
    return (cx / total, cy / total)


def place(point: Sequence[float], pose: Mapping[str, float]) -> Point:
    """Rotate by ``theta`` about the origin, then translate by ``(x, y)``."""
    c, s = math.cos(pose["theta"]), math.sin(pose["theta"])
    return (pose["x"] + c * point[0] - s * point[1], pose["y"] + s * point[0] + c * point[1])


def place_polygon(polygon: Sequence[Sequence[float]], pose: Mapping[str, float]) -> list[Point]:
    return [place(p, pose) for p in polygon]


def roof_height(
    roof: Mapping[str, float], pose: Mapping[str, float], world: Sequence[float]
) -> float:
    """Height of a posed piece's roof plane above a world point."""
    dx, dy = world[0] - pose["x"], world[1] - pose["y"]
    c, s = math.cos(pose["theta"]), math.sin(pose["theta"])
    u, v = c * dx + s * dy, -s * dx + c * dy
    return roof["z0"] + roof["gx"] * u + roof["gy"] * v


def is_convex_ccw(polygon: Sequence[Sequence[float]]) -> bool:
    """Every corner turns strictly left and the corners add up to one circuit."""
    n = len(polygon)
    if n < 3:
        return False
    total = 0.0
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        cx, cy = polygon[(i + 2) % n]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross <= 0:
            return False
        total += math.atan2(cross, (bx - ax) * (cx - bx) + (by - ay) * (cy - by))
    return abs(total - 2 * math.pi) < 1e-6


def outside_depth(point: Sequence[float], convex_ccw: Sequence[Sequence[float]]) -> float:
    """How far a point lies outside a convex counter-clockwise polygon; 0 if inside."""
    worst = 0.0
    n = len(convex_ccw)
    for i in range(n):
        ax, ay = convex_ccw[i]
        bx, by = convex_ccw[(i + 1) % n]
        length = math.hypot(bx - ax, by - ay)
        # Positive to the right of the edge, which is outside.
        right = ((point[0] - ax) * (by - ay) - (point[1] - ay) * (bx - ax)) / length
        worst = max(worst, right)
    return worst


def vertex_set_distance(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """Hausdorff distance between two finite point sets."""
    forward = max(min(math.dist(p, q) for q in b) for p in a)
    backward = max(min(math.dist(p, q) for q in a) for p in b)
    return max(forward, backward)


def same_polygon(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]], tol: float) -> bool:
    """Equal as cyclic vertex sequences in the same direction, within ``tol``."""
    n = len(a)
    if n != len(b):
        return False
    return any(
        all(math.dist(a[i], b[(i + shift) % n]) <= tol for i in range(n)) for shift in range(n)
    )
