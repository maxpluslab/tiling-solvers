"""The search-level functions of ``_native``, on states small enough to work out by hand.

Cavities and roof steps of an ``Assembly``, canonical forms, and the argument
checks of ``contact_dfs``. What the search finds is tested through ``solve()``
in ``test_rust_contact_dfs.py``.
"""

import math
from typing import Any

import pytest

from maxplus_solvers import _native

TOL: dict[str, Any] = {"length_tol": 1e-7, "angle_tol": 1e-7, "slope_tol": 1e-7}
# A 4 by 4 tray with its corner at the origin.
TRAY = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]


def rectangle(w: float, h: float) -> list[tuple[float, float]]:
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


# --- cavities -----------------------------------------------------------------------------


def test_the_empty_tray_is_one_cavity_as_wide_as_the_tray() -> None:
    state = _native.Assembly(TRAY, [rectangle(4, 1)], **TOL)
    cavities = state.cavities()
    assert cavities is not None
    ((area, width, corners),) = cavities
    assert area == pytest.approx(16.0, abs=1e-12)
    assert width == pytest.approx(4.0, abs=1e-12)
    assert sorted(corners) == [0, 1, 2, 3]


def test_a_strip_across_the_tray_leaves_two_cavities() -> None:
    """The strip over 1 <= y <= 2 leaves 4 by 1 below it and 4 by 2 above."""
    state = _native.Assembly(TRAY, [rectangle(4, 1)], **TOL)
    state.place(0, (2.0, 1.5, 0.0))
    cavities = state.cavities()
    assert cavities is not None
    assert sorted((round(area, 9), round(width or 0, 9)) for area, width, _ in cavities) == [
        (4.0, 1.0),
        (8.0, 2.0),
    ]
    # Each corner of the frontier belongs to one cavity.
    used = sorted(corner for _, _, corners in cavities for corner in corners)
    assert used == list(range(len(state.frontier())))


def test_a_cavity_with_a_reflex_corner_has_no_width() -> None:
    """A 2 by 1 block in the corner leaves an L: 16 - 2 = 14."""
    state = _native.Assembly(TRAY, [rectangle(2, 1)], **TOL)
    state.place(0, (1.0, 0.5, 0.0))
    cavities = state.cavities()
    assert cavities is not None
    ((area, width, corners),) = cavities
    assert area == pytest.approx(14.0, abs=1e-12)
    assert width is None
    assert len(corners) == 6


def test_a_piece_standing_in_the_open_gets_no_answer() -> None:
    """It makes a hole in the uncovered region, which the cavity rules do not cover."""
    state = _native.Assembly(TRAY, [rectangle(1, 1)], **TOL)
    state.place(0, (2.0, 2.0, 0.0))
    assert state.cavities() is None


def test_a_covered_tray_has_no_cavity() -> None:
    state = _native.Assembly(TRAY, [rectangle(4, 4)], **TOL)
    state.place(0, (2.0, 2.0, 0.0))
    assert state.cavities() == []


# --- roofs --------------------------------------------------------------------------------

# Two 2 by 4 strips whose roofs rise towards the seam between them at 0.25 mm/mm:
# 20 mm at their centres, 20.25 at the seam.
RIDGE = [(20.0, 0.25, 0.0), (20.0, -0.25, 0.0)]


def ridge(roofs: list[tuple[float, float, float]] = RIDGE) -> _native.Assembly:
    return _native.Assembly(TRAY, [rectangle(2, 4), rectangle(2, 4)], roofs, **TOL)


def test_roofs_that_meet_have_no_step() -> None:
    state = ridge()
    state.place(0, (1.0, 2.0, 0.0))
    assert state.roof_step(1, (3.0, 2.0, 0.0)) == pytest.approx(0.0, abs=1e-12)
    # Away from the first strip there is no shared edge, and so no step.
    assert state.roof_step(1, (3.5, 2.0, 0.0)) == 0.0


def test_a_step_is_measured_where_it_is_largest() -> None:
    """Turn the second strip half round: its roof now falls away from the seam.

    At the seam the first roof is at 20.25 and the second, with its low edge
    there, at 20 - 0.25 = 19.75: a step of 0.5 all along.

    Give the second roof a slope along the seam instead and the step grows
    along it: with gradient (-0.25, 0.1) the roofs agree at the seam's middle
    and differ by 0.1 * 2 = 0.2 at its ends.
    """
    state = ridge()
    state.place(0, (1.0, 2.0, 0.0))
    assert state.roof_step(1, (3.0, 2.0, math.pi)) == pytest.approx(0.5, abs=1e-12)
    tilted = ridge([RIDGE[0], (20.0, -0.25, 0.1)])
    tilted.place(0, (1.0, 2.0, 0.0))
    assert tilted.roof_step(1, (3.0, 2.0, 0.0)) == pytest.approx(0.2, abs=1e-12)


def test_proposals_leave_out_placements_whose_roofs_do_not_meet() -> None:
    state = ridge()
    state.place(0, (1.0, 2.0, 0.0))
    (corner,) = [c for c in state.frontier() if (c.x, c.y) == (2.0, 0.0)]
    proposals = state.propose(corner)
    # A roofed strip is not its own half turn, so each of its four corners is tried.
    # Two lay it across the gap, 4 wide where 2 are left, and stick out of the tray.
    # The other two fit; only one of them continues the roof.
    assert [(c.piece, round(c.theta, 9)) for c in proposals] == [(1, 0.0)]
    generated, outside, overlap, roof = state.stats()
    assert (generated, outside + overlap, roof) == (4, 2, 1)
    # Without roofs both ways are proposed, as one: the strip is its own half turn.
    bare = _native.Assembly(TRAY, [rectangle(2, 4), rectangle(2, 4)], **TOL)
    bare.place(0, (1.0, 2.0, 0.0))
    (corner,) = [c for c in bare.frontier() if (c.x, c.y) == (2.0, 0.0)]
    assert len(bare.propose(corner)) == 1
    assert bare.stats()[3] == 0


def test_a_height_tolerance_must_be_positive() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        _native.Assembly(TRAY, [rectangle(2, 4)], **TOL, height_tol=0.0)
    with pytest.raises(ValueError, match="no piece 3"):
        ridge().roof_step(3, (0.0, 0.0, 0.0))


# --- canonical forms ----------------------------------------------------------------------

STRIPS = [rectangle(1, 4), rectangle(3, 4)]
# The narrow strip against the left wall, and that assembly turned with the tray by
# quarter turns about (2, 2): against the bottom, the right and the top.
LEFT = [(0.5, 2.0, 0.0), (2.5, 2.0, 0.0)]
TURNS = [
    LEFT,
    [(2.0, 0.5, math.pi / 2), (2.0, 2.5, math.pi / 2)],
    [(3.5, 2.0, math.pi), (1.5, 2.0, math.pi)],
    [(2.0, 3.5, -math.pi / 2), (2.0, 1.5, -math.pi / 2)],
]


def test_the_turns_of_an_assembly_have_one_canonical_form() -> None:
    form = _native.canonical_poses(TRAY, STRIPS, None, LEFT, **TOL)
    for turn in TURNS:
        assert _native.same_assembly(TRAY, STRIPS, None, LEFT, turn, **TOL)
        again = _native.canonical_poses(TRAY, STRIPS, None, turn, **TOL)
        for (x, y, theta), (u, v, phi) in zip(form, again, strict=True):
            assert (x, y, theta) == pytest.approx((u, v, phi), abs=1e-9)
    # The form is itself one of the four, with the strip's half turn taken out.
    assert any(
        all(
            math.dist(p[:2], q[:2]) <= 1e-9 and abs(math.remainder(p[2] - q[2], math.pi)) <= 1e-9
            for p, q in zip(form, turn, strict=True)
        )
        for turn in TURNS
    )


def test_a_shifted_piece_is_another_assembly() -> None:
    shifted = [LEFT[0], (2.5, 2.0 + 1e-3, 0.0)]
    assert not _native.same_assembly(TRAY, STRIPS, None, LEFT, shifted, **TOL)
    # Within the tolerance it is the same one.
    nudged = [LEFT[0], (2.5, 2.0 + 1e-9, 0.0)]
    assert _native.same_assembly(TRAY, STRIPS, None, LEFT, nudged, **TOL)


def test_congruent_pieces_may_change_places_and_others_may_not() -> None:
    tray = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]
    pieces = [rectangle(1, 3), rectangle(1, 3), rectangle(2, 3)]
    one = [(0.5, 1.5, 0.0), (1.5, 1.5, 0.0), (3.0, 1.5, 0.0)]
    swapped = [one[1], one[0], one[2]]
    between = [(0.5, 1.5, 0.0), (3.5, 1.5, 0.0), (2.0, 1.5, 0.0)]
    assert _native.same_assembly(tray, pieces, None, one, swapped, **TOL)
    assert not _native.same_assembly(tray, pieces, None, one, between, **TOL)


def test_a_roof_makes_a_turned_piece_a_different_piece() -> None:
    """Without roofs a strip is its own half turn. With a sloping roof it is not."""
    half_turned = [(0.5, 2.0, math.pi), LEFT[1]]
    assert _native.same_assembly(TRAY, STRIPS, None, LEFT, half_turned, **TOL)
    roofs = [(20.0, 0.25, 0.0), (20.0, 0.25, 0.0)]
    assert not _native.same_assembly(TRAY, STRIPS, roofs, LEFT, half_turned, **TOL)


def test_canonical_forms_refuse_what_does_not_fit_the_puzzle() -> None:
    with pytest.raises(ValueError, match="1 poses for 2 pieces"):
        _native.canonical_poses(TRAY, STRIPS, None, LEFT[:1], **TOL)
    with pytest.raises(ValueError, match="3 poses for 2 pieces"):
        _native.same_assembly(TRAY, STRIPS, None, LEFT, [*LEFT, LEFT[0]], **TOL)
    with pytest.raises(ValueError, match="1 roofs for 2 pieces"):
        _native.canonical_poses(TRAY, STRIPS, [(1.0, 0.0, 0.0)], LEFT, **TOL)
    with pytest.raises(ValueError, match="not a strictly convex"):
        _native.canonical_poses(TRAY, [STRIPS[0][::-1], STRIPS[1]], None, LEFT, **TOL)


# --- contact_dfs --------------------------------------------------------------------------


def test_the_search_returns_poses_in_piece_order_and_its_counts() -> None:
    outcome = _native.contact_dfs(TRAY, STRIPS, **TOL, max_solutions=None)
    assert outcome.exhausted
    assert outcome.tray_order == 4
    # The wide strip is the larger of two pieces that are congruent to nothing else.
    assert outcome.anchor == 1
    (poses,) = outcome.solutions
    assert len(poses) == 2
    assert any(_native.same_assembly(TRAY, STRIPS, None, poses, turn, **TOL) for turn in TURNS)
    assert outcome.nodes >= 3 and outcome.max_depth == 2
    assert outcome.cavities_unknown == 0
    assert outcome.first_solution_s is not None
    assert 0.0 <= outcome.first_solution_s <= outcome.wall_time_s

    every = _native.contact_dfs(TRAY, STRIPS, **TOL, max_solutions=None, all_tray_rotations=True)
    assert len(every.solutions) == 4 and every.anchor is None


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"order": "backwards"}, "order must be generated, matched-edges or random"),
        ({"time_limit_s": -1.0}, "time_limit_s must be finite and not negative"),
        ({"time_limit_s": math.inf}, "time_limit_s must be finite and not negative"),
        ({"height_tol": -1.0}, "finite and positive"),
    ],
)
def test_the_search_refuses_bad_arguments(arguments: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _native.contact_dfs(TRAY, STRIPS, **{**TOL, **arguments})


def test_the_search_refuses_bad_puzzles() -> None:
    with pytest.raises(ValueError, match="piece 0 is not a strictly convex"):
        _native.contact_dfs(TRAY, [STRIPS[0][::-1]], **TOL)
    with pytest.raises(ValueError, match="1 roofs for 2 pieces"):
        _native.contact_dfs(TRAY, STRIPS, [(1.0, 0.0, 0.0)], **TOL)
