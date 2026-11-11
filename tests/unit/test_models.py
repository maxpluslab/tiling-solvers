"""The contract types: what they accept, what they refuse, and that they round-trip."""

import dataclasses
import json
import math

import pytest

from maxplus_solvers import (
    InstanceError,
    Piece,
    Pose,
    PuzzleInstance,
    Regime,
    Roof,
    Solution,
    SolverConfig,
    SolveResult,
    SolveStatus,
    TolerancePolicy,
)
from support import documents

SQUARE = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


# --- Pose and Roof ------------------------------------------------------------


def test_pose_rotates_then_translates() -> None:
    x, y = Pose(10.0, 20.0, math.pi / 2).apply((1.0, 0.0))
    assert x == pytest.approx(10.0, abs=1e-12)
    assert y == pytest.approx(21.0, abs=1e-12)


def test_pose_to_local_undoes_apply() -> None:
    pose = Pose(-31.0, 7.5, 1.234)
    u, v = pose.to_local(pose.apply((3.0, -4.0)))
    assert u == pytest.approx(3.0, abs=1e-12)
    assert v == pytest.approx(-4.0, abs=1e-12)


def test_roof_is_a_plane_in_local_coordinates() -> None:
    # 5 + 0.5*2 - 0.25*4
    assert Roof(5.0, 0.5, -0.25).height_at((2.0, 4.0)) == pytest.approx(5.0, abs=1e-12)


# --- Piece --------------------------------------------------------------------


def test_a_piece_keeps_its_polygon_as_given() -> None:
    piece = Piece("p00", SQUARE)
    assert piece.polygon == SQUARE
    assert piece.area == pytest.approx(4.0, abs=1e-12)


@pytest.mark.parametrize(
    ("name", "polygon"),
    [
        ("clockwise", list(SQUARE[::-1])),
        ("two vertices", list(SQUARE[:2])),
        ("reflex vertex", [(-3.0, -3.0), (3.0, -3.0), (0.0, -1.0), (3.0, 3.0), (-3.0, 3.0)]),
        ("collinear vertex", [(-1.0, -1.0), (0.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]),
        ("repeated vertex", [(-1.0, -1.0), (1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]),
        ("off-centre", [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
        ("not finite", [(-1.0, -1.0), (1.0, -1.0), (1.0, math.nan), (-1.0, 1.0)]),
        # A pentagram turns left at every vertex but goes round twice.
        (
            "pentagram",
            [
                (math.cos(2 * math.pi * k * 2 / 5), math.sin(2 * math.pi * k * 2 / 5))
                for k in range(5)
            ],
        ),
    ],
)
def test_a_piece_refuses_a_bad_polygon(name: str, polygon: list[tuple[float, float]]) -> None:
    with pytest.raises(InstanceError):
        Piece("p00", tuple(polygon))


def test_models_are_immutable() -> None:
    piece = Piece("p00", SQUARE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        piece.id = "other"  # type: ignore[misc]


# --- PuzzleInstance -----------------------------------------------------------


@pytest.mark.parametrize(
    "document", [documents.footprint, documents.relief, documents.tropical_aware]
)
def test_an_instance_round_trips_through_json(document) -> None:  # type: ignore[no-untyped-def]
    doc = documents.with_source(document())
    instance = PuzzleInstance.from_dict(doc)
    assert instance.to_dict() == doc
    assert PuzzleInstance.from_dict(json.loads(json.dumps(instance.to_dict()))) == instance


def test_target_area_is_the_area_of_the_target() -> None:
    assert PuzzleInstance.from_dict(documents.footprint()).target_area == pytest.approx(
        144.0 * 144.0, abs=1e-9
    )


def test_piece_lookup_by_id() -> None:
    instance = PuzzleInstance.from_dict(documents.footprint())
    assert instance.piece("p01") is instance.pieces[1]
    with pytest.raises(KeyError):
        instance.piece("p99")


def test_relief_reduces_to_footprint_and_loses_every_relief_field() -> None:
    relief = PuzzleInstance.from_dict(documents.relief())
    flat = relief.as_regime("footprint")
    assert flat.regime is Regime.FOOTPRINT
    assert flat.to_dict() == documents.footprint()


def test_tropical_aware_reduces_to_relief_and_loses_the_construction() -> None:
    aware = PuzzleInstance.from_dict(documents.tropical_aware())
    assert aware.as_regime(Regime.RELIEF).to_dict() == documents.relief()
    assert aware.as_regime(Regime.FOOTPRINT).to_dict() == documents.footprint()


def test_reducing_to_the_same_regime_is_the_identity() -> None:
    relief = PuzzleInstance.from_dict(documents.relief())
    assert relief.as_regime("relief") is relief


@pytest.mark.parametrize(
    ("start", "wanted"),
    [
        (documents.footprint, "relief"),
        (documents.footprint, "tropical-aware"),
        (documents.relief, "tropical-aware"),
    ],
)
def test_a_regime_never_gains_information(start, wanted: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InstanceError):
        PuzzleInstance.from_dict(start()).as_regime(wanted)


def test_the_hash_ignores_key_order_and_sees_every_coordinate() -> None:
    doc = documents.relief()
    reference = PuzzleInstance.from_dict(doc).instance_hash()
    assert len(reference) == 64

    reordered = dict(reversed(list(doc.items())))
    assert PuzzleInstance.from_dict(reordered).instance_hash() == reference

    doc["pieces"][0]["roof"]["gx"] += 1e-9
    assert PuzzleInstance.from_dict(doc).instance_hash() != reference


def test_the_hash_separates_regimes() -> None:
    relief = PuzzleInstance.from_dict(documents.relief())
    assert relief.instance_hash() != relief.as_regime("footprint").instance_hash()


# --- TolerancePolicy ----------------------------------------------------------


def test_tolerances_match_the_published_rev2_values() -> None:
    """docs/puzzle-rules.md of the source: 0.86 mm, 0.86 mm, 249 mm², 1.75 mm for rev2."""
    policy = TolerancePolicy.from_instance(PuzzleInstance.from_dict(documents.relief()))
    assert policy.overlap_depth_mm == pytest.approx(0.864, abs=1e-12)  # 0.006 * 144
    assert policy.outside_depth_mm == pytest.approx(0.864, abs=1e-12)
    assert policy.area_error_mm2 == pytest.approx(248.832, abs=1e-9)  # 0.012 * 144**2
    assert policy.roof_mismatch_mm == pytest.approx(1.75, abs=1e-12)  # 0.05 * 35
    assert policy.contact_noise_mm == pytest.approx(1.44e-4, abs=1e-15)  # 1e-6 * 144
    assert policy.edge_min_overlap_mm == pytest.approx(2.88, abs=1e-12)  # 0.02 * 144
    assert policy.edge_angle_rad == pytest.approx(math.pi / 60, abs=1e-15)  # 3 degrees


def test_a_footprint_puzzle_has_no_roof_tolerance() -> None:
    policy = TolerancePolicy.from_instance(PuzzleInstance.from_dict(documents.footprint()))
    assert policy.roof_mismatch_mm is None


def test_tolerances_round_trip() -> None:
    for document in (documents.footprint, documents.relief):
        policy = TolerancePolicy.from_instance(PuzzleInstance.from_dict(document()))
        assert TolerancePolicy.from_dict(json.loads(json.dumps(policy.to_dict()))) == policy


# --- solving ------------------------------------------------------------------


def test_solver_config_round_trips_and_normalizes_the_mode() -> None:
    config = SolverConfig(
        solver="rust.contact_dfs",
        mode="relief",  # type: ignore[arg-type]
        time_limit_s=60,
        max_solutions=2,
        seed=42,
        tolerances=TolerancePolicy.from_instance(PuzzleInstance.from_dict(documents.relief())),
        options={"frontier": "mrv"},
    )
    assert config.mode is Regime.RELIEF
    assert SolverConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config


@pytest.mark.parametrize("bad", [{"time_limit_s": 0}, {"time_limit_s": -1}, {"max_solutions": 0}])
def test_solver_config_refuses_impossible_limits(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        SolverConfig(solver="x", **bad)  # type: ignore[arg-type]


def _result(status: SolveStatus, solutions: tuple[Solution, ...]) -> SolveResult:
    return SolveResult(
        status=status,
        solver="python.contact_dfs",
        regime=Regime.FOOTPRINT,
        instance_hash="abc",
        solutions=solutions,
        exhaustive=True,
        metrics={"nodes": 12, "wall_s": 0.5},
    )


def test_solve_result_round_trips() -> None:
    solution = Solution({"p00": Pose(1.0, 2.0, 0.5)}, {"overlap_depth_mm": 0.0})
    result = _result(SolveStatus.SOLVED, (solution,))
    assert SolveResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_a_result_claims_no_completeness_unless_told() -> None:
    result = SolveResult(SolveStatus.INTERRUPTED, "x", Regime.FOOTPRINT, "abc")
    assert result.exhaustive is False
    assert result.candidates_proven_complete is False
    assert (result.candidate_set, result.config, result.solver_version) == ("", None, "")


def test_no_solution_found_is_only_said_by_a_search_that_finished() -> None:
    with pytest.raises(ValueError, match="ran to its end"):
        SolveResult(SolveStatus.NO_SOLUTION_FOUND, "x", Regime.FOOTPRINT, "abc")
    finished = SolveResult(
        SolveStatus.NO_SOLUTION_FOUND, "x", Regime.FOOTPRINT, "abc", exhaustive=True
    )
    assert finished.solutions == ()
    with pytest.raises(ValueError, match="was not exhaustive"):
        SolveResult(SolveStatus.INTERRUPTED, "x", Regime.FOOTPRINT, "abc", exhaustive=True)


def test_a_result_round_trips_with_its_configuration_and_verdicts() -> None:
    solution = Solution({"p00": Pose(1.0, 2.0, 0.5)}, {"overlap_depth_mm": 0.0}, valid=True)
    result = SolveResult(
        SolveStatus.SOLVED,
        "python.contact_dfs",
        Regime.FOOTPRINT,
        "abc",
        (solution, Solution({"p00": Pose(0.0, 0.0, 0.0)})),
        candidate_set="corner-contact/1",
        config=SolverConfig("python.contact_dfs", max_solutions=None, options={"node_limit": 5}),
        solver_version="0.1.0",
    )
    document = json.loads(json.dumps(result.to_dict()))
    assert document["solutions"][0]["valid"] is True
    assert document["solutions"][1]["valid"] is None
    assert document["config"]["maxSolutions"] is None
    assert SolveResult.from_dict(document) == result


def test_solved_means_there_is_a_solution() -> None:
    with pytest.raises(ValueError):
        _result(SolveStatus.SOLVED, ())
    with pytest.raises(ValueError):
        _result(SolveStatus.NO_SOLUTION_FOUND, (Solution({"p00": Pose(0.0, 0.0, 0.0)}),))
