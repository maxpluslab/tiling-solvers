"""Phase 2 exit criterion: every answer key validates, and every way of spoiling one is caught.

A key that passes shows the validator accepts a real solution. That alone would
also be true of a validator that accepts everything, so each check is also made
to fail: every piece of every fixture is shifted, turned and swapped, and relief
assemblies are rearranged so that they still tile but their roofs no longer meet.
"""

import math
from typing import Any

import pytest

from maxplus_solvers import Pose, PuzzleInstance
from maxplus_solvers.validation import ValidationReport, validate_solution
from support import corpus, geometry

ALL = corpus.fixture_ids()
RELIEF = corpus.fixture_ids(regime="relief")

# Well clear of the 0.864 mm depth tolerance, small against the pieces.
SHIFT_MM = 5.0
TURN = math.radians(20.0)


def load(fixture_id: str) -> tuple[PuzzleInstance, dict[str, Pose]]:
    instance = PuzzleInstance.from_dict(corpus.fixture(fixture_id))
    poses = {pid: Pose(**pose) for pid, pose in corpus.key(fixture_id)["poses"].items()}
    return instance, poses


def geometric_failure(report: ValidationReport) -> bool:
    """Caught by a depth check, not merely by the looser area check."""
    return not report.no_overlap or not report.inside


# --- the keys validate ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_answer_key_validates(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    report = validate_solution(instance, poses)
    assert report.solved, report.failed
    # Far inside the tolerances: the keys are exact assemblies, up to rounding.
    assert report.overlaps == ()
    assert report.worst_overlap_depth_mm == 0.0
    assert report.worst_outside_mm == 0.0
    assert report.outside_area_mm2 == pytest.approx(0.0, abs=1e-6)
    assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_the_keyed_roof_is_continuous_along_every_seam(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    report = validate_solution(instance, poses)
    assert report.worst_roof_mismatch_mm == pytest.approx(0.0, abs=1e-6)
    # Every piece touches another along an edge, or the check would be looking at nothing.
    assert {s.a for s in report.seams} | {s.b for s in report.seams} == {
        p.id for p in instance.pieces
    }
    assert all(s.length_mm >= report.tolerances.edge_min_overlap_mm for s in report.seams)


@pytest.mark.parametrize("fixture_id", [f for f in ALL if f not in RELIEF])
def test_footprint_keys_have_no_roof_verdict(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    report = validate_solution(instance, poses)
    assert report.worst_roof_mismatch_mm is None and report.seams == ()


# --- spoiled keys are refused -----------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_a_shifted_piece_is_caught(fixture_id: str) -> None:
    """Any piece, 5 mm in any of four directions: it enters a neighbour or leaves the tray."""
    instance, poses = load(fixture_id)
    for pid, pose in poses.items():
        for dx, dy in ((SHIFT_MM, 0.0), (-SHIFT_MM, 0.0), (0.0, SHIFT_MM), (0.0, -SHIFT_MM)):
            spoiled = {**poses, pid: Pose(pose.x + dx, pose.y + dy, pose.theta)}
            report = validate_solution(instance, spoiled)
            assert geometric_failure(report), (pid, dx, dy, report.residuals())


@pytest.mark.parametrize("fixture_id", ALL)
def test_a_rotated_piece_is_caught(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    for pid, pose in poses.items():
        for turn in (TURN, -TURN):
            spoiled = {**poses, pid: Pose(pose.x, pose.y, pose.theta + turn)}
            report = validate_solution(instance, spoiled)
            assert geometric_failure(report), (pid, turn, report.residuals())


def congruent(a: Any, b: Any) -> bool:
    """Same shape up to a rotation: equal as cyclic sequences of side lengths and turning angles."""

    def signature(polygon: Any) -> list[tuple[float, float]]:
        n = len(polygon)
        out = []
        for i in range(n):
            p, q, r = polygon[i], polygon[(i + 1) % n], polygon[(i + 2) % n]
            turn = math.atan2(
                (q[0] - p[0]) * (r[1] - q[1]) - (q[1] - p[1]) * (r[0] - q[0]),
                (q[0] - p[0]) * (r[0] - q[0]) + (q[1] - p[1]) * (r[1] - q[1]),
            )
            out.append((math.dist(p, q), turn))
        return out

    sa, sb = signature(a), signature(b)
    n = len(sa)
    return n == len(sb) and any(
        all(
            math.isclose(sa[i][k], sb[(i + s) % n][k], abs_tol=1e-6)
            for i in range(n)
            for k in (0, 1)
        )
        for s in range(n)
    )


def trade_places(poses: dict[str, Pose], first: str, second: str) -> dict[str, Pose]:
    """Exchange where two pieces sit. Each keeps its own orientation."""
    a, b = poses[first], poses[second]
    return {**poses, first: Pose(b.x, b.y, a.theta), second: Pose(a.x, a.y, b.theta)}


@pytest.mark.parametrize("fixture_id", ALL)
def test_two_swapped_pieces_are_caught(fixture_id: str) -> None:
    """Each piece trades places with the next one of a different shape."""
    instance, poses = load(fixture_id)
    pieces = instance.pieces
    swaps = 0
    for i, first in enumerate(pieces):
        second = next(
            (p for p in pieces[i + 1 :] + pieces[:i] if not congruent(first.polygon, p.polygon)),
            None,
        )
        if second is None:
            continue
        swaps += 1
        report = validate_solution(instance, trade_places(poses, first.id, second.id))
        assert geometric_failure(report), (first.id, second.id, report.residuals())
    if fixture_id in ("syn-four-squares", "syn-four-triangles"):
        assert swaps == 0, "identical pieces: there is no pair of different shapes"
    else:
        assert swaps == len(pieces)


def test_swapping_identical_pieces_changes_nothing() -> None:
    """Four squares that all sit the same way round: any two can trade places."""
    instance, poses = load("syn-four-squares")
    ids = list(poses)
    for i, first in enumerate(ids):
        for second in ids[i + 1 :]:
            report = validate_solution(instance, trade_places(poses, first, second))
            assert report.solved
            assert report.worst_overlap_depth_mm == 0.0
            assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)


# --- assemblies that tile but whose roofs do not meet -----------------------------------------


@pytest.mark.parametrize(
    ("turned", "step"),
    [(("narrow",), 12.0), (("wide",), 6.0), (("narrow", "wide"), 6.0)],
)
def test_the_ridge_with_a_strip_half_turned_fails_only_the_roof_check(
    turned: tuple[str, ...], step: float
) -> None:
    """The strips meet at 20|20. Half-turned they meet at 8|20, 20|14 or 8|14 (see synthetic.py)."""
    instance, poses = load("syn-two-rectangles-ridge")
    source = corpus.key("syn-two-rectangles-ridge")["sourceIds"]
    spoiled = {
        pid: Pose(p.x, p.y, p.theta + math.pi) if source[pid] in turned else p
        for pid, p in poses.items()
    }
    report = validate_solution(instance, spoiled)
    assert report.failed == ("roof",)
    assert report.worst_roof_mismatch_mm == pytest.approx(step, abs=1e-9)
    assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)
    # Without the roofs, the same poses are a solution.
    assert validate_solution(instance.as_regime("footprint"), spoiled).solved


def half_turn_symmetric(fixture_id: str) -> list[str]:
    """Pieces whose footprint is unchanged by half a turn, such as rectangles."""
    found = []
    for piece in corpus.fixture(fixture_id)["pieces"]:
        turned = [(-x, -y) for x, y in piece["polygon"]]
        if geometry.vertex_set_distance(piece["polygon"], turned) < 1e-6:
            found.append(piece["id"])
    return found


HALF_TURNS = [
    (f, pid)
    for f in corpus.fixture_ids(kind="corpus", regime="relief")
    for pid in half_turn_symmetric(f)
]


LEVEL_ROOFED = {
    (fixture_id, piece["id"])
    for fixture_id, pid in HALF_TURNS
    for piece in corpus.fixture(fixture_id)["pieces"]
    if piece["id"] == pid and math.hypot(piece["roof"]["gx"], piece["roof"]["gy"]) < 1e-12
}


def test_the_corpus_has_pieces_that_fit_two_ways() -> None:
    """Otherwise the test below would be vacuous."""
    assert len(HALF_TURNS) >= 10
    assert len({fixture_id for fixture_id, _ in HALF_TURNS}) >= 4


@pytest.mark.parametrize(("fixture_id", "pid"), HALF_TURNS, ids=[f"{f}:{p}" for f, p in HALF_TURNS])
def test_a_half_turned_symmetric_piece_fails_only_the_roof_check(fixture_id: str, pid: str) -> None:
    """The footprints still tile exactly; only the sloping top gives the piece away."""
    instance, poses = load(fixture_id)
    pose = poses[pid]
    spoiled = {**poses, pid: Pose(pose.x, pose.y, pose.theta + math.pi)}
    report = validate_solution(instance, spoiled)
    assert report.overlaps == ()
    assert report.uncovered_area_mm2 == pytest.approx(0.0, abs=1e-6)
    assert validate_solution(instance.as_regime("footprint"), spoiled).solved
    if (fixture_id, pid) in LEVEL_ROOFED:
        # A level top looks the same either way round: this is a second solution, not an error.
        assert report.solved
        assert report.worst_roof_mismatch_mm == pytest.approx(0.0, abs=1e-6)
    else:
        assert report.failed == ("roof",), report.residuals()


def test_level_roofed_symmetric_pieces_are_the_known_ones() -> None:
    """Relief does not pin these down. Recorded so that the corpus cannot change unnoticed."""
    assert {("rat1", "p02")} == LEVEL_ROOFED
