"""Phase 3 exit criterion: the Rust geometry agrees with the Shapely validator.

Fixture pieces are thrown at seeded random poses and every quantity the search
will rely on is computed twice: by ``_native``, and by the validator, Shapely or
the Python models, none of which shares code with the Rust kernel.

Tolerances, stated once:

* lengths (penetration depth, outside depth, roof heights): ``1e-9`` mm;
* areas (intersection, area outside the target): ``1e-6`` mm², on areas of up to
  20736 mm².

Agreement to these tolerances is numerical evidence that the two implementations
compute the same thing. It is not a proof of either.
"""

import math
import random
from collections.abc import Sequence
from itertools import combinations

import pytest
import shapely

from maxplus_solvers import Pose, PuzzleInstance, TolerancePolicy, _native
from maxplus_solvers.validation import penetration_depth, validate_solution
from support import corpus

ALL = corpus.fixture_ids()
RELIEF = corpus.fixture_ids(regime="relief")

LENGTH_TOL = 1e-9
AREA_TOL = 1e-6

PAIR_TRIALS = 60
PLACEMENT_TRIALS = 40
ASSEMBLY_TRIALS = 8


def load(fixture_id: str) -> tuple[PuzzleInstance, dict[str, Pose]]:
    instance = PuzzleInstance.from_dict(corpus.fixture(fixture_id))
    poses = {pid: Pose(**pose) for pid, pose in corpus.key(fixture_id)["poses"].items()}
    return instance, poses


def rng_for(fixture_id: str, purpose: str) -> random.Random:
    """Seeded by name, so every run and every platform sees the same poses."""
    return random.Random(f"phase-3:{purpose}:{fixture_id}")


def as_tuple(pose: Pose) -> tuple[float, float, float]:
    return (pose.x, pose.y, pose.theta)


def radius(polygon: Sequence[Sequence[float]]) -> float:
    """Distance from the local origin, which is the centroid, to the farthest vertex."""
    return max(math.hypot(x, y) for x, y in polygon)


def random_pose(rng: random.Random, reach: float) -> Pose:
    return Pose(
        rng.uniform(-reach, reach), rng.uniform(-reach, reach), rng.uniform(-math.pi, math.pi)
    )


# --- two pieces at random poses -----------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_pairs_of_pieces_at_random_poses(fixture_id: str) -> None:
    """Placement, penetration depth and shared area of two fixture pieces."""
    instance, _ = load(fixture_id)
    rng = rng_for(fixture_id, "pairs")
    overlapping = apart = 0
    for _ in range(PAIR_TRIALS):
        first, second = rng.sample(instance.pieces, 2)
        pose_a = random_pose(rng, instance.span_mm / 2.0)
        # Within reach of the first piece, so that the two sometimes meet and sometimes do not.
        reach = 1.2 * (radius(first.polygon) + radius(second.polygon))
        pose_b = Pose(
            pose_a.x + rng.uniform(-reach, reach),
            pose_a.y + rng.uniform(-reach, reach),
            rng.uniform(-math.pi, math.pi),
        )
        expected_a, expected_b = first.world_polygon(pose_a), second.world_polygon(pose_b)
        a = _native.transform(first.polygon, as_tuple(pose_a))
        b = _native.transform(second.polygon, as_tuple(pose_b))
        for ours, theirs in ((a, expected_a), (b, expected_b)):
            assert len(ours) == len(theirs)
            assert max(math.dist(p, q) for p, q in zip(ours, theirs, strict=True)) <= LENGTH_TOL

        depth = _native.penetration_depth(a, b)
        assert depth == pytest.approx(penetration_depth(expected_a, expected_b), abs=LENGTH_TOL)
        shape_a, shape_b = shapely.Polygon(expected_a), shapely.Polygon(expected_b)
        shared = shape_a.intersection(shape_b).area
        assert _native.intersection_area(a, b) == pytest.approx(shared, abs=AREA_TOL)
        assert _native.intersection_area(b, a) == pytest.approx(shared, abs=AREA_TOL)
        if depth > 1e-6:
            overlapping += 1
            assert shared > 0.0
        elif depth < -1e-6:
            apart += 1
            assert shared == 0.0
            assert shape_a.distance(shape_b) >= -depth - LENGTH_TOL
    # Both cases were seen, or the comparison above checked only one of them.
    assert overlapping >= 5 and apart >= 5, (overlapping, apart)


@pytest.mark.parametrize("fixture_id", ALL)
def test_pieces_at_random_poses_against_the_target(fixture_id: str) -> None:
    """Outside depth and outside area of a fixture piece: where it belongs, then anywhere."""
    instance, keyed = load(fixture_id)
    assert _native.is_convex_ccw(instance.target), "the convex routines need a convex target"
    target = shapely.Polygon(instance.target)
    rng = rng_for(fixture_id, "target")
    inside = outside = 0
    placements = [(piece, keyed[piece.id]) for piece in instance.pieces]
    for _ in range(PLACEMENT_TRIALS):
        placements.append((rng.choice(instance.pieces), random_pose(rng, instance.span_mm * 0.6)))
    for piece, pose in placements:
        expected = piece.world_polygon(pose)
        placed = _native.transform(piece.polygon, as_tuple(pose))
        worst = max(shapely.Point(vertex).distance(target) for vertex in expected)
        assert _native.outside_depth(placed, instance.target) == pytest.approx(
            worst, abs=LENGTH_TOL
        )
        beyond = shapely.Polygon(expected).difference(target).area
        assert _native.outside_area(placed, instance.target) == pytest.approx(beyond, abs=AREA_TOL)
        for vertex in expected:
            here = shapely.Point(vertex)
            if here.distance(target.exterior) > LENGTH_TOL:
                assert _native.contains_point(instance.target, vertex) == target.covers(here)
        if worst <= LENGTH_TOL:
            inside += 1
        else:
            outside += 1
    assert inside >= len(instance.pieces) and outside >= 5, (inside, outside)


# --- whole assemblies ---------------------------------------------------------------------


def native_residuals(
    instance: PuzzleInstance, poses: dict[str, Pose], policy: TolerancePolicy
) -> dict[str, float | dict[str, float]]:
    """The validator's depth and area residuals, recomputed with the Rust kernel alone."""
    noise = policy.contact_noise_mm
    world = {p.id: _native.transform(p.polygon, as_tuple(poses[p.id])) for p in instance.pieces}
    worst_depth = overlap_area = 0.0
    for first, second in combinations(instance.pieces, 2):
        depth = _native.penetration_depth(world[first.id], world[second.id])
        if depth > noise:
            worst_depth = max(worst_depth, depth)
            overlap_area += _native.intersection_area(world[first.id], world[second.id])
    outside = {}
    for pid, polygon in world.items():
        depth = _native.outside_depth(polygon, instance.target)
        outside[pid] = depth if depth > noise else 0.0
    return {
        "overlap_depth_mm": worst_depth,
        "overlap_area_mm2": overlap_area,
        "outside_mm": outside,
        "outside_area_mm2": sum(_native.outside_area(p, instance.target) for p in world.values()),
    }


def assert_same_residuals(instance: PuzzleInstance, poses: dict[str, Pose]) -> tuple[bool, bool]:
    policy = TolerancePolicy.from_instance(instance)
    report = validate_solution(instance, poses, policy)
    ours = native_residuals(instance, poses, policy)
    assert ours["overlap_depth_mm"] == pytest.approx(report.worst_overlap_depth_mm, abs=LENGTH_TOL)
    assert ours["overlap_area_mm2"] == pytest.approx(report.overlap_area_mm2, abs=AREA_TOL)
    assert ours["outside_mm"] == pytest.approx(dict(report.outside_mm), abs=LENGTH_TOL)
    assert ours["outside_area_mm2"] == pytest.approx(report.outside_area_mm2, abs=AREA_TOL)
    return report.no_overlap, report.inside


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_keyed_assembly_has_no_residuals_by_either_implementation(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    assert assert_same_residuals(instance, poses) == (True, True)
    policy = TolerancePolicy.from_instance(instance)
    ours = native_residuals(instance, poses, policy)
    assert ours["overlap_depth_mm"] == 0.0
    assert ours["outside_area_mm2"] == pytest.approx(0.0, abs=AREA_TOL)
    # The pieces fill the target: no overlap, nothing outside, and the areas add up.
    total = sum(_native.signed_area(p.polygon) for p in instance.pieces)
    assert total == pytest.approx(_native.signed_area(instance.target), abs=AREA_TOL)


@pytest.mark.parametrize("fixture_id", ALL)
def test_disturbed_assemblies_have_the_same_residuals(fixture_id: str) -> None:
    """Every piece of the key nudged at random, from a hair to a few millimetres and degrees."""
    instance, poses = load(fixture_id)
    rng = rng_for(fixture_id, "assembly")
    verdicts = set()
    for trial in range(ASSEMBLY_TRIALS):
        # Scales from 0.01 mm to about 4 mm, so both sides of every tolerance are visited.
        scale = 0.01 * 2.0 ** (trial * 8.6 / (ASSEMBLY_TRIALS - 1))
        disturbed = {
            pid: Pose(
                pose.x + rng.gauss(0.0, scale),
                pose.y + rng.gauss(0.0, scale),
                pose.theta + rng.gauss(0.0, scale / 30.0),
            )
            for pid, pose in poses.items()
        }
        verdicts.add(assert_same_residuals(instance, disturbed))
    assert (True, True) in verdicts and (False, False) in verdicts, verdicts


# --- roofs --------------------------------------------------------------------------------


def shared_edges(
    instance: PuzzleInstance, poses: dict[str, Pose]
) -> list[tuple[str, str, tuple[float, float], tuple[float, float]]]:
    """Pairs of pieces with two world vertices in common, and the segment between those."""
    world = {p.id: p.world_polygon(poses[p.id]) for p in instance.pieces}
    found = []
    for first, second in combinations(instance.pieces, 2):
        common = [
            p for p in world[first.id] if any(math.dist(p, q) < 1e-6 for q in world[second.id])
        ]
        if len(common) == 2:
            found.append((first.id, second.id, common[0], common[1]))
    return found


def native_roof_mismatch(instance: PuzzleInstance, poses: dict[str, Pose]) -> float:
    worst = 0.0
    for first, second, p0, p1 in shared_edges(instance, poses):
        roof_a, roof_b = instance.piece(first).roof, instance.piece(second).roof
        assert roof_a is not None and roof_b is not None
        worst = max(
            worst,
            _native.seam_mismatch(
                (roof_a.z0, roof_a.gx, roof_a.gy),
                as_tuple(poses[first]),
                (roof_b.z0, roof_b.gx, roof_b.gy),
                as_tuple(poses[second]),
                p0,
                p1,
            ),
        )
    return worst


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_roof_heights_at_random_poses_agree_with_the_models(fixture_id: str) -> None:
    instance, _ = load(fixture_id)
    rng = rng_for(fixture_id, "roof")
    for _ in range(PLACEMENT_TRIALS):
        piece = rng.choice(instance.pieces)
        assert piece.roof is not None
        pose = random_pose(rng, instance.span_mm / 2.0)
        point = (rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0))
        roof = (piece.roof.z0, piece.roof.gx, piece.roof.gy)
        expected = piece.roof.height_at(pose.to_local(point))
        assert _native.roof_height(roof, as_tuple(pose), point) == pytest.approx(
            expected, abs=LENGTH_TOL
        )


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_the_keyed_roof_is_continuous_by_the_native_seam_test(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    edges = shared_edges(instance, poses)
    assert len(edges) >= len(instance.pieces) // 2, "too few shared edges to say anything"
    assert native_roof_mismatch(instance, poses) == pytest.approx(0.0, abs=1e-6)
    for first, second, p0, p1 in edges:
        roof_a, roof_b = instance.piece(first).roof, instance.piece(second).roof
        assert roof_a is not None and roof_b is not None
        drift = _native.tangential_gradient_mismatch(
            (roof_a.z0, roof_a.gx, roof_a.gy),
            as_tuple(poses[first]),
            (roof_b.z0, roof_b.gx, roof_b.gy),
            as_tuple(poses[second]),
            p0,
            p1,
        )
        # A slope difference along the edge, in mm per mm.
        assert drift == pytest.approx(0.0, abs=1e-8)


@pytest.mark.parametrize(
    ("turned", "step"),
    [(("narrow",), 12.0), (("wide",), 6.0), (("narrow", "wide"), 6.0)],
)
def test_the_half_turned_ridge_steps_by_the_same_amount_as_the_validator_finds(
    turned: tuple[str, ...], step: float
) -> None:
    """The steps are worked out in synthetic.py; validator and kernel must both find them."""
    instance, poses = load("syn-two-rectangles-ridge")
    source = corpus.key("syn-two-rectangles-ridge")["sourceIds"]
    spoiled = {
        pid: Pose(p.x, p.y, p.theta + math.pi) if source[pid] in turned else p
        for pid, p in poses.items()
    }
    report = validate_solution(instance, spoiled)
    assert report.worst_roof_mismatch_mm == pytest.approx(step, abs=LENGTH_TOL)
    assert native_roof_mismatch(instance, spoiled) == pytest.approx(step, abs=LENGTH_TOL)


@pytest.mark.parametrize("fixture_id", corpus.fixture_ids(kind="corpus", regime="relief"))
def test_a_half_turned_piece_never_shows_a_larger_step_than_the_validator_reports(
    fixture_id: str,
) -> None:
    """The edges two pieces share end to end are among the seams the validator examines."""
    instance, poses = load(fixture_id)
    for pid, pose in poses.items():
        spoiled = {**poses, pid: Pose(pose.x, pose.y, pose.theta + math.pi)}
        report = validate_solution(instance, spoiled)
        assert report.worst_roof_mismatch_mm is not None
        ours = native_roof_mismatch(instance, spoiled)
        assert ours <= report.worst_roof_mismatch_mm + 1e-6
