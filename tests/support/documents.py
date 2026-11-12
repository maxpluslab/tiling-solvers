"""Hand-written instance documents, valid by inspection, as starting points for tests.

Two 72 mm by 144 mm strips in a 144 mm square, at the scale of the corpus so that
tolerances come out at the published rev2 values. Every call returns a fresh copy.
"""

from typing import Any

_VALIDATION = {
    "contactNoise": 1e-06,
    "overlapDepth": 0.006,
    "outsideDepth": 0.006,
    "areaError": 0.012,
    "edgeAngleDeg": 3,
    "edgeMinOverlap": 0.02,
}


def _strip() -> list[list[float]]:
    return [[-36.0, -72.0], [36.0, -72.0], [36.0, 72.0], [-36.0, 72.0]]


def footprint() -> dict[str, Any]:
    return {
        "formatVersion": 1,
        "id": "strips",
        "regime": "footprint",
        "units": "mm",
        "spanMm": 144.0,
        "target": {"vertices": [[-72.0, -72.0], [72.0, -72.0], [72.0, 72.0], [-72.0, 72.0]]},
        "pieces": [{"id": "p00", "polygon": _strip()}, {"id": "p01", "polygon": _strip()}],
        "rules": {"translate": True, "rotate": "continuous-z", "flip": False},
        "validation": dict(_VALIDATION),
    }


def relief() -> dict[str, Any]:
    doc = footprint()
    doc["regime"] = "relief"
    doc["reliefMm"] = 35.0
    doc["pieces"][0]["roof"] = {"z0": 20.0, "gx": 0.25, "gy": 0.0}
    doc["pieces"][1]["roof"] = {"z0": 20.0, "gx": -0.25, "gy": 0.0}
    doc["validation"]["roofMismatch"] = 0.05
    return doc


def tropical_aware() -> dict[str, Any]:
    doc = relief()
    doc["regime"] = "tropical-aware"
    doc["tropical"] = {
        "construction": {"convention": "max", "terms": [{"id": "A"}, {"id": "B"}]},
        "pieceTerms": {"p00": "B", "p01": "A"},
    }
    return doc


def with_source(doc: dict[str, Any]) -> dict[str, Any]:
    doc["source"] = {
        "repository": "https://example.invalid/puzzles",
        "commit": "0123abc",
        "puzzleId": "strips",
        "geometryHash": "feed",
    }
    return doc


# Three strips side by side in a 120 mm by 72 mm tray, 24, 36 and 60 mm wide, in
# that order from the left wall at x = -60. Their centres are at x = -48, -18 and 30.
THREE_STRIP_WIDTHS = (24.0, 36.0, 60.0)
THREE_STRIP_CENTRES = (-48.0, -18.0, 30.0)


def three_strips() -> dict[str, Any]:
    """A footprint puzzle with 3! = 6 assemblies: the strips in any order.

    The tray is a rectangle, with a half turn and no quarter turn. The half
    turn reverses an order, so the 6 are 3 pairs.
    """

    def strip(width: float) -> list[list[float]]:
        half = width / 2
        return [[-half, -36.0], [half, -36.0], [half, 36.0], [-half, 36.0]]

    doc = footprint()
    doc["id"] = "three-strips"
    doc["spanMm"] = 120.0
    doc["target"] = {"vertices": [[-60.0, -36.0], [60.0, -36.0], [60.0, 36.0], [-60.0, 36.0]]}
    doc["pieces"] = [
        {"id": f"p{index:02d}", "polygon": strip(width)}
        for index, width in enumerate(THREE_STRIP_WIDTHS)
    ]
    return doc


def three_strips_relief() -> dict[str, Any]:
    """The same strips, each with the roof it has under ``z = 20 + (x + 60) / 4``.

    From the left, the roofs run 20 to 26, 26 to 35 and 35 to 50 mm. Two
    unturned strips meet only where one's right height is the other's left,
    which is the order they were cut in. A strip turned half round shows its
    other edge, and no two right heights or two left heights agree. So the
    roofs are continuous in that one order, and in its half turn with the tray:
    2 assemblies, 1 pair.
    """
    doc = three_strips()
    doc["regime"] = "relief"
    doc["reliefMm"] = 50.0
    doc["validation"]["roofMismatch"] = 0.05
    for piece, centre in zip(doc["pieces"], THREE_STRIP_CENTRES, strict=True):
        piece["roof"] = {"z0": 20.0 + (centre + 60.0) / 4, "gx": 0.25, "gy": 0.0}
    return doc


def block_and_squares() -> dict[str, Any]:
    """A 144 by 72 mm block and two 72 mm squares in the 144 mm tray.

    They fit one way, up to turning the tray and exchanging the squares: the
    block along one wall, the squares side by side along it. Their shared
    corner then stands at the middle of the block's long edge, a T, so no
    assembly of these pieces meets edge to edge.
    """
    doc = footprint()
    block = [[-72.0, -36.0], [72.0, -36.0], [72.0, 36.0], [-72.0, 36.0]]
    square = [[-36.0, -36.0], [36.0, -36.0], [36.0, 36.0], [-36.0, 36.0]]
    doc["id"] = "block-and-squares"
    doc["pieces"] = [
        {"id": "p00", "polygon": block},
        {"id": "p01", "polygon": [list(v) for v in square]},
        {"id": "p02", "polygon": [list(v) for v in square]},
    ]
    return doc
