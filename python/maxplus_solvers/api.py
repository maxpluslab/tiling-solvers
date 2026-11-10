"""The public entry points. Importing from ``maxplus_solvers`` directly is equivalent."""

import os
from dataclasses import replace
from pathlib import Path

from maxplus_solvers import solvers
from maxplus_solvers.io.instance import load_instance
from maxplus_solvers.models import PuzzleInstance, Regime, SolverConfig, SolveResult

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


def available_solvers() -> tuple[str, ...]:
    """Names that ``SolverConfig.solver`` may take."""
    return solvers.available()


def solve(instance: PuzzleInstance, config: SolverConfig, *, validate: bool = False) -> SolveResult:
    """Run the solver named by ``config`` on ``instance``.

    The solver sees the instance reduced to ``config.mode``: asking for
    ``footprint`` on a relief puzzle hides the roofs from it. A mode with more
    information than the instance has, or one the solver does not declare, is
    an error.

    With ``validate``, every returned solution is checked by the independent
    validator against the instance in that same regime, and comes back with its
    residuals and verdict. That needs the ``validate`` extra. The check is
    never part of the search.
    """
    spec = solvers.get(config.solver)
    if config.mode not in spec.regimes:
        offered = ", ".join(sorted(regime.value for regime in spec.regimes))
        raise ValueError(
            f"solver {spec.name!r} does not work in {config.mode} mode; it has {offered}"
        )
    seen = instance.as_regime(config.mode)
    result = spec.run(seen, config)
    if not validate:
        return result

    from maxplus_solvers.validation import validate_solution

    checked = []
    for solution in result.solutions:
        report = validate_solution(seen, solution, config.tolerances)
        checked.append(replace(solution, residuals=report.residuals(), valid=report.solved))
    return replace(result, solutions=tuple(checked))
