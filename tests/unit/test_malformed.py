"""Documents that must be refused.

Structural faults are refused twice, by the schema and by the loader, so that
neither can drift from the other. Geometric and cross-field faults are beyond a
JSON schema: the schema accepts them, which is asserted so the split stays
deliberate, and the loader refuses them.
"""

import math
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest

from maxplus_solvers import InstanceError, PuzzleInstance
from support import corpus, documents

Doc = dict[str, Any]


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    schema = corpus.schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _set(path: list[Any], value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        node: Any = doc
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value

    return mutate


def _drop(path: list[Any]) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        node: Any = doc
        for step in path[:-1]:
            node = node[step]
        del node[path[-1]]

    return mutate


STRUCTURAL: list[tuple[str, Callable[[], Doc], Callable[[Doc], None]]] = [
    # The three ways the source leaks the answer have nowhere to go.
    ("reference poses", documents.footprint, _set(["reference"], {"poses": []})),
    ("provenance", documents.footprint, _set(["provenance"], {})),
    ("scramble", documents.footprint, _set(["scramble"], {"defaultSeed": 1})),
    ("name", documents.footprint, _set(["name"], "16 easy")),
    ("seed in source", documents.relief, _set(["source"], {"seed": 1})),
    ("pose on a piece", documents.footprint, _set(["pieces", 0, "pose"], {"x": 0})),
    ("thickness on a piece", documents.footprint, _set(["pieces", 0, "thickness"], 12.0)),
    # Versioning and units.
    ("format version 2", documents.footprint, _set(["formatVersion"], 2)),
    ("format version true", documents.footprint, _set(["formatVersion"], True)),
    ("units", documents.footprint, _set(["units"], "cm")),
    ("unknown regime", documents.footprint, _set(["regime"], "flat")),
    # Required parts.
    ("no pieces key", documents.footprint, _drop(["pieces"])),
    ("empty pieces", documents.footprint, _set(["pieces"], [])),
    ("no target", documents.footprint, _drop(["target"])),
    ("no validation", documents.footprint, _drop(["validation"])),
    ("missing tolerance", documents.footprint, _drop(["validation", "overlapDepth"])),
    ("negative tolerance", documents.footprint, _set(["validation", "areaError"], -0.1)),
    ("zero span", documents.footprint, _set(["spanMm"], 0)),
    ("piece without id", documents.footprint, _drop(["pieces", 1, "id"])),
    ("empty piece id", documents.footprint, _set(["pieces", 1, "id"], "")),
    # Shapes of values.
    ("two-vertex polygon", documents.footprint, _set(["pieces", 0, "polygon"], [[0, 0], [1, 1]])),
    ("three coordinates", documents.footprint, _set(["pieces", 0, "polygon", 0], [0, 0, 0])),
    ("string coordinate", documents.footprint, _set(["pieces", 0, "polygon", 0, 0], "-36")),
    ("boolean coordinate", documents.footprint, _set(["target", "vertices", 0, 0], True)),
    ("roof missing gy", documents.relief, _drop(["pieces", 0, "roof", "gy"])),
    # Rules: format version 1 has one rule set.
    ("flipping allowed", documents.footprint, _set(["rules", "flip"], True)),
    ("stepped rotation", documents.footprint, _set(["rules", "rotate"], "quarter-turns")),
    ("snap rule", documents.footprint, _set(["rules", "snap"], False)),
    # Regime consistency.
    (
        "roof in footprint",
        documents.footprint,
        _set(["pieces", 0, "roof"], {"z0": 1, "gx": 0, "gy": 0}),
    ),
    ("relief height in footprint", documents.footprint, _set(["reliefMm"], 35.0)),
    (
        "roof tolerance in footprint",
        documents.footprint,
        _set(["validation", "roofMismatch"], 0.05),
    ),
    ("relief piece without roof", documents.relief, _drop(["pieces", 1, "roof"])),
    ("relief without relief height", documents.relief, _drop(["reliefMm"])),
    ("relief without roof tolerance", documents.relief, _drop(["validation", "roofMismatch"])),
    (
        "construction data in relief",
        documents.relief,
        _set(["tropical"], {"construction": {}, "pieceTerms": {}}),
    ),
    (
        "construction data in footprint",
        documents.footprint,
        _set(["tropical"], {"construction": {}, "pieceTerms": {}}),
    ),
    ("tropical-aware without construction", documents.tropical_aware, _drop(["tropical"])),
    (
        "tropical-aware without piece terms",
        documents.tropical_aware,
        _drop(["tropical", "pieceTerms"]),
    ),
]

SEMANTIC: list[tuple[str, Callable[[], Doc], Callable[[Doc], None]]] = [
    (
        "clockwise piece",
        documents.footprint,
        _set(["pieces", 0, "polygon"], [[-36, 72], [36, 72], [36, -72], [-36, -72]]),
    ),
    (
        "clockwise target",
        documents.footprint,
        _set(["target", "vertices"], [[-72, 72], [72, 72], [72, -72], [-72, -72]]),
    ),
    (
        "reflex piece",
        documents.footprint,
        _set(["pieces", 0, "polygon"], [[-36, -72], [36, -72], [0, 0], [36, 72], [-36, 72]]),
    ),
    (
        "collinear vertex",
        documents.footprint,
        _set(["pieces", 0, "polygon"], [[-36, -72], [0, -72], [36, -72], [36, 72], [-36, 72]]),
    ),
    (
        "piece not centred on its centroid",
        documents.footprint,
        _set(["pieces", 0, "polygon"], [[0, 0], [72, 0], [72, 144], [0, 144]]),
    ),
    ("duplicate piece id", documents.footprint, _set(["pieces", 1, "id"], "p00")),
    ("NaN coordinate", documents.footprint, _set(["pieces", 0, "polygon", 0, 0], math.nan)),
    ("infinite roof", documents.relief, _set(["pieces", 0, "roof", "z0"], math.inf)),
    (
        "piece terms naming another piece",
        documents.tropical_aware,
        _set(["tropical", "pieceTerms"], {"p00": "A", "p07": "B"}),
    ),
]


def test_the_starting_documents_are_valid(validator: jsonschema.Draft202012Validator) -> None:
    for document in (documents.footprint, documents.relief, documents.tropical_aware):
        for doc in (document(), documents.with_source(document())):
            validator.validate(doc)
            PuzzleInstance.from_dict(doc)


@pytest.mark.parametrize(("name", "base", "mutate"), STRUCTURAL, ids=[r[0] for r in STRUCTURAL])
def test_structural_faults_are_refused_by_schema_and_loader(
    name: str,
    base: Callable[[], Doc],
    mutate: Callable[[Doc], None],
    validator: jsonschema.Draft202012Validator,
) -> None:
    doc = base()
    mutate(doc)
    assert not validator.is_valid(doc), "the schema accepted it"
    with pytest.raises(InstanceError):
        PuzzleInstance.from_dict(doc)


@pytest.mark.parametrize(("name", "base", "mutate"), SEMANTIC, ids=[r[0] for r in SEMANTIC])
def test_semantic_faults_pass_the_schema_and_are_refused_by_the_loader(
    name: str,
    base: Callable[[], Doc],
    mutate: Callable[[Doc], None],
    validator: jsonschema.Draft202012Validator,
) -> None:
    doc = base()
    mutate(doc)
    assert validator.is_valid(doc), "the schema now catches this: move the row to STRUCTURAL"
    with pytest.raises(InstanceError):
        PuzzleInstance.from_dict(doc)


@pytest.mark.parametrize("not_an_object", [None, [], "instance", 1])
def test_the_loader_refuses_anything_but_an_object(not_an_object: Any) -> None:
    with pytest.raises(InstanceError):
        PuzzleInstance.from_dict(not_an_object)
