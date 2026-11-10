"""Independent check of a whole assembly: is this puzzle solved?

The rules are the browser player's completion check
(``tropical-puzzle-lab/web/src/geometry/evaluate.ts``, described in that
repository's ``docs/puzzle-rules.md``):

* **overlap**: the separating-axis penetration depth of every pair of pieces;
* **inside**: how far any vertex lies outside the target;
* **area**: overlap area plus area outside the target, and uncovered target area;
* **roof**, when pieces have roofs: the height mismatch along shared edges.

This module is deliberately separate from the search. It needs Shapely (the
``validate`` extra) and must not import ``_native`` or anything built on the
Rust geometry, so that one bug cannot make a solver and its checker agree.

Where it differs from the browser, it is the stricter or the more exact of the two:

* uncovered area comes from an exact union of the pieces; the browser uses
  first-order inclusion-exclusion, which is exact only when no three pieces
  share area;
* outside depth is the Euclidean distance from a vertex to the target; the
  browser takes the largest distance past any one wall, which is smaller beyond
  a corner;
* penetration depth is the true shortest separating translation; the browser
  takes the length of the shared extent along each edge normal, which is
  smaller when one piece's extent lies wholly inside the other's. The two agree
  whenever pieces overlap only partially along the shallowest axis, which
  covers every near-solution.

Numbers are ``f64``. A report is evidence within tolerances, not a proof.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

try:
    import shapely
except ImportError as error:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "maxplus_solvers.validation needs Shapely: install the 'validate' extra"
    ) from error

from maxplus_solvers.models import Piece, Pose, PuzzleInstance, Solution, TolerancePolicy

Vec2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class PairOverlap:
    """Two pieces that penetrate each other by more than the contact noise."""

    a: str
    b: str
    depth_mm: float
    area_mm2: float


@dataclass(frozen=True, slots=True)
class Seam:
    """A stretch of edge shared by two roofed pieces, and the roof step along it."""

    a: str
    b: str
    length_mm: float
    mismatch_mm: float


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Residuals of every check, the tolerances they were held to, and the verdicts."""

    worst_overlap_depth_mm: float
    worst_outside_mm: float
    overlap_area_mm2: float
    outside_area_mm2: float
    uncovered_area_mm2: float
    # None when the pieces have no roofs.
    worst_roof_mismatch_mm: float | None
    overlaps: tuple[PairOverlap, ...]
    outside_mm: Mapping[str, float]
    seams: tuple[Seam, ...]
    tolerances: TolerancePolicy

    @property
    def no_overlap(self) -> bool:
        return self.worst_overlap_depth_mm <= self.tolerances.overlap_depth_mm

    @property
    def inside(self) -> bool:
        return self.worst_outside_mm <= self.tolerances.outside_depth_mm

    @property
    def area(self) -> bool:
        limit = self.tolerances.area_error_mm2
        misplaced = self.overlap_area_mm2 + self.outside_area_mm2
        return misplaced <= limit and self.uncovered_area_mm2 <= limit

    @property
    def roof(self) -> bool:
        if self.worst_roof_mismatch_mm is None or self.tolerances.roof_mismatch_mm is None:
            return True
        return self.worst_roof_mismatch_mm <= self.tolerances.roof_mismatch_mm

    @property
    def failed(self) -> tuple[str, ...]:
        """Names of the checks that did not pass, in a fixed order."""
        checks = (
            ("overlap", self.no_overlap),
            ("inside", self.inside),
            ("area", self.area),
            ("roof", self.roof),
        )
        return tuple(name for name, passed in checks if not passed)

    @property
    def solved(self) -> bool:
        return not self.failed

    def residuals(self) -> dict[str, float]:
        """The numbers behind the verdicts, in the form ``Solution.residuals`` carries."""
        out = {
            "overlap_depth_mm": self.worst_overlap_depth_mm,
            "outside_mm": self.worst_outside_mm,
            "overlap_area_mm2": self.overlap_area_mm2,
            "outside_area_mm2": self.outside_area_mm2,
            "uncovered_area_mm2": self.uncovered_area_mm2,
        }
        if self.worst_roof_mismatch_mm is not None:
            out["roof_mismatch_mm"] = self.worst_roof_mismatch_mm
        return out


def penetration_depth(a: Sequence[Vec2], b: Sequence[Vec2]) -> float:
    """Separating-axis measure for two convex counter-clockwise polygons.

    Positive: the penetration depth, the length of the shortest translation
    that separates them. For convex polygons that translation is along an edge
    normal of one of them, so trying each normal is enough. Zero or negative:
    touching or apart, and the magnitude is the widest gap along any edge normal.
    """
    best = math.inf
    for polygon in (a, b):
        for i, (px, py) in enumerate(polygon):
            qx, qy = polygon[(i + 1) % len(polygon)]
            length = math.hypot(qx - px, qy - py)
            nx, ny = (qy - py) / length, -(qx - px) / length
            along_a = [nx * x + ny * y for x, y in a]
            along_b = [nx * x + ny * y for x, y in b]
            # How far b must move along this axis, either way, to clear a.
            escape = min(max(along_a) - min(along_b), max(along_b) - min(along_a))
            best = min(best, escape)
    return best


def _roof_height(piece: Piece, pose: Pose) -> Callable[[Vec2], float]:
    """The roof of a placed piece as a function of a world point."""
    roof = piece.roof
    if roof is None:
        raise ValueError(f"piece {piece.id} has no roof")
    return lambda p: roof.height_at(pose.to_local(p))


def _seams(
    a: Sequence[Vec2],
    b: Sequence[Vec2],
    height_a: Callable[[Vec2], float],
    height_b: Callable[[Vec2], float],
    policy: TolerancePolicy,
    lateral_tol: float,
) -> list[tuple[float, float]]:
    """Shared edge stretches of two placed pieces as ``(length, roof mismatch)``.

    Two edges form a seam when they run in opposite directions within the angle
    tolerance, lie within ``lateral_tol`` of each other, and run alongside each
    other for at least the minimum overlap. Both roofs are affine, so the
    mismatch along the stretch is largest at one of its ends; it is taken on the
    midline between the two edges, which is where a small gap or overlap leaves
    the true contact.
    """
    found: list[tuple[float, float]] = []
    cos_tol = math.cos(policy.edge_angle_rad)
    for i, e0 in enumerate(a):
        e1 = a[(i + 1) % len(a)]
        length = math.dist(e0, e1)
        dx, dy = (e1[0] - e0[0]) / length, (e1[1] - e0[1]) / length

        def lateral(p: Vec2, e0: Vec2 = e0, dx: float = dx, dy: float = dy) -> float:
            return dx * (p[1] - e0[1]) - dy * (p[0] - e0[0])

        def along(p: Vec2, e0: Vec2 = e0, dx: float = dx, dy: float = dy) -> float:
            return dx * (p[0] - e0[0]) + dy * (p[1] - e0[1])

        for j, f0 in enumerate(b):
            f1 = b[(j + 1) % len(b)]
            f_length = math.dist(f0, f1)
            fx, fy = (f1[0] - f0[0]) / f_length, (f1[1] - f0[1]) / f_length
            # Counter-clockwise neighbours run along a shared edge in opposite directions.
            if dx * fx + dy * fy > -cos_tol:
                continue
            if abs(lateral(f0)) > lateral_tol or abs(lateral(f1)) > lateral_tol:
                continue
            t0, t1 = along(f0), along(f1)
            lo, hi = max(0.0, min(t0, t1)), min(length, max(t0, t1))
            if hi - lo < policy.edge_min_overlap_mm:
                continue
            mismatch = 0.0
            for t in (lo, hi):
                on_e = (e0[0] + dx * t, e0[1] + dy * t)
                s = (t - t0) / (t1 - t0)
                on_f = (f0[0] + (f1[0] - f0[0]) * s, f0[1] + (f1[1] - f0[1]) * s)
                mid = ((on_e[0] + on_f[0]) / 2.0, (on_e[1] + on_f[1]) / 2.0)
                mismatch = max(mismatch, abs(height_a(mid) - height_b(mid)))
            found.append((hi - lo, mismatch))
    return found


def validate_solution(
    instance: PuzzleInstance,
    solution: Solution | Mapping[str, Pose],
    policy: TolerancePolicy | None = None,
) -> ValidationReport:
    """Check an assembly against the completion rules.

    ``solution`` gives one pose per piece id. ``policy`` defaults to the
    instance's published tolerances. The roof check runs whenever the instance
    has roofs, which is every regime but footprint.
    """
    poses = solution.poses if isinstance(solution, Solution) else solution
    ids = [piece.id for piece in instance.pieces]
    if set(poses) != set(ids):
        missing = sorted(set(ids) - set(poses))
        extra = sorted(set(poses) - set(ids))
        raise ValueError(f"poses do not match the pieces: missing {missing}, unexpected {extra}")
    if policy is None:
        policy = TolerancePolicy.from_instance(instance)
    roofed = instance.pieces[0].roof is not None
    if roofed and policy.roof_mismatch_mm is None:
        raise ValueError("the pieces have roofs but the tolerance policy has no roof tolerance")

    noise = policy.contact_noise_mm
    world = {p.id: p.world_polygon(poses[p.id]) for p in instance.pieces}
    shapes = {pid: shapely.Polygon(polygon) for pid, polygon in world.items()}
    target = shapely.Polygon(instance.target)
    lateral_tol = 2.0 * policy.overlap_depth_mm + noise

    overlaps: list[PairOverlap] = []
    seams: list[Seam] = []
    for first, second in combinations(instance.pieces, 2):
        depth = penetration_depth(world[first.id], world[second.id])
        if depth > noise:
            shared = shapes[first.id].intersection(shapes[second.id]).area
            overlaps.append(PairOverlap(first.id, second.id, depth, shared))
        if roofed and depth > -lateral_tol:
            for length, mismatch in _seams(
                world[first.id],
                world[second.id],
                _roof_height(first, poses[first.id]),
                _roof_height(second, poses[second.id]),
                policy,
                lateral_tol,
            ):
                seams.append(Seam(first.id, second.id, length, mismatch))

    outside_mm: dict[str, float] = {}
    outside_area = 0.0
    for pid in ids:
        worst = max(shapely.Point(vertex).distance(target) for vertex in world[pid])
        outside_mm[pid] = worst if worst > noise else 0.0
        outside_area += shapes[pid].difference(target).area
    uncovered = target.difference(shapely.union_all(list(shapes.values()))).area

    return ValidationReport(
        worst_overlap_depth_mm=max((o.depth_mm for o in overlaps), default=0.0),
        worst_outside_mm=max(outside_mm.values()),
        overlap_area_mm2=sum(o.area_mm2 for o in overlaps),
        outside_area_mm2=outside_area,
        uncovered_area_mm2=uncovered,
        worst_roof_mismatch_mm=max((s.mismatch_mm for s in seams), default=0.0) if roofed else None,
        overlaps=tuple(overlaps),
        outside_mm=outside_mm,
        seams=tuple(seams),
        tolerances=policy,
    )
