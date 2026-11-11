"""The validator on assemblies small enough to work out by hand.

Four 72 mm squares in a 144 mm tray, and the two roofed strips of
``support.documents``. Tolerances are the published ones: 0.864 mm of depth,
248.832 mm² of area, 1.75 mm of roof.
"""

import math

import pytest

from maxplus_solvers import Piece, Pose, PuzzleInstance, Regime, Solution, TolerancePolicy
from maxplus_solvers.models import ValidationConstants
from maxplus_solvers.validation import penetration_depth, validate_solution
from support import documents

MM = 1e-9
MM2 = 1e-6
SQUARE = ((-36.0, -36.0), (36.0, -36.0), (36.0, 36.0), (-36.0, 36.0))
TRAY = ((-72.0, -72.0), (72.0, -72.0), (72.0, 72.0), (-72.0, 72.0))


def four_squares() -> PuzzleInstance:
    return PuzzleInstance(
        id="squares",
        regime=Regime.FOOTPRINT,
        target=TRAY,
        pieces=tuple(Piece(name, SQUARE) for name in ("sw", "se", "ne", "nw")),
        span_mm=144.0,
        validation=ValidationConstants(1e-6, 0.006, 0.006, 0.012, 3.0, 0.02),
    )


def solved_squares() -> dict[str, Pose]:
    return {
        "sw": Pose(-36.0, -36.0, 0.0),
        "se": Pose(36.0, -36.0, 0.0),
        "ne": Pose(36.0, 36.0, 0.0),
        "nw": Pose(-36.0, 36.0, 0.0),
    }


def moved(poses: dict[str, Pose], piece: str, dx: float, dy: float, turn: float = 0.0) -> dict:
    out = dict(poses)
    p = poses[piece]
    out[piece] = Pose(p.x + dx, p.y + dy, p.theta + turn)
    return out


# --- penetration depth ------------------------------------------------------------

UNIT = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def shifted(polygon: tuple, dx: float, dy: float) -> tuple:
    return tuple((x + dx, y + dy) for x, y in polygon)


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [
        (0.7, 0.0, 0.3),  # overlap 0.3 wide: slide 0.3 to separate
        (0.7, 0.9, 0.1),  # 0.3 by 0.1: the short way out is 0.1
        (1.0, 0.0, 0.0),  # sharing an edge
        (1.0, 1.0, 0.0),  # sharing a corner
        (1.5, 0.0, -0.5),  # half a unit apart
        (0.0, 0.0, 1.0),  # coincident
    ],
)
def test_penetration_depth_of_two_unit_squares(dx: float, dy: float, expected: float) -> None:
    assert penetration_depth(UNIT, shifted(UNIT, dx, dy)) == pytest.approx(expected, abs=1e-12)
    assert penetration_depth(shifted(UNIT, dx, dy), UNIT) == pytest.approx(expected, abs=1e-12)


def test_penetration_depth_uses_the_slanted_axis() -> None:
    """A corner poking 0.1 through a hypotenuse separates along the hypotenuse's normal."""
    triangle = ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0))
    # The hypotenuse is x + y = 2. A unit square whose near corner is at (1.05, 1.05)
    # reaches 0.1 / sqrt(2) past the midpoint (1, 1) ... measured along (1, 1)/sqrt(2):
    # the triangle extends to 2/sqrt(2), the square starts at 2.1/sqrt(2).
    square = shifted(UNIT, 0.95, 0.95)
    # Corner at (0.95, 0.95): starts at 1.9/sqrt(2), so it is 0.1/sqrt(2) inside.
    assert penetration_depth(triangle, square) == pytest.approx(0.1 / math.sqrt(2), abs=1e-12)


# --- the solved assembly -------------------------------------------------------------


def test_a_tight_assembly_is_solved_with_zero_residuals() -> None:
    report = validate_solution(four_squares(), solved_squares())
    assert report.solved and report.failed == ()
    assert report.no_overlap and report.inside and report.area and report.roof
    assert report.overlaps == ()  # contact along edges is not overlap
    assert report.worst_overlap_depth_mm == 0.0
    assert report.worst_outside_mm == 0.0
    assert report.overlap_area_mm2 == 0.0
    assert report.outside_area_mm2 == pytest.approx(0.0, abs=MM2)
    assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=MM2)
    assert report.worst_roof_mismatch_mm is None and report.seams == ()


def test_the_default_tolerances_are_the_instance_policy() -> None:
    instance = four_squares()
    report = validate_solution(instance, solved_squares())
    assert report.tolerances == TolerancePolicy.from_instance(instance)
    assert report.tolerances.overlap_depth_mm == pytest.approx(0.864, abs=1e-12)


def test_a_solution_object_is_accepted() -> None:
    assert validate_solution(four_squares(), Solution(solved_squares())).solved


def test_residuals_are_reported_by_name() -> None:
    residuals = validate_solution(
        four_squares(), moved(solved_squares(), "ne", -10.0, 0.0)
    ).residuals()
    assert set(residuals) == {
        "overlap_depth_mm", "outside_mm",
        "overlap_area_mm2", "outside_area_mm2", "uncovered_area_mm2",
    }  # fmt: skip
    assert residuals["overlap_depth_mm"] == pytest.approx(10.0, abs=MM)


# --- overlap ---------------------------------------------------------------------------


def test_a_piece_pushed_into_its_neighbour() -> None:
    """ne moved 10 mm left: a 10 by 72 strip overlaps nw, and a 10 by 72 strip is vacated."""
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", -10.0, 0.0))
    assert report.failed == ("overlap", "area")
    assert report.worst_overlap_depth_mm == pytest.approx(10.0, abs=MM)
    assert report.overlap_area_mm2 == pytest.approx(720.0, abs=MM2)
    assert report.uncovered_area_mm2 == pytest.approx(720.0, abs=MM2)
    assert report.outside_area_mm2 == pytest.approx(0.0, abs=MM2)
    assert report.worst_outside_mm == 0.0
    (pair,) = report.overlaps
    assert {pair.a, pair.b} == {"ne", "nw"}
    assert pair.depth_mm == pytest.approx(10.0, abs=MM)
    assert pair.area_mm2 == pytest.approx(720.0, abs=MM2)


def test_a_small_overlap_is_within_tolerance_and_still_reported() -> None:
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", -0.5, 0.0))
    assert report.solved
    assert report.worst_overlap_depth_mm == pytest.approx(0.5, abs=MM)
    assert report.overlap_area_mm2 == pytest.approx(36.0, abs=MM2)
    assert report.uncovered_area_mm2 == pytest.approx(36.0, abs=MM2)


def test_depth_catches_a_thin_misfit_that_area_would_accept() -> None:
    """1 mm of overlap is only 72 mm², well inside the area tolerance, but too deep."""
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", -1.0, 0.0))
    assert report.failed == ("overlap",)
    assert report.area


def test_the_tolerance_boundary_is_where_the_policy_puts_it() -> None:
    just_inside = validate_solution(four_squares(), moved(solved_squares(), "ne", -0.86, 0.0))
    just_outside = validate_solution(four_squares(), moved(solved_squares(), "ne", -0.87, 0.0))
    assert just_inside.no_overlap and not just_outside.no_overlap


def test_penetration_below_the_contact_noise_is_not_an_overlap() -> None:
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", -1e-5, 0.0))
    assert report.overlaps == () and report.worst_overlap_depth_mm == 0.0


def test_a_small_square_inside_a_large_one_is_as_deep_as_the_way_out() -> None:
    """A unit square 3 from the left of a 10 by 10: the shared extent is 1, but leaving takes 4.

    The browser's formula would say 1. Sliding by 1 would not separate them.
    """
    big = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    small = shifted(UNIT, 3.0, 4.5)
    assert penetration_depth(big, small) == pytest.approx(4.0, abs=1e-12)
    assert penetration_depth(small, big) == pytest.approx(4.0, abs=1e-12)


def test_a_turned_piece_overlaps_its_two_neighbours() -> None:
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", 0.0, 0.0, math.pi / 4))
    assert "overlap" in report.failed and "inside" in report.failed
    # A corner of a 72 mm square turned an eighth reaches 36*sqrt(2) from its centre,
    # which is 36*(sqrt(2)-1) past the wall.
    assert report.worst_outside_mm == pytest.approx(36.0 * (math.sqrt(2) - 1), abs=MM)
    # The diamond reaches into nw and se. It stops short of the tray's centre, so not sw.
    assert {frozenset((o.a, o.b)) for o in report.overlaps} == {
        frozenset(("ne", "nw")), frozenset(("ne", "se")),
    }  # fmt: skip


def test_stacked_pieces_leave_exactly_the_rest_uncovered() -> None:
    """All four on one spot: three quarters of the tray are bare, however the pile overlaps."""
    poses: dict[str, Pose] = dict.fromkeys(solved_squares(), Pose(-36.0, -36.0, 0.0))
    report = validate_solution(four_squares(), poses)
    assert report.uncovered_area_mm2 == pytest.approx(3 * 72.0 * 72.0, abs=MM2)
    assert report.overlap_area_mm2 == pytest.approx(6 * 72.0 * 72.0, abs=MM2)  # six pairs
    assert report.worst_overlap_depth_mm == pytest.approx(72.0, abs=MM)
    assert report.failed == ("overlap", "area")


# --- inside ----------------------------------------------------------------------------


def test_a_piece_pushed_through_a_wall() -> None:
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", 10.0, 0.0))
    assert report.failed == ("inside", "area")
    assert report.worst_outside_mm == pytest.approx(10.0, abs=MM)
    assert report.outside_mm == {"sw": 0.0, "se": 0.0, "ne": pytest.approx(10.0, abs=MM), "nw": 0.0}
    assert report.outside_area_mm2 == pytest.approx(720.0, abs=MM2)
    assert report.uncovered_area_mm2 == pytest.approx(720.0, abs=MM2)
    assert report.overlaps == ()


def test_outside_depth_past_a_corner_is_the_euclidean_distance() -> None:
    """3 right and 4 up puts the corner 5 mm from the tray. The browser would say 4."""
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", 3.0, 4.0))
    assert report.worst_outside_mm == pytest.approx(5.0, abs=MM)


def test_a_piece_left_beside_the_tray() -> None:
    report = validate_solution(four_squares(), moved(solved_squares(), "ne", 500.0, 0.0))
    assert report.failed == ("inside", "area")
    assert report.uncovered_area_mm2 == pytest.approx(72.0 * 72.0, abs=MM2)
    assert report.outside_area_mm2 == pytest.approx(72.0 * 72.0, abs=MM2)


# --- policy and input checking -----------------------------------------------------------


def test_a_stricter_policy_refuses_what_the_default_accepts() -> None:
    poses = moved(solved_squares(), "ne", -0.5, 0.0)
    strict = TolerancePolicy(1e-9, 0.1, 0.1, 1.0, math.radians(3.0), 2.88)
    assert validate_solution(four_squares(), poses).solved
    assert validate_solution(four_squares(), poses, strict).failed == ("overlap", "area")


@pytest.mark.parametrize("change", ["missing", "extra", "renamed"])
def test_poses_must_name_exactly_the_pieces(change: str) -> None:
    poses = solved_squares()
    if change != "extra":
        del poses["ne"]
    if change != "missing":
        poses["p99"] = Pose(0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="poses do not match"):
        validate_solution(four_squares(), poses)


# --- roofs -------------------------------------------------------------------------------
# Two 72 by 144 strips. p00 sits on the left and rises to the right at 0.25; p01 mirrors it.
# Both are 20 mm high at their centres, so 20 + 0.25*36 = 29 mm where they meet.


def strips(regime: str = "relief") -> PuzzleInstance:
    doc = {"relief": documents.relief, "tropical-aware": documents.tropical_aware}[regime]()
    return PuzzleInstance.from_dict(doc)


def solved_strips() -> dict[str, Pose]:
    return {"p00": Pose(-36.0, 0.0, 0.0), "p01": Pose(36.0, 0.0, 0.0)}


@pytest.mark.parametrize("regime", ["relief", "tropical-aware"])
def test_a_continuous_roof_passes(regime: str) -> None:
    report = validate_solution(strips(regime), solved_strips())
    assert report.solved
    assert report.worst_roof_mismatch_mm == pytest.approx(0.0, abs=MM)
    (seam,) = report.seams
    assert (seam.a, seam.b) == ("p00", "p01")
    assert seam.length_mm == pytest.approx(144.0, abs=MM)
    assert "roof_mismatch_mm" in report.residuals()


def test_a_half_turned_strip_tiles_but_breaks_the_roof() -> None:
    """Turned, p01 is 20 - 9 = 11 mm high at the seam against 29: a step of 18 mm, nothing else."""
    report = validate_solution(strips(), moved(solved_strips(), "p01", 0.0, 0.0, math.pi))
    assert report.failed == ("roof",)
    assert report.worst_roof_mismatch_mm == pytest.approx(18.0, abs=MM)
    assert report.no_overlap and report.inside and report.area


def test_the_footprint_view_of_the_same_assembly_has_no_roof_to_fail() -> None:
    flat = strips().as_regime("footprint")
    report = validate_solution(flat, moved(solved_strips(), "p01", 0.0, 0.0, math.pi))
    assert report.solved
    assert report.worst_roof_mismatch_mm is None and report.seams == ()
    assert "roof_mismatch_mm" not in report.residuals()


@pytest.mark.parametrize(
    ("step", "passes"), [(1.0, True), (1.74, True), (1.76, False), (5.0, False)]
)
def test_the_roof_tolerance_is_a_twentieth_of_the_relief(step: float, passes: bool) -> None:
    doc = documents.relief()
    doc["pieces"][1]["roof"]["z0"] += step
    report = validate_solution(PuzzleInstance.from_dict(doc), solved_strips())
    assert report.worst_roof_mismatch_mm == pytest.approx(step, abs=MM)
    assert report.roof is passes
    assert report.failed == (() if passes else ("roof",))


def test_a_roof_that_matches_at_one_end_only_is_measured_at_the_other() -> None:
    """Tilt p01 along the seam by 0.01 mm per mm: zero at the middle, 0.72 mm at either end."""
    doc = documents.relief()
    doc["pieces"][1]["roof"]["gy"] = 0.01
    report = validate_solution(PuzzleInstance.from_dict(doc), solved_strips())
    assert report.worst_roof_mismatch_mm == pytest.approx(0.72, abs=MM)


def test_a_small_gap_between_roofed_pieces_is_still_a_seam() -> None:
    """1 mm apart is within twice the depth tolerance. Heights are compared on the midline."""
    report = validate_solution(strips(), moved(solved_strips(), "p01", 1.0, 0.0))
    (seam,) = report.seams
    assert seam.length_mm == pytest.approx(144.0, abs=MM)
    # On x = 0.5: p00 gives 20 + 0.25*36.5, p01 (centre now at 37) gives 20 + 0.25*36.5.
    assert seam.mismatch_mm == pytest.approx(0.0, abs=MM)


def test_pieces_too_far_apart_or_barely_alongside_share_no_seam() -> None:
    apart = validate_solution(strips(), moved(solved_strips(), "p01", 2.0, 0.0))
    assert apart.seams == ()  # 2 mm > 2 * 0.864
    barely = validate_solution(strips(), moved(solved_strips(), "p01", 0.0, 142.0))
    assert barely.seams == ()  # 2 mm alongside < 2.88
    enough = validate_solution(strips(), moved(solved_strips(), "p01", 0.0, 140.0))
    assert [round(s.length_mm, 9) for s in enough.seams] == [4.0]


def test_edges_that_are_not_antiparallel_within_three_degrees_share_no_seam() -> None:
    turned = validate_solution(strips(), moved(solved_strips(), "p01", 0.0, 0.0, math.radians(4.0)))
    assert turned.seams == ()


def test_a_roofed_instance_needs_a_roof_tolerance() -> None:
    no_roof_tolerance = TolerancePolicy(1e-4, 0.864, 0.864, 248.832, math.radians(3.0), 2.88)
    with pytest.raises(ValueError, match="roof tolerance"):
        validate_solution(strips(), solved_strips(), no_roof_tolerance)
