"""The instance-v1 JSON format on disk (``schemas/instance-v1.json``)."""

import json
from pathlib import Path
from typing import Any

from maxplus_solvers.models import InstanceError, PuzzleInstance


def _is_flat(value: Any) -> bool:
    """A list of numbers, or a list of number pairs: short enough to keep on one line."""
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)


def format_json(value: Any, indent: int = 0) -> str:
    """Indented JSON with each coordinate pair on one line.

    The output is deterministic: key order is the insertion order of the
    document, and floats use ``repr``, the shortest string that round-trips.
    """
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{pad}{json.dumps(k)}: {format_json(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + f"\n{end}}}"
    if isinstance(value, list) and not _is_flat(value) and value:
        rows = [f"{pad}{format_json(v, indent + 1)}" for v in value]
        return "[\n" + ",\n".join(rows) + f"\n{end}]"
    return json.dumps(value, allow_nan=False)


def write_json(path: Path, document: Any) -> None:
    """Write a document with LF line endings on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_json(document) + "\n", encoding="utf-8", newline="\n")


def dump_instance(instance: PuzzleInstance) -> str:
    return format_json(instance.to_dict()) + "\n"


def save_instance(instance: PuzzleInstance, path: str | Path) -> None:
    write_json(Path(path), instance.to_dict())


def load_instance(path: str | Path) -> PuzzleInstance:
    """Read and check an instance file."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InstanceError(f"{path}: not valid JSON ({error})") from error
    try:
        return PuzzleInstance.from_dict(document)
    except InstanceError as error:
        raise InstanceError(f"{path}: {error}") from error
