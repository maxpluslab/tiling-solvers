"""The candidate interface through ``_native``, on arrangements small enough to draw."""

import math
from typing import Any

import pytest

from maxplus_solvers import _native

TRAY = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
TOL: dict[str, Any] = {"length_tol": 1e-7, "angle_tol": 1e-7, "slope_tol": 1e-7}
QUARTER = math.pi / 2


def rectangle(w: float, h: float) -> list[tuple[float, float]]:
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


def assembly(*pieces: list[tuple[float, float]], roofs: Any = None) -> _native.Assembly:
    return _native.Assembly(TRAY, list(pieces), roofs, **TOL)


def corners(state: _native.Assembly) -> list[tuple[float, float, float, float, bool]]:
    """Corners as (x, y, direction and angle in quarter turns, convex)."""
    return [
        (c.x, c.y, round(c.direction / QUARTER, 6), round(c.angle / QUARTER, 6), c.convex)
        for c in state.frontier()
    ]


def test_an_empty_tray_has_its_four_corners() -> None:
    state = assembly(rectangle(2, 1))
    # Each opens a quarter turn, starting along the tray edge that leaves it.
    assert corners(state) == [
        (0.0, 0.0, 0.0, 1.0, True),
        (4.0, 0.0, 1.0, 1.0, True),
        (4.0, 4.0, 2.0, 1.0, True),
        (0.0, 4.0, 3.0, 1.0, True),
    ]
    first = state.frontier()[0]
    assert (first.source_piece, first.source_edge) == (None, 0)
    assert repr(first).endswith("convex=True, source=tray edge 0)")
    with pytest.raises(AttributeError):
        first.angle = 1.0  # pyright: ignore[reportAttributeAccessIssue]


def test_a_block_in_the_corner_leaves_an_l_with_one_reflex_corner() -> None:
    state = assembly(rectangle(2, 1), rectangle(2, 1))
    state.place(0, (1.0, 0.5, 0.0))
    assert corners(state) == [
        (4.0, 0.0, 1.0, 1.0, True),
        (4.0, 4.0, 2.0, 1.0, True),
        (0.0, 4.0, 3.0, 1.0, True),
        (2.0, 0.0, 0.0, 1.0, True),
        # Three quarters of the way round the block's top-right corner are open.
        (2.0, 1.0, 3.0, 3.0, False),
        (0.0, 1.0, 0.0, 1.0, True),
    ]
    reflex = state.frontier()[4]
    # It leaves down the block's right side: edge 1, from (2, 0) to (2, 1), backwards.
    assert (reflex.source_piece, reflex.source_edge) == (0, 1)


def test_a_covered_tray_has_no_frontier() -> None:
    state = assembly(rectangle(2, 4), rectangle(2, 4))
    state.place(0, (1.0, 2.0, 0.0))
    # The other half is a rectangle.
    assert len(state.frontier()) == 4
    state.place(1, (3.0, 2.0, 0.0))
    assert state.frontier() == []
    assert state.all_placed


def test_proposals_put_a_vertex_in_the_corner_and_an_edge_along_its_side() -> None:
    state = assembly(rectangle(2, 1))
    lying, standing = state.propose(state.frontier()[0])
    # Lying: centre (1, 0.5), unturned. Standing: centre (0.5, 1), a quarter turn back.
    assert lying.pose == pytest.approx((1.0, 0.5, 0.0), abs=1e-12)
    assert standing.pose == pytest.approx((0.5, 1.0, -QUARTER), abs=1e-12)
    assert (lying.piece, lying.vertex, standing.vertex) == (0, 0, 1)
    assert (lying.contact_piece, lying.contact_edge) == (None, 0)
    assert (lying.x, lying.y, lying.theta) == lying.pose
    # A rectangle maps onto itself by a half turn, so vertices 2 and 3 are not tried.
    assert state.symmetry() == [2]
    assert state.stats() == (2, 0, 0)
    assert repr(lying).startswith("Candidate(piece=0, x=1.0, y=0.5, theta=0.0, vertex=0")


def test_proposals_leave_out_twins_and_count_what_does_not_fit() -> None:
    # Two identical blocks and a square that leaves a gap half a unit wide.
    state = assembly(rectangle(2, 1), rectangle(2, 1), rectangle(3.5, 3.5))
    assert state.classes() == [0, 0, 2]
    state.place(2, (1.75, 1.75, 0.0))
    gap = next(c for c in state.frontier() if (c.x, c.y) == (3.5, 0.0))
    assert state.propose(gap) == []
    # Piece 0 was tried lying and standing and reaches outside both ways; piece 1 was not tried.
    assert state.stats() == (2, 2, 0)


def test_a_proposal_that_enters_a_placed_piece_is_counted_as_such() -> None:
    # A 3 by 1 bar along the bottom; a 2 by 3.5 block into the top-left corner.
    state = assembly(rectangle(3, 1), rectangle(2, 3.5))
    state.place(0, (1.5, 0.5, 0.0))
    top_left = next(c for c in state.frontier() if (c.x, c.y) == (0.0, 4.0))
    # The corner's first side runs down the left wall. With its short side there the block
    # lies 3.5 wide and fits; with its long side there it comes down to y = 0.5, into the bar.
    (lying,) = state.propose(top_left)
    assert lying.pose == pytest.approx((1.75, 3.0, -QUARTER), abs=1e-12)
    assert state.stats() == (2, 0, 1)


def test_check_placement_measures_outside_and_overlap() -> None:
    state = assembly(rectangle(2, 1), rectangle(2, 1))
    state.place(0, (1.0, 0.5, 0.0))
    beside = state.check_placement(1, (3.0, 0.5, 0.0))
    assert (beside.outside_mm, beside.overlap_mm, beside.blocker, beside.fits) == (
        0.0,
        0.0,
        None,
        True,
    )
    # A quarter unit to the left: a quarter unit into the first block.
    into = state.check_placement(1, (2.75, 0.5, 0.0))
    assert into.overlap_mm == pytest.approx(0.25, abs=1e-12)
    assert (into.blocker, into.fits) == (0, False)
    # Half a unit right and 0.3 down: beyond the tray's corner by hypot(0.5, 0.3).
    out = state.check_placement(1, (3.5, 0.2, 0.0))
    assert out.outside_mm == pytest.approx(math.hypot(0.5, 0.3), abs=1e-12)
    assert (out.overlap_mm, out.fits) == (0.0, False)
    # Within the tolerance is a fit: 5e-8 over the wall, against 1e-7.
    assert state.check_placement(1, (3.0 + 5e-8, 0.5, 0.0)).fits
    assert not state.check_placement(1, (3.0 + 2e-7, 0.5, 0.0)).fits


def test_placing_and_undoing_is_a_stack() -> None:
    state = assembly(rectangle(2, 1), rectangle(2, 1))
    assert state.undo() is None
    state.place(1, (1.0, 0.5, 0.0))
    state.place(0, (3.0, 0.5, 0.0))
    assert state.placed() == [1, 0]
    assert state.pose(0) == (3.0, 0.5, 0.0)
    assert state.undo() == 0
    assert state.pose(0) is None
    assert state.placed() == [1]
    assert not state.all_placed


def test_roofs_prune_the_compatibility_graph() -> None:
    square = rectangle(1, 1)
    bare = assembly(square, square)
    # 4 edges against 4, both ways.
    assert (bare.edge_count, bare.arc_count) == (8, 32)
    assert bare.compatible(0, 0, 1, 0)
    assert not bare.compatible(0, 0, 0, 2), "a piece does not mate with itself"
    # Both rise 0.5 per mm towards +x: +0.5 along the bottom edge, -0.5 along the top, sides level.
    roofed = assembly(square, square, roofs=[(5.0, 0.5, 0.0), (5.0, 0.5, 0.0)])
    assert roofed.arc_count == 12
    assert [roofed.compatible(0, 0, 1, edge) for edge in range(4)] == [False, False, True, False]
    assert [roofed.compatible(0, 1, 1, edge) for edge in range(4)] == [False, True, False, True]
    # The tray has no roof: anything may lie against it.
    assert all(roofed.compatible(None, 0, 1, edge) for edge in range(4))
    # A sloping roof ends the square's symmetry; a level one would keep all four turns.
    assert roofed.symmetry() == [1, 1]
    assert assembly(square, roofs=[(5.0, 0.0, 0.0)]).symmetry() == [4]


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: _native.Assembly(TRAY[::-1], [rectangle(2, 1)], **TOL), "the target is not"),
        (lambda: _native.Assembly(TRAY, [rectangle(2, 1)[::-1]], **TOL), "piece 0 is not"),
        (lambda: _native.Assembly(TRAY, [rectangle(2, 1), TRAY[:2]], **TOL), "piece 1 is not"),
        (
            lambda: _native.Assembly(TRAY, [rectangle(2, 1)], [], **TOL),
            "0 roofs for 1 pieces",
        ),
        (
            lambda: _native.Assembly(
                TRAY, [rectangle(2, 1)], length_tol=0.0, angle_tol=1e-7, slope_tol=1e-7
            ),
            "tolerances must be",
        ),
        (
            lambda: _native.Assembly(
                TRAY, [rectangle(2, 1)], length_tol=1e-7, angle_tol=math.nan, slope_tol=1e-7
            ),
            "tolerances must be",
        ),
    ],
)
def test_construction_refuses_bad_input(build: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def test_tolerances_must_be_named() -> None:
    untyped: Any = _native.Assembly
    with pytest.raises(TypeError):
        untyped(TRAY, [rectangle(2, 1)], None, 1e-7, 1e-7, 1e-7)


def test_misuse_is_refused_not_a_crash() -> None:
    state = assembly(rectangle(2, 1), rectangle(2, 1))
    state.place(0, (1.0, 0.5, 0.0))
    with pytest.raises(ValueError, match="already placed"):
        state.place(0, (3.0, 0.5, 0.0))
    with pytest.raises(ValueError, match="no piece 2"):
        state.place(2, (3.0, 0.5, 0.0))
    with pytest.raises(ValueError, match="no piece 7"):
        state.check_placement(7, (0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="no piece 7"):
        state.pose(7)
    with pytest.raises(ValueError, match="no edge 4"):
        state.compatible(0, 0, 1, 4)
    with pytest.raises(ValueError, match="tray has no edge 4"):
        state.compatible(None, 4, 1, 0)
    # A corner taken from a larger assembly names a piece this one does not have.
    other = assembly(*[rectangle(1, 1)] * 5)
    other.place(4, (0.5, 0.5, 0.0))
    foreign = next(c for c in other.frontier() if c.source_piece == 4)
    with pytest.raises(ValueError, match="no piece 4"):
        state.propose(foreign)
