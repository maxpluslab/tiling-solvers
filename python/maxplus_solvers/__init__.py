"""MaxPlus Lab tiling solvers.

Python owns orchestration, experiments and analysis. The compiled ``_native``
module holds the Rust geometry and search, and is private: import from this
package, not from ``_native``.
"""

from maxplus_solvers import _native
from maxplus_solvers.api import load_puzzle
from maxplus_solvers.models import (
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

__version__: str = _native.version()

__all__ = [
    "InstanceError",
    "Piece",
    "Pose",
    "PuzzleInstance",
    "Regime",
    "Roof",
    "Solution",
    "SolveResult",
    "SolveStatus",
    "SolverConfig",
    "TolerancePolicy",
    "__version__",
    "load_puzzle",
]
