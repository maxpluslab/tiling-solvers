"""The metrics record every solver fills in. ``docs/solver-contract.md`` defines the fields."""

from dataclasses import dataclass, fields


@dataclass(slots=True)
class SearchMetrics:
    """Counts of search effort and candidate work, and times.

    The counts are deterministic for a deterministic solver. The times are not,
    and nothing should be asserted about them.
    """

    # Search nodes expanded, the root included.
    nodes: int = 0
    # Nodes left without success: no piece fits the corner branched on, a pruning
    # rule calls the state a dead end, or every piece is down and something is uncovered.
    backtracks: int = 0
    # Pieces put down as a branch of the search, counting every attempt.
    placements: int = 0
    # The largest number of pieces down at once.
    max_depth: int = 0
    # Placements generated from contacts, and how many were refused and why.
    candidates_generated: int = 0
    rejected_outside: int = 0
    rejected_overlap: int = 0
    rejected_roof: int = 0
    # Nodes given up by a pruning rule, and candidates dropped before they became nodes.
    pruned_cavity: int = 0
    pruned_closure: int = 0
    pruned_anchor: int = 0
    pruned_lookahead: int = 0
    # Assemblies found that were a turn of one already found.
    duplicates: int = 0
    solutions: int = 0
    wall_time_s: float = 0.0
    cpu_time_s: float = 0.0
    # Wall time until the first solution; absent if there was none.
    first_solution_s: float | None = None
    # Wall time until the search had run to its end; absent if it was stopped first.
    exhausted_s: float | None = None
    # For a solver that chooses from a list of placements: the size of the list and of
    # the constraints on the choice, the work of the choosing, and where the time went.
    # Absent for a solver that does not.
    model_placements: int | None = None
    model_cliques: int | None = None
    model_pairs: int | None = None
    model_covers: int | None = None
    sat_branches: int | None = None
    sat_conflicts: int | None = None
    listing_s: float | None = None
    model_s: float | None = None
    sat_s: float | None = None

    def to_dict(self) -> dict[str, float]:
        """The record as ``SolveResult.metrics`` carries it. Absent values are left out."""
        out: dict[str, float] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None:
                out[item.name] = value
        return out
