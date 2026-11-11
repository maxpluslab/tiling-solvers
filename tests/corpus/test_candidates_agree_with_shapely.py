"""The candidate interface against Shapely and the test oracle, on partly assembled fixtures.

Some of the keyed pieces of a fixture are put down, chosen by a seeded draw, and
then everything the search would ask of the state is computed twice:

* the frontier, against the corners of ``target - union(placed)`` as GEOS builds it;
* ``check_placement``, against Shapely distances and the validator's penetration depth;
* ``propose``, against every piece tried at every vertex with the oracle's own arithmetic;
* the compatibility graph of the relief fixtures, against the contacts in the answer keys.

Lengths are compared to 1e-9 mm where both sides compute the same quantity. The
frontier is compared to 1e-4 mm and 1e-4 rad, because the Shapely side has to
grow the pieces by 1e-7 mm before uniting them: pieces that touch exactly would
otherwise leave slivers that are artefacts of the overlay, not corners.
"""

import math
import random
from typing import Any

import pytest
import shapely
from shapely.geometry.polygon import orient

from maxplus_solvers import Pose, PuzzleInstance, TolerancePolicy, _native
from maxplus_solvers.validation import penetration_depth
from support import assemblies, corpus, geometry

ALL = corpus.fixture_ids()
RELIEF = corpus.fixture_ids(regime="relief")
CORPUS = corpus.fixture_ids(kind="corpus")

STATES = 10
GROW_MM = 1e-7
CORNER_MM = 1e-4
CORNER_RAD = 1e-4
LENGTH_TOL = 1e-9

Corner = tuple[float, float, float, float]


def load(fixture_id: str) -> tuple[PuzzleInstance, list[Pose]]:
    instance = PuzzleInstance.from_dict(corpus.fixture(fixture_id))
    poses = corpus.key(fixture_id)["poses"]
    return instance, [Pose(**poses[piece.id]) for piece in instance.pieces]


def tolerances(instance: PuzzleInstance) -> tuple[float, float]:
    """The solver's own: the contact noise, and the turn that moves a span's end by it."""
    fit = TolerancePolicy.from_instance(instance).contact_noise_mm
    return fit, fit / instance.span_mm


def new_state(instance: PuzzleInstance, roofs: bool = False) -> _native.Assembly:
    fit, turn = tolerances(instance)
    planes = None
    if roofs:
        planes = []
        for piece in instance.pieces:
            assert piece.roof is not None
            planes.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
    return _native.Assembly(
        instance.target,
        [piece.polygon for piece in instance.pieces],
        planes,
        length_tol=fit,
        angle_tol=turn,
        slope_tol=turn,
    )


def partial_states(
    fixture_id: str, purpose: str
) -> list[tuple[PuzzleInstance, list[Pose], list[int]]]:
    """Seeded subsets of the keyed assembly, from one piece down to all but one."""
    instance, poses = load(fixture_id)
    rng = random.Random(f"phase-4:{purpose}:{fixture_id}")
    count = len(instance.pieces)
    states = []
    for _ in range(STATES):
        down = sorted(rng.sample(range(count), rng.randint(1, count - 1)))
        states.append((instance, poses, down))
    return states


def as_tuple(pose: Pose) -> tuple[float, float, float]:
    return (pose.x, pose.y, pose.theta)


# --- the frontier -------------------------------------------------------------------------


def shapely_corners(instance: PuzzleInstance, placed: list[Any]) -> list[Corner]:
    """Corners of the uncovered region as ``(x, y, direction, angle)``, from GEOS."""
    grown = [
        shapely.Polygon(p).buffer(GROW_MM, join_style="mitre", mitre_limit=100.0) for p in placed
    ]
    free: Any = shapely.Polygon(instance.target).difference(shapely.union_all(grown))
    parts = [free] if free.geom_type == "Polygon" else list(free.geoms)
    corners: list[Corner] = []
    for part in parts:
        if part.area < 1e-3:
            continue
        # Exterior counter-clockwise, holes clockwise: the region is always on the left.
        part = orient(part, 1.0)
        for ring in [part.exterior, *part.interiors]:
            points: list[tuple[float, float]] = []
            for point in list(ring.coords)[:-1]:
                if not points or math.dist(point, points[-1]) > 10 * CORNER_MM:
                    points.append((point[0], point[1]))
            if len(points) > 1 and math.dist(points[0], points[-1]) <= 10 * CORNER_MM:
                points.pop()
            n = len(points)
            for i, (x, y) in enumerate(points):
                before, after = points[i - 1], points[(i + 1) % n]
                leaving = math.atan2(after[1] - y, after[0] - x)
                arriving = math.atan2(before[1] - y, before[0] - x)
                angle = (arriving - leaving) % (2 * math.pi)
                if abs(angle - math.pi) > CORNER_RAD:
                    corners.append((x, y, leaving % (2 * math.pi), angle))
    return corners


def same_corner(a: Corner, b: Corner) -> bool:
    turn = abs(a[2] - b[2]) % (2 * math.pi)
    return (
        math.dist(a[:2], b[:2]) <= CORNER_MM
        and min(turn, 2 * math.pi - turn) <= CORNER_RAD
        and abs(a[3] - b[3]) <= CORNER_RAD
    )


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_frontier_is_the_corners_of_the_uncovered_region(fixture_id: str) -> None:
    convex = reflex = 0
    for instance, poses, down in partial_states(fixture_id, "frontier"):
        state = new_state(instance)
        for piece in down:
            state.place(piece, as_tuple(poses[piece]))
        ours = [(c.x, c.y, c.direction, c.angle) for c in state.frontier()]
        theirs = shapely_corners(
            instance, [instance.pieces[piece].world_polygon(poses[piece]) for piece in down]
        )
        unmatched = list(theirs)
        for corner in ours:
            match = next((other for other in unmatched if same_corner(corner, other)), None)
            assert match is not None, (down, corner)
            unmatched.remove(match)
        assert not unmatched, (down, unmatched)
        for corner in state.frontier():
            assert corner.convex == (corner.angle < math.pi)
            convex += corner.convex
            reflex += not corner.convex
        assert any(c.convex for c in state.frontier()), "an uncovered region has a convex corner"
    assert convex >= 3 * STATES
    if fixture_id in CORPUS:
        assert reflex >= 1, "no state had a reflex corner: the comparison saw only easy cases"


@pytest.mark.parametrize("fixture_id", ALL)
def test_the_whole_keyed_assembly_leaves_no_frontier(fixture_id: str) -> None:
    instance, poses = load(fixture_id)
    state = new_state(instance)
    for piece, pose in enumerate(poses):
        assert state.check_placement(piece, as_tuple(pose)).fits
        state.place(piece, as_tuple(pose))
        assert (state.frontier() == []) == (piece == len(poses) - 1)
    assert state.all_placed


# --- check_placement ----------------------------------------------------------------------


@pytest.mark.parametrize("fixture_id", ALL)
def test_check_placement_agrees_with_shapely_and_the_validator(fixture_id: str) -> None:
    rng = random.Random(f"phase-4:check:{fixture_id}")
    fit, _ = tolerances(load(fixture_id)[0])
    fitting = entering = leaving = 0
    for instance, poses, down in partial_states(fixture_id, "check"):
        state = new_state(instance)
        for piece in down:
            state.place(piece, as_tuple(poses[piece]))
        target = shapely.Polygon(instance.target)
        free = [p for p in range(len(poses)) if p not in down]
        for trial in range(8):
            piece = rng.choice(free)
            home = poses[piece]
            # Where it belongs, then nudged, then thrown anywhere.
            reach = (0.0, 2.0, 2.0, 2.0, 30.0, 30.0, 30.0, 30.0)[trial]
            pose = Pose(
                home.x + rng.uniform(-reach, reach),
                home.y + rng.uniform(-reach, reach),
                home.theta + rng.uniform(-reach, reach) / 30.0,
            )
            polygon = instance.pieces[piece].world_polygon(pose)
            check = state.check_placement(piece, as_tuple(pose))

            outside = max(shapely.Point(v).distance(target) for v in polygon)
            assert check.outside_mm == pytest.approx(outside, abs=LENGTH_TOL)
            depths = {
                other: penetration_depth(
                    polygon, instance.pieces[other].world_polygon(poses[other])
                )
                for other in down
            }
            deepest = max(depths, key=lambda other: depths[other])
            assert check.overlap_mm == pytest.approx(max(0.0, depths[deepest]), abs=LENGTH_TOL)
            if depths[deepest] > 1e-6:
                assert check.blocker == deepest
            elif depths[deepest] < -1e-6:
                assert check.blocker is None
            assert check.fits == (check.outside_mm <= fit and check.overlap_mm <= fit)
            fitting += check.fits
            entering += check.overlap_mm > fit
            leaving += check.outside_mm > fit
    assert fitting >= STATES, "the keyed pose of every state fits"
    assert entering >= 5 and leaving >= 5, (entering, leaving)


# --- propose ------------------------------------------------------------------------------


def brute_force_fillers(
    instance: PuzzleInstance, poses: list[Pose], down: list[int], corner: _native.Corner
) -> list[Any]:
    """Every distinct way to fill a corner, tried one piece vertex at a time with the oracle."""
    fit, turn = tolerances(instance)
    target = shapely.Polygon(instance.target)
    fixed = [instance.pieces[p].world_polygon(poses[p]) for p in down]
    found: list[Any] = []
    for index, piece in enumerate(instance.pieces):
        if index in down:
            continue
        n = len(piece.polygon)
        for i in range(n):
            before, here, after = piece.polygon[i - 1], piece.polygon[i], piece.polygon[(i + 1) % n]
            leaving = math.atan2(after[1] - here[1], after[0] - here[0])
            arriving = math.atan2(before[1] - here[1], before[0] - here[0])
            if (arriving - leaving) % (2 * math.pi) > corner.angle + turn:
                continue
            # Turn the edge that leaves this vertex onto the corner's first side, then move
            # the vertex to the corner.
            theta = corner.direction - leaving
            moved = geometry.place(here, {"x": 0.0, "y": 0.0, "theta": theta})
            pose = {"x": corner.x - moved[0], "y": corner.y - moved[1], "theta": theta}
            polygon = geometry.place_polygon(piece.polygon, pose)
            if max(shapely.Point(v).distance(target) for v in polygon) > fit:
                continue
            if any(penetration_depth(polygon, other) > fit for other in fixed):
                continue
            if not any(geometry.same_polygon(polygon, q, assemblies.SAME_MM) for q in found):
                found.append(polygon)
    return found


@pytest.mark.parametrize("fixture_id", ALL)
def test_proposals_are_exactly_the_placements_that_fill_the_corner(fixture_id: str) -> None:
    corners = offered = 0
    for instance, poses, down in partial_states(fixture_id, "propose")[:5]:
        state = new_state(instance)
        for piece in down:
            state.place(piece, as_tuple(poses[piece]))
        truth = [
            instance.pieces[p].world_polygon(poses[p]) for p in range(len(poses)) if p not in down
        ]
        for corner in state.frontier():
            candidates = state.propose(corner)
            ours = [instance.pieces[c.piece].world_polygon(Pose(*c.pose)) for c in candidates]
            theirs = brute_force_fillers(instance, poses, down, corner)
            assert assemblies.same(ours, theirs), (down, corner)
            assert all(c.piece not in down for c in candidates)
            if corner.convex:
                corners += 1
                # The search's guarantee: the piece that belongs in this corner is on offer.
                assert any(
                    geometry.same_polygon(polygon, real, assemblies.SAME_MM)
                    for polygon in ours
                    for real in truth
                ), (down, corner)
            offered += len(candidates)
    assert corners >= 15 and offered >= corners


# --- the compatibility graph --------------------------------------------------------------


def keyed_contacts(instance: PuzzleInstance, poses: list[Pose]) -> list[tuple[int, int, int, int]]:
    """Pairs of edges of different pieces that lie flush in the answer key: (piece, edge) twice."""
    world = [piece.world_polygon(pose) for piece, pose in zip(instance.pieces, poses, strict=True)]
    found = []
    for a, first in enumerate(world):
        for b, second in enumerate(world):
            if a == b:
                continue
            for i, p0 in enumerate(first):
                p1 = first[(i + 1) % len(first)]
                length = math.dist(p0, p1)
                dx, dy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
                for j, q0 in enumerate(second):
                    q1 = second[(j + 1) % len(second)]
                    other = math.dist(q0, q1)
                    if dx * (q1[0] - q0[0]) + dy * (q1[1] - q0[1]) > -other * (1 - 1e-9):
                        continue
                    offsets = [dx * (q[1] - p0[1]) - dy * (q[0] - p0[0]) for q in (q0, q1)]
                    if max(abs(offset) for offset in offsets) > 1e-6:
                        continue
                    along = sorted(dx * (q[0] - p0[0]) + dy * (q[1] - p0[1]) for q in (q0, q1))
                    if min(length, along[1]) - max(0.0, along[0]) > 1.0:
                        found.append((a, i, b, j))
    return found


@pytest.mark.parametrize("fixture_id", RELIEF)
def test_the_graph_keeps_every_contact_of_the_answer_key(fixture_id: str) -> None:
    """A real contact has roofs that agree along it, so their slopes along the edges cancel."""
    instance, poses = load(fixture_id)
    state = new_state(instance, roofs=True)
    contacts = keyed_contacts(instance, poses)
    assert len(contacts) >= 2 * (len(instance.pieces) - 1), "a connected assembly"
    for a, i, b, j in contacts:
        assert state.compatible(a, i, b, j), (a, i, b, j)


@pytest.mark.parametrize("fixture_id", corpus.fixture_ids(kind="corpus", regime="relief"))
def test_roofs_rule_out_most_pairs_of_edges(fixture_id: str) -> None:
    instance, _ = load(fixture_id)
    bare, roofed = new_state(instance.as_regime("footprint")), new_state(instance, roofs=True)
    counts = [len(piece.polygon) for piece in instance.pieces]
    # Without roofs every edge may meet every edge of another piece.
    assert bare.arc_count == sum(counts) ** 2 - sum(n * n for n in counts)
    assert bare.edge_count == roofed.edge_count == sum(counts)
    assert roofed.arc_count < bare.arc_count / 2


@pytest.mark.parametrize("fixture_id", ALL)
def test_classes_and_symmetry_agree_with_the_oracle(fixture_id: str) -> None:
    """Congruence by trying every turn about the centroid, which is the local origin."""
    instance, _ = load(fixture_id)
    state = new_state(instance.as_regime("footprint"))

    def turns_onto(a: Any, b: Any) -> int:
        """How many of the turns that could map polygon ``a`` onto ``b`` do."""
        hits = 0
        for vertex in b:
            theta = math.atan2(vertex[1], vertex[0]) - math.atan2(a[0][1], a[0][0])
            moved = geometry.place_polygon(a, {"x": 0.0, "y": 0.0, "theta": theta})
            hits += geometry.same_polygon(moved, b, assemblies.SAME_MM)
        return hits

    polygons = [piece.polygon for piece in instance.pieces]
    expected_classes = [
        next(q for q in range(p + 1) if turns_onto(polygons[q], polygons[p]))
        for p in range(len(polygons))
    ]
    assert state.classes() == expected_classes
    assert state.symmetry() == [turns_onto(polygon, polygon) for polygon in polygons]
