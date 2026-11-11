"""The geometry phase 5 added to the search, against Shapely, the validator and the test oracle.

Three things the Rust search relies on are computed a second way here, on
partial and whole assemblies taken from the answer keys:

* the cavities of a partial assembly, against a Shapely difference;
* the roof step a placement would make, against the validator's seam check;
* canonical forms and the "same assembly" test, against ``support.assemblies``.

Tolerances: lengths ``1e-9`` mm; areas ``1e-6`` mm², except where a cavity is
compared with a Shapely polygon that was first shrunk by ``1e-7`` mm to pull
apart cavities that touch at a point, which changes its area by its perimeter
times that and is compared to ``1e-3`` mm².

Agreement is numerical evidence that two implementations compute the same
thing. It is not a proof of either.
"""

import dataclasses
import math
import random
from typing import Any

import pytest
import shapely

from maxplus_solvers import Pose, PuzzleInstance, Regime, Roof, SolverConfig, _native, solve
from maxplus_solvers.validation import validate_solution
from support import assemblies, corpus, geometry

FLAT = corpus.fixture_ids(kind="corpus", regime="footprint")
RELIEF = corpus.fixture_ids(kind="corpus", regime="relief")
ALL = corpus.fixture_ids()

LENGTH_TOL = 1e-9
AREA_TOL = 1e-6
# For a cavity against a Shapely polygon shrunk by SHRINK_MM (see the module docstring).
SHRINK_MM = 1e-7
SHRUNK_AREA_TOL = 1e-3

# The search's own tolerances are of this order: far above rounding, far below a feature.
TOL = {"length_tol": 1e-6, "angle_tol": 1e-6, "slope_tol": 1e-6}

CAVITY_TRIALS = 30


def load(fixture_id: str) -> tuple[PuzzleInstance, dict[str, Pose]]:
    instance = PuzzleInstance.from_dict(corpus.fixture(fixture_id))
    poses = {pid: Pose(**pose) for pid, pose in corpus.key(fixture_id)["poses"].items()}
    return instance, poses


def rng_for(fixture_id: str, purpose: str) -> random.Random:
    """Seeded by name, so every run and every platform sees the same choices."""
    return random.Random(f"phase-5:{purpose}:{fixture_id}")


def as_tuple(pose: Pose) -> tuple[float, float, float]:
    return (pose.x, pose.y, pose.theta)


def roofs_of(instance: PuzzleInstance) -> list[tuple[float, float, float]] | None:
    if instance.regime is not Regime.RELIEF:
        return None
    roofs = []
    for piece in instance.pieces:
        assert piece.roof is not None
        roofs.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
    return roofs


def assembly(instance: PuzzleInstance) -> Any:
    return _native.Assembly(
        instance.target, [piece.polygon for piece in instance.pieces], roofs_of(instance), **TOL
    )


# --- cavities -----------------------------------------------------------------------------


def least_width(ring: list[tuple[float, float]]) -> float:
    """The least distance between two parallel lines that hold a convex polygon.

    One of the lines lies along an edge, so: for each edge, the farthest vertex
    from its line; the least of those.
    """
    best = math.inf
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            continue
        reach = max(abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / length for px, py in ring)
        best = min(best, reach)
    return best


@pytest.mark.parametrize("fixture_id", FLAT)
def test_cavities_of_partial_assemblies(fixture_id: str) -> None:
    """Some of the keyed pieces are placed; what is left uncovered is found both ways."""
    instance, poses = load(fixture_id)
    tray = shapely.Polygon(instance.target)
    rng = rng_for(fixture_id, "cavities")
    traced = holed = convex_seen = 0
    for _ in range(CAVITY_TRIALS):
        order = list(range(len(instance.pieces)))
        rng.shuffle(order)
        chosen = order[: rng.randrange(1, len(order))]
        state = assembly(instance)
        placed = []
        for index in chosen:
            piece = instance.pieces[index]
            state.place(index, as_tuple(poses[piece.id]))
            placed.append(shapely.Polygon(piece.world_polygon(poses[piece.id])))
        covered = shapely.union_all(placed)
        # Shrunk a little, so that cavities meeting at a point come apart as they do in a trace.
        left = tray.difference(covered.buffer(SHRINK_MM)).buffer(-SHRINK_MM)
        parts = [g for g in getattr(left, "geoms", [left]) if g.area > SHRUNK_AREA_TOL]
        has_hole = any(len(part.interiors) > 0 for part in parts)

        cavities = state.cavities()
        if cavities is None:
            # A placed piece that touches nothing leaves a region with a hole: not traced.
            assert has_hole
            holed += 1
            continue
        assert not has_hole
        traced += 1
        assert len(cavities) == len(parts)
        # Exactly: what is uncovered is the tray less the pieces placed.
        uncovered = tray.area - sum(shape.area for shape in placed)
        assert sum(area for area, _, _ in cavities) == pytest.approx(uncovered, abs=AREA_TOL)

        frontier = state.frontier()
        unmatched = list(parts)
        for area, width, corners in cavities:
            part = min(unmatched, key=lambda g, area=area: abs(g.area - area))
            unmatched.remove(part)
            assert area == pytest.approx(part.area, abs=SHRUNK_AREA_TOL)
            # Its corners are on that part's boundary.
            for index in corners:
                corner = frontier[index]
                point = shapely.Point(corner.x, corner.y)
                assert part.exterior.distance(point) <= 10 * SHRINK_MM
            # A width is given exactly when the cavity is convex.
            hull = part.convex_hull
            is_convex = hull.area - part.area <= SHRUNK_AREA_TOL
            assert (width is not None) == is_convex
            if width is not None:
                convex_seen += 1
                ring = [(x, y) for x, y in hull.exterior.coords[:-1]]
                assert width == pytest.approx(least_width(ring), abs=10 * SHRINK_MM)
    # Each case was seen, or the comparisons above checked only some of them.
    assert traced >= 10 and convex_seen >= 3, (traced, holed, convex_seen)


def test_a_cavity_with_a_hole_is_reported_as_unknown_on_some_fixture() -> None:
    """The ``None`` branch above is reached: some trial places a piece touching nothing."""
    seen = 0
    for fixture_id in FLAT:
        instance, poses = load(fixture_id)
        # The piece whose keyed centre is nearest the middle of the tray, alone.
        centre = geometry.centroid(instance.target)
        index = min(
            range(len(instance.pieces)),
            key=lambda i: math.dist(
                centre, (poses[instance.pieces[i].id].x, poses[instance.pieces[i].id].y)
            ),
        )
        piece = instance.pieces[index]
        world = shapely.Polygon(piece.world_polygon(poses[piece.id]))
        state = assembly(instance)
        state.place(index, as_tuple(poses[piece.id]))
        touches_the_wall = world.distance(shapely.Polygon(instance.target).exterior) <= 1e-6
        assert (state.cavities() is None) == (not touches_the_wall)
        seen += not touches_the_wall
    assert seen >= 3


def test_the_least_width_helper_on_shapes_measured_by_hand() -> None:
    """Guard the oracle: a 3 x 5 rectangle is 3 wide; a 3-4-5 triangle is 12/5, its least height."""
    assert least_width([(0, 0), (5, 0), (5, 3), (0, 3)]) == pytest.approx(3.0, abs=1e-12)
    assert least_width([(0, 0), (4, 0), (0, 3)]) == pytest.approx(2.4, abs=1e-12)


# --- roof steps ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_the_roof_step_of_a_placement_is_the_validators_seam_mismatch(fixture_id: str) -> None:
    """One piece's roof is raised, or tilted; the step it then makes is measured twice.

    Every other seam of the keyed assembly is continuous, so the validator's
    worst mismatch is the step along the changed piece's seams.
    """
    instance, poses = load(fixture_id)
    rng = rng_for(fixture_id, "roofs")
    indices = rng.sample(range(len(instance.pieces)), min(5, len(instance.pieces)))
    for index in indices:
        target = instance.pieces[index]
        assert target.roof is not None
        lifted = Roof(target.roof.z0 + rng.uniform(0.5, 3.0), target.roof.gx, target.roof.gy)
        tilted = Roof(
            target.roof.z0,
            target.roof.gx + rng.uniform(-0.05, 0.05),
            target.roof.gy + rng.uniform(-0.05, 0.05),
        )
        for roof in (target.roof, lifted, tilted):
            pieces = tuple(
                dataclasses.replace(piece, roof=roof) if piece.id == target.id else piece
                for piece in instance.pieces
            )
            changed = dataclasses.replace(instance, pieces=pieces)
            report = validate_solution(changed, poses)
            assert report.worst_roof_mismatch_mm is not None
            state = assembly(changed)
            for other, piece in enumerate(changed.pieces):
                if other != index:
                    state.place(other, as_tuple(poses[piece.id]))
            step = state.roof_step(index, as_tuple(poses[target.id]))
            assert step == pytest.approx(report.worst_roof_mismatch_mm, abs=LENGTH_TOL)
            if roof is target.roof:
                assert step == pytest.approx(0.0, abs=LENGTH_TOL)
            else:
                assert step > 1e-3


# --- canonical forms ----------------------------------------------------------------------


def turned_poses(
    instance: PuzzleInstance, poses: dict[str, Pose], turn: float
) -> list[tuple[float, float, float]]:
    """The poses of the assembly turned about the tray's centroid, worked out here.

    A pose turns its piece about the local origin and then moves it, so turning
    the placed piece about the centre turns the pose's offset about the centre
    and adds to its angle.
    """
    cx, cy = geometry.centroid(instance.target)
    c, s = math.cos(turn), math.sin(turn)
    out = []
    for piece in instance.pieces:
        pose = poses[piece.id]
        dx, dy = pose.x - cx, pose.y - cy
        out.append((cx + c * dx - s * dy, cy + s * dx + c * dy, pose.theta + turn))
    return out


def world(instance: PuzzleInstance, poses: list[tuple[float, float, float]]) -> list[Any]:
    return [
        piece.world_polygon(Pose(*pose)) for piece, pose in zip(instance.pieces, poses, strict=True)
    ]


@pytest.mark.parametrize("fixture_id", ALL)
def test_every_turn_of_the_key_has_the_same_canonical_form(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    polygons = [piece.polygon for piece in instance.pieces]
    roofs = roofs_of(instance)
    turns = assemblies.tray_turns(instance.target)
    assert len(turns) >= 3, "every tray in the corpus has a rotation"
    plain = turned_poses(instance, poses, 0.0)
    form = _native.canonical_poses(instance.target, polygons, roofs, plain, **TOL)
    centre = geometry.centroid(instance.target)
    expected = [assemblies.turned(world(instance, plain), turn, centre) for turn in turns]
    # The form is the keyed assembly in one of the tray's orientations.
    assert sum(assemblies.same(world(instance, form), turn) for turn in expected) >= 1
    for turn in turns:
        other = turned_poses(instance, poses, turn)
        assert _native.same_assembly(instance.target, polygons, roofs, plain, other, **TOL)
        again = _native.canonical_poses(instance.target, polygons, roofs, other, **TOL)
        for (x, y, theta), (u, v, phi) in zip(form, again, strict=True):
            assert math.hypot(x - u, y - v) <= 1e-6
            # Angles compared as turns: -pi and pi are one.
            assert abs(math.remainder(theta - phi, 2 * math.pi)) <= 1e-9


@pytest.mark.parametrize("fixture_id", ALL)
def test_a_moved_piece_makes_another_assembly(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    polygons = [piece.polygon for piece in instance.pieces]
    roofs = roofs_of(instance)
    plain = turned_poses(instance, poses, 0.0)
    rng = rng_for(fixture_id, "moved")
    for _ in range(5):
        moved = list(plain)
        index = rng.randrange(len(moved))
        x, y, theta = moved[index]
        moved[index] = (x + rng.choice([-1.0, 1.0]), y, theta)
        assert not _native.same_assembly(instance.target, polygons, roofs, plain, moved, **TOL)
        assert not assemblies.same(world(instance, plain), world(instance, moved))


def test_same_assembly_agrees_with_the_oracle_on_the_assemblies_of_rat1() -> None:
    """Pairs out of 404 footprint assemblies: the same up to the tray's turns, or not.

    The oracle compares placed polygons; the Rust form compares seats. Pieces
    here are their own half turns and the tray has four orientations, so both
    notions of "same" are exercised.
    """
    instance, _ = load("rat1-flat")
    polygons = [piece.polygon for piece in instance.pieces]
    result = solve(
        instance,
        SolverConfig("rust.contact_dfs", max_solutions=None, options={"tray_rotations": "all"}),
    )
    found = [
        [as_tuple(solution.poses[piece.id]) for piece in instance.pieces]
        for solution in result.solutions
    ]
    assert len(found) == 404
    rng = rng_for("rat1-flat", "pairs")
    sample = rng.sample(found, 40)
    placed = [world(instance, poses) for poses in sample]
    groups = assemblies.orbits(instance.target, placed)
    group_of = {member: g for g, group in enumerate(groups) for member in group}
    together = 0
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            expected = group_of[i] == group_of[j]
            together += expected
            assert (
                _native.same_assembly(instance.target, polygons, None, sample[i], sample[j], **TOL)
                == expected
            )
    # 40 out of 404 in orbits of four: some pairs share an orbit, most do not.
    assert together >= 1
