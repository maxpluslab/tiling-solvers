"""Small puzzles whose solutions are known by construction.

Each builder returns a :class:`SolvedAssembly`, which becomes an instance only
through the sanitizer, like a corpus puzzle. The solution counts are derived by
hand in each docstring, under one convention:

* ``assemblies`` is the number of distinct tilings of the target, with pieces
  unlabelled (swapping congruent pieces, or turning a piece onto itself, is not
  a new tiling). In relief puzzles the roof surface is part of the tiling.
* ``canonical`` is the number of those up to rotations of the target onto itself.

The counts are about exact geometry. A check with tolerances may accept more.
"""

import math
from collections.abc import Callable, Sequence

from maxplus_solvers import _polygon
from maxplus_solvers._polygon import Vec2
from maxplus_solvers.models import Pose, Roof, ValidationConstants
from maxplus_solvers.sanitize import SolutionCount, SolvedAssembly, SolvedPiece

SPAN_MM = 144.0
_HALF = SPAN_MM / 2.0
_SQUARE: tuple[Vec2, ...] = ((-_HALF, -_HALF), (_HALF, -_HALF), (_HALF, _HALF), (-_HALF, _HALF))

# The tolerances every corpus puzzle is published with.
_VALIDATION = ValidationConstants(
    contact_noise=1e-06,
    overlap_depth=0.006,
    outside_depth=0.006,
    area_error=0.012,
    edge_angle_deg=3.0,
    edge_min_overlap=0.02,
)
_RELIEF_VALIDATION = ValidationConstants(
    contact_noise=1e-06,
    overlap_depth=0.006,
    outside_depth=0.006,
    area_error=0.012,
    edge_angle_deg=3.0,
    edge_min_overlap=0.02,
    roof_mismatch=0.05,
)


def _piece(
    source_id: str, world: Sequence[Vec2], height: Callable[[Vec2], float] | None = None
) -> SolvedPiece:
    """A piece from its solved world polygon, and optionally its roof as a world height function.

    The height function must be affine. The local roof is read off from its value
    at the centroid and its differences one millimetre along each axis.
    """
    cx, cy = _polygon.centroid(world)
    local = tuple((x - cx, y - cy) for x, y in world)
    roof = None
    if height is not None:
        z0 = height((cx, cy))
        roof = Roof(z0, height((cx + 1.0, cy)) - z0, height((cx, cy + 1.0)) - z0)
    return SolvedPiece(source_id, local, Pose(cx, cy, 0.0), roof)


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> tuple[Vec2, ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def two_rectangles() -> SolvedAssembly:
    """A 144 mm square cut into a 48 mm strip and a 96 mm strip.

    Two convex pieces that tile a convex target are separated by a chord. Both
    parts are rectangles only if the chord is parallel to a side, and the strip
    widths then force it to lie 48 mm from one of the four sides. That gives 4
    assemblies, which are the four rotations of one: 1 canonical.
    """
    cut = -_HALF + 48.0
    pieces = (
        _piece("narrow", _rectangle(-_HALF, -_HALF, cut, _HALF)),
        _piece("wide", _rectangle(cut, -_HALF, _HALF, _HALF)),
    )
    return SolvedAssembly(
        "syn-two-rectangles", _SQUARE, pieces, SPAN_MM, _VALIDATION, solution_count=_count(1, 4)
    )


def two_rectangles_ridge() -> SolvedAssembly:
    """The two strips with roofs that meet in a ridge along the cut.

    The narrow strip rises from 8 mm at its wall to 20 mm at the cut; the wide
    strip falls from 20 mm at the cut to 14 mm at the opposite wall. Footprints
    tile as in :func:`two_rectangles`, and each strip can also be turned half a
    turn in place. Along the cut the heights are then 20|20 (the ridge), 8|20,
    20|14 or 8|14. Only the first is continuous, the others are off by at least
    6 mm, so the relief puzzle has the same 4 assemblies and 1 canonical, with
    every piece orientation determined.

    Turning one strip half a turn gives an assembly that tiles and has
    mismatched roofs, which is what the validator's roof check must catch.
    """
    cut = -_HALF + 48.0

    def narrow(p: Vec2) -> float:
        return 8.0 + 12.0 * (p[0] + _HALF) / 48.0

    def wide(p: Vec2) -> float:
        return 20.0 - 6.0 * (p[0] - cut) / 96.0

    pieces = (
        _piece("narrow", _rectangle(-_HALF, -_HALF, cut, _HALF), narrow),
        _piece("wide", _rectangle(cut, -_HALF, _HALF, _HALF), wide),
    )
    return SolvedAssembly(
        "syn-two-rectangles-ridge",
        _SQUARE,
        pieces,
        SPAN_MM,
        _RELIEF_VALIDATION,
        relief_mm=12.0,
        solution_count=_count(1, 4),
    )


def four_squares() -> SolvedAssembly:
    """A 144 mm square cut into four identical 72 mm squares.

    Each corner of the target is a right angle and must be filled by one piece
    corner, which pins a 72 mm square into every corner. Those four already
    cover the target: 1 assembly, 1 canonical. The pieces are interchangeable
    and each fits in four orientations, so a solver that labels pieces and poses
    sees 4! * 4**4 placements of the same tiling.
    """
    pieces = tuple(
        _piece(name, _rectangle(x, y, x + _HALF, y + _HALF))
        for name, x, y in (
            ("sw", -_HALF, -_HALF),
            ("se", 0.0, -_HALF),
            ("ne", 0.0, 0.0),
            ("nw", -_HALF, 0.0),
        )
    )
    return SolvedAssembly(
        "syn-four-squares", _SQUARE, pieces, SPAN_MM, _VALIDATION, solution_count=_count(1, 1)
    )


def four_triangles() -> SolvedAssembly:
    """An equilateral triangle of side 144 mm cut along its midlines into four of side 72 mm.

    Each 60 degree corner of the target can only be filled by a single 60 degree
    piece corner, so one piece sits in every corner with two sides along the
    target's sides. The remainder is the medial triangle, congruent to the
    fourth piece: 1 assembly, 1 canonical. The target is not a square and two of
    its sides are oblique, so this fixture exercises general targets and angles
    that are not multiples of 45 degrees.
    """
    side = SPAN_MM
    height = side * math.sqrt(3.0) / 2.0
    a: Vec2 = (-side / 2.0, -height / 3.0)
    b: Vec2 = (side / 2.0, -height / 3.0)
    c: Vec2 = (0.0, 2.0 * height / 3.0)

    def mid(p: Vec2, q: Vec2) -> Vec2:
        return ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)

    ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
    pieces = (
        _piece("corner-a", (a, ab, ca)),
        _piece("corner-b", (ab, b, bc)),
        _piece("corner-c", (ca, bc, c)),
        _piece("middle", (ab, bc, ca)),
    )
    return SolvedAssembly(
        "syn-four-triangles", (a, b, c), pieces, SPAN_MM, _VALIDATION, solution_count=_count(1, 1)
    )


def _count(canonical: int, assemblies: int) -> SolutionCount:
    return SolutionCount(canonical=canonical, assemblies=assemblies)


BUILDERS: dict[str, Callable[[], SolvedAssembly]] = {
    "syn-two-rectangles": two_rectangles,
    "syn-two-rectangles-ridge": two_rectangles_ridge,
    "syn-four-squares": four_squares,
    "syn-four-triangles": four_triangles,
}
