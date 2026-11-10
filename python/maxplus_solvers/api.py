"""The public entry points. Importing from ``maxplus_solvers`` directly is equivalent."""

import os
from pathlib import Path

from maxplus_solvers.io.instance import load_instance
from maxplus_solvers.models import PuzzleInstance, Regime

FIXTURES_ENV = "MAXPLUS_FIXTURES"
_DEFAULT_FIXTURES = Path("benchmarks") / "fixtures"


def load_puzzle(
    path_or_id: str | os.PathLike[str], regime: Regime | str | None = None
) -> PuzzleInstance:
    """Load a puzzle instance from a file, or a corpus fixture by id.

    An existing path is read as it is. Anything else is taken as a fixture id
    and looked up as ``<id>.json`` in the directory named by ``MAXPLUS_FIXTURES``,
    or in ``benchmarks/fixtures`` under the current directory.

    ``regime`` reduces the instance to a regime with less information, for
    example a relief puzzle to its footprint. It cannot add information.
    """
    path = Path(path_or_id)
    if not path.is_file():
        directory = Path(os.environ.get(FIXTURES_ENV, _DEFAULT_FIXTURES))
        candidate = directory / f"{path_or_id}.json"
        if not candidate.is_file():
            raise FileNotFoundError(
                f"{path_or_id!s} is neither a file nor a fixture id in {directory}"
            )
        path = candidate
    instance = load_instance(path)
    return instance if regime is None else instance.as_regime(regime)
