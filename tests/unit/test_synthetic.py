"""The synthetic puzzles are what their docstrings claim, checked with the oracle."""

import math

import pytest

from maxplus_solvers import synthetic
from maxplus_solvers.sanitize import SolvedAssembly
from support import geometry


def world(assembly: SolvedAssembly) -> dict[str, list[tuple[float, float]]]:
    return {
        p.source_id: geometry.place_polygon(p.polygon, p.pose.to_dict()) for p in assembly.pieces
    }


def rectangle(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


@pytest.mark.parametrize("name", sorted(synthetic.BUILDERS))
def test_every_builder_makes_a_well_formed_assembly(name: str) -> None:
    assembly = synthetic.BUILDERS[name]()
    assert assembly.id == name
    assert geometry.is_convex_ccw(assembly.target)
    for piece in assembly.pieces:
        assert geometry.is_convex_ccw(piece.polygon)
        cx, cy = geometry.centroid(piece.polygon)
        assert math.hypot(cx, cy) < 1e-9
        for vertex in geometry.place_polygon(piece.polygon, piece.pose.to_dict()):
            assert geometry.outside_depth(vertex, assembly.target) < 1e-9
    assert sum(geometry.area(p.polygon) for p in assembly.pieces) == pytest.approx(
        geometry.area(assembly.target), abs=1e-6
    )
    assert assembly.solution_count is not None
    assert assembly.source is None and assembly.tropical is None


def test_two_rectangles() -> None:
    assembly = synthetic.two_rectangles()
    placed = world(assembly)
    assert geometry.same_polygon(placed["narrow"], rectangle(-72, -72, -24, 72), tol=1e-9)
    assert geometry.same_polygon(placed["wide"], rectangle(-24, -72, 72, 72), tol=1e-9)
    assert not assembly.has_roofs
    assert assembly.solution_count is not None
    assert (assembly.solution_count.canonical, assembly.solution_count.assemblies) == (1, 4)


def test_four_squares() -> None:
    assembly = synthetic.four_squares()
    placed = world(assembly)
    assert geometry.same_polygon(placed["sw"], rectangle(-72, -72, 0, 0), tol=1e-9)
    assert geometry.same_polygon(placed["se"], rectangle(0, -72, 72, 0), tol=1e-9)
    assert geometry.same_polygon(placed["ne"], rectangle(0, 0, 72, 72), tol=1e-9)
    assert geometry.same_polygon(placed["nw"], rectangle(-72, 0, 0, 72), tol=1e-9)
    # Identical pieces: the same local polygon four times.
    first = assembly.pieces[0].polygon
    assert all(geometry.same_polygon(p.polygon, first, tol=1e-9) for p in assembly.pieces)
    assert assembly.solution_count is not None
    assert (assembly.solution_count.canonical, assembly.solution_count.assemblies) == (1, 1)


def test_four_triangles() -> None:
    assembly = synthetic.four_triangles()
    assert len(assembly.target) == 3
    target_sides = [math.dist(assembly.target[i], assembly.target[(i + 1) % 3]) for i in range(3)]
    assert target_sides == pytest.approx([144.0] * 3, abs=1e-9)
    assert geometry.centroid(assembly.target) == pytest.approx((0.0, 0.0), abs=1e-9)
    for piece in assembly.pieces:
        sides = [math.dist(piece.polygon[i], piece.polygon[(i + 1) % 3]) for i in range(3)]
        assert sides == pytest.approx([72.0] * 3, abs=1e-9)
    # Area of an equilateral triangle of side 144.
    assert geometry.area(assembly.target) == pytest.approx(math.sqrt(3) / 4 * 144**2, abs=1e-6)
    assert assembly.solution_count is not None
    assert (assembly.solution_count.canonical, assembly.solution_count.assemblies) == (1, 1)


def test_the_ridge_has_the_documented_heights() -> None:
    assembly = synthetic.two_rectangles_ridge()
    pieces = {p.source_id: p for p in assembly.pieces}
    placed = world(assembly)
    assert geometry.same_polygon(placed["narrow"], rectangle(-72, -72, -24, 72), tol=1e-9)
    assert geometry.same_polygon(placed["wide"], rectangle(-24, -72, 72, 72), tol=1e-9)

    def height(name: str, x: float, y: float) -> float:
        piece = pieces[name]
        assert piece.roof is not None
        return geometry.roof_height(piece.roof.to_dict(), piece.pose.to_dict(), (x, y))

    assert height("narrow", -72, 50) == pytest.approx(8.0, abs=1e-9)
    assert height("narrow", -24, -10) == pytest.approx(20.0, abs=1e-9)
    assert height("wide", -24, 33) == pytest.approx(20.0, abs=1e-9)
    assert height("wide", 72, 0) == pytest.approx(14.0, abs=1e-9)
    # Lowest 8, highest 20.
    assert assembly.relief_mm == 12.0
    assert assembly.solution_count is not None
    assert (assembly.solution_count.canonical, assembly.solution_count.assemblies) == (1, 4)


@pytest.mark.parametrize(
    ("turned", "left", "right"),
    [
        ((), 20.0, 20.0),
        (("narrow",), 8.0, 20.0),
        (("wide",), 20.0, 14.0),
        (("narrow", "wide"), 8.0, 14.0),
    ],
)
def test_only_the_ridge_is_continuous(turned: tuple[str, ...], left: float, right: float) -> None:
    """Half-turning a strip in place still tiles, so the count rests on the roofs differing."""
    assembly = synthetic.two_rectangles_ridge()
    heights = {}
    for piece in assembly.pieces:
        assert piece.roof is not None
        pose = piece.pose.to_dict()
        if piece.source_id in turned:
            pose["theta"] = math.pi
        heights[piece.source_id] = geometry.roof_height(piece.roof.to_dict(), pose, (-24.0, 17.0))
    assert heights["narrow"] == pytest.approx(left, abs=1e-9)
    assert heights["wide"] == pytest.approx(right, abs=1e-9)
    tolerance = assembly.validation.roof_mismatch * assembly.relief_mm  # type: ignore[operator]
    assert (abs(left - right) <= tolerance) == (turned == ())
