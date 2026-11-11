"""The conflicts of a placement model, against Shapely.

``_native.placement_model`` says which listed placements exclude one another,
mostly as cliques at probe points. Here every pair of placements is intersected
with Shapely and the two are compared:

* two placements the model lets stand together share no more area than a sliver
  one length tolerance deep;
* two it excludes overlap, or, under roofs, share a stretch of edge;
* the members of a clique have a region in common, as placements holding one
  point must.

Tolerances: the model is built with a length tolerance of ``1e-6`` mm. An
overlap is "none" below that depth along the shorter of the two perimeters,
plus ``1e-6`` mm² for the arithmetic, and "some" above ``1e-9`` mm². Shapely
rarely reports the common part of two nearly collinear edges, so a shared
stretch of edge is found by growing one placement by ``1e-3`` mm.

Agreement is numerical evidence that two implementations compute the same
thing. It is not a proof of either.
"""

from itertools import combinations

import pytest
import shapely

from maxplus_solvers import PuzzleInstance, Regime, _native
from support import corpus

PIECES = {entry["id"]: entry["pieceCount"] for entry in corpus.index()["fixtures"]}
# Lists short enough to intersect every pair: up to a few hundred placements.
FLAT = ["new5-flat", "rev2-flat", "new4-flat"]
RELIEF = corpus.fixture_ids(kind="corpus", regime="relief")
SYNTHETIC = corpus.fixture_ids(kind="synthetic")

LENGTH_TOL = 1e-6
AREA_TOL = 1e-6
SOME_AREA = 1e-9
# Two placements share a stretch of edge if one, grown by this much, takes this much
# area of the other: a stretch of more than a hundredth of a millimetre. Placements that
# only touch at a corner share about the square of the growth.
GROWTH_MM = 1e-3
SEAM_AREA = 1e-5


def model_of(fixture_id: str, targeted: bool) -> tuple[PuzzleInstance, _native.PlacementModel]:
    instance = PuzzleInstance.from_dict(corpus.fixture(fixture_id))
    roofs = None
    if instance.regime is Regime.RELIEF:
        roofs = []
        for piece in instance.pieces:
            assert piece.roof is not None
            roofs.append((piece.roof.z0, piece.roof.gx, piece.roof.gy))
    model = _native.placement_model(
        instance.target,
        [piece.polygon for piece in instance.pieces],
        roofs,
        length_tol=LENGTH_TOL,
        angle_tol=1e-6,
        slope_tol=1e-6,
        # Every orientation and no anchor: the longest list the search makes.
        all_tray_rotations=True,
        anchor=False,
        targeted_probes=targeted,
    )
    assert model.exhausted
    return instance, model


def polygons_of(instance: PuzzleInstance, model: _native.PlacementModel) -> list[shapely.Polygon]:
    placed = []
    for index, poses in zip(model.placement_class, model.placement_poses, strict=True):
        first = instance.pieces[model.classes[index][0]]
        x, y, theta = poses[0]
        placed.append(shapely.Polygon(_native.transform(first.polygon, (x, y, theta))))
    return placed


def excluded_pairs(model: _native.PlacementModel) -> set[tuple[int, int]]:
    pairs = {(min(a, b), max(a, b)) for a, b in model.pairs}
    for clique in model.cliques:
        pairs.update(combinations(sorted(clique), 2))
    return pairs


@pytest.mark.parametrize("targeted", [False, True], ids=["grid", "targeted"])
@pytest.mark.parametrize("fixture_id", FLAT + RELIEF + SYNTHETIC)
def test_the_model_excludes_the_pairs_shapely_finds_overlapping(
    fixture_id: str, targeted: bool
) -> None:
    instance, model = model_of(fixture_id, targeted)
    placed = polygons_of(instance, model)
    assert len(placed) >= PIECES[fixture_id] - sum(len(c) - 1 for c in model.classes)
    excluded = excluded_pairs(model)
    if fixture_id not in SYNTHETIC:
        # The smallest synthetic lists are a tiling and nothing else.
        assert excluded, "the model excludes nothing"

    overlapping = 0
    steps = 0
    for a, b in combinations(range(len(placed)), 2):
        shared = placed[a].intersection(placed[b]).area
        if (a, b) in excluded:
            if shared > SOME_AREA:
                overlapping += 1
            else:
                # Only a roof can keep apart two placements that do not overlap, and
                # only across an edge they share.
                assert instance.regime is Regime.RELIEF, (a, b)
                seam = placed[a].buffer(GROWTH_MM).intersection(placed[b]).area
                assert seam > SEAM_AREA, (a, b, seam)
                steps += 1
        else:
            sliver = LENGTH_TOL * min(placed[a].length, placed[b].length) + AREA_TOL
            assert shared <= sliver, (a, b, shared)
    # The model calls a pair an overlap first and looks at roofs only if it is not one.
    # An overlap thinner than SOME_AREA across a shared edge is counted here as a step,
    # so the two tallies may trade a pair and must agree in sum.
    assert overlapping + steps == model.overlapping_pairs + model.roof_step_pairs
    assert overlapping <= model.overlapping_pairs
    assert model.overlapping_pairs - overlapping <= max(1, len(excluded) // 1000)
    if instance.regime is Regime.FOOTPRINT:
        assert model.roof_step_pairs == 0

    # A pair is stated once: not listed if a clique already holds it.
    in_cliques = set()
    for clique in model.cliques:
        in_cliques.update(combinations(sorted(clique), 2))
    assert not in_cliques & {(min(a, b), max(a, b)) for a, b in model.pairs}


@pytest.mark.parametrize("fixture_id", FLAT + RELIEF[:3])
def test_the_members_of_a_clique_have_a_region_in_common(fixture_id: str) -> None:
    instance, model = model_of(fixture_id, True)
    placed = polygons_of(instance, model)
    assert model.cliques
    for clique in model.cliques:
        assert len(clique) >= 2 and sorted(set(clique)) == list(clique)
        common = placed[clique[0]]
        for member in clique[1:]:
            common = common.intersection(placed[member])
        assert common.area > SOME_AREA, clique


@pytest.mark.parametrize("fixture_id", FLAT + RELIEF[:3])
def test_targeted_probes_change_how_overlaps_are_stated_and_not_which(fixture_id: str) -> None:
    _, grid = model_of(fixture_id, False)
    _, targeted = model_of(fixture_id, True)
    assert grid.placement_poses == targeted.placement_poses
    assert excluded_pairs(grid) == excluded_pairs(targeted)
    assert len(targeted.pairs) <= len(grid.pairs)
    assert grid.covers == targeted.covers


@pytest.mark.parametrize("fixture_id", FLAT + RELIEF)
def test_every_cover_is_reached_by_a_placement_and_lies_in_the_target(fixture_id: str) -> None:
    """A cover is the placements reaching one point of the target.

    So its members have a point in common, boundaries counted, and no listed
    placement outside it contains all that its members share.
    """
    instance, model = model_of(fixture_id, False)
    placed = polygons_of(instance, model)
    target = shapely.Polygon(instance.target)
    assert model.covers
    for cover in model.covers:
        assert cover, "a point of the target that nothing listed reaches"
        # Reaching counts the boundary, and a point outside by no more than the tolerance.
        common = placed[cover[0]].buffer(2 * LENGTH_TOL)
        for member in cover[1:]:
            common = common.intersection(placed[member].buffer(2 * LENGTH_TOL))
        assert not common.is_empty, cover
        assert common.intersects(target)
        # A placement that held every point the members share would reach the probe too.
        if common.area > SOME_AREA:
            inside = common.buffer(-LENGTH_TOL)
            for other in set(range(len(placed))) - set(cover):
                assert not placed[other].contains(inside) or inside.is_empty, (cover, other)
