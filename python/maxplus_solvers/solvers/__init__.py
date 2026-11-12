"""The solver registry: every solver behind one name and one calling convention.

A solver is a function from an instance and a configuration to a
:class:`~maxplus_solvers.models.SolveResult`. It is registered with the regimes
it can use, and :func:`maxplus_solvers.api.solve` hands it an instance already
reduced to the regime the configuration asks for.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from maxplus_solvers.models import Assumption, PuzzleInstance, Regime, SolverConfig, SolveResult

SolverFunction = Callable[[PuzzleInstance, SolverConfig], SolveResult]


@dataclass(frozen=True, slots=True)
class SolverSpec:
    """A registered solver and what it declares about itself."""

    name: str
    run: SolverFunction
    # For each information regime it can work in, the name of the candidate set
    # its completeness claims are relative to there. Results across regimes are
    # not comparable.
    candidate_sets: Mapping[Regime, str]
    description: str
    # The assumptions it can be asked to make. Making one changes what it looks
    # for, so a solver that has not declared it is not handed it.
    assumptions: frozenset[Assumption] = frozenset()

    @property
    def regimes(self) -> frozenset[Regime]:
        return frozenset(self.candidate_sets)


_REGISTRY: dict[str, SolverSpec] = {}


def register(spec: SolverSpec) -> None:
    if spec.name in _REGISTRY:
        raise ValueError(f"solver {spec.name!r} is already registered")
    if not spec.regimes:
        raise ValueError(f"solver {spec.name!r} declares no regime")
    _REGISTRY[spec.name] = spec


def available() -> tuple[str, ...]:
    """Names of the registered solvers, sorted."""
    return tuple(sorted(_REGISTRY))


def get(name: str) -> SolverSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(available()) or "none"
        raise ValueError(f"unknown solver {name!r}; registered: {known}") from None


def _register_builtin() -> None:
    from maxplus_solvers.solvers import contact_dfs, cp_sat
    from maxplus_solvers.solvers.prototypes import contact_dfs as prototype

    register(contact_dfs.SPEC)
    # Registering needs no OR-Tools; running does.
    register(cp_sat.SPEC)
    register(prototype.SPEC)


_register_builtin()
