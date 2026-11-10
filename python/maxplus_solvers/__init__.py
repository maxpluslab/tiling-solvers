"""MaxPlus Lab tiling solvers.

Python owns orchestration, experiments and analysis. The compiled ``_native``
module holds the Rust geometry and search, and is private: import from this
package, not from ``_native``.
"""

from maxplus_solvers import _native

__version__: str = _native.version()

__all__ = ["__version__"]
