"""``maxplus-solve``: run one solver on one puzzle from the command line."""

import argparse
import json
import sys
from collections.abc import Sequence

from maxplus_solvers.api import available_solvers, load_puzzle, solve
from maxplus_solvers.models import (
    Assumption,
    InstanceError,
    Regime,
    SolverConfig,
    SolveResult,
    SolveStatus,
)

# Exit codes.
SOLVED = 0
NOT_SOLVED = 1
INVALID = 3


def _max_solutions(text: str) -> int | None:
    if text == "all":
        return None
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError("must be at least 1, or 'all'")
    return count


def _option(text: str) -> tuple[str, object]:
    """``name=value``, the value read as JSON if it is JSON and as a word otherwise."""
    name, equals, value = text.partition("=")
    if not (name and equals):
        raise argparse.ArgumentTypeError("must be NAME=VALUE")
    try:
        return name, json.loads(value)
    except json.JSONDecodeError:
        return name, value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maxplus-solve",
        description="Solve a tiling puzzle and report what the search can and cannot claim.",
    )
    parser.add_argument("puzzle", help="an instance file, or a fixture id such as new5-flat")
    parser.add_argument("--solver", default="rust.contact_dfs", choices=available_solvers())
    parser.add_argument(
        "--mode",
        default=Regime.FOOTPRINT.value,
        choices=[regime.value for regime in Regime],
        help="the information the solver may use (default: footprint)",
    )
    parser.add_argument(
        "--assume",
        action="append",
        default=[],
        choices=[assumption.value for assumption in Assumption],
        help="something to take for granted about the assembly, such as edge-to-edge; "
        "it narrows what the search looks for",
    )
    parser.add_argument("--time-limit", type=float, metavar="SECONDS")
    parser.add_argument(
        "--max-solutions",
        type=_max_solutions,
        default=1,
        metavar="N",
        help="stop after N solutions, or 'all' to run the search to its end (default: 1)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        type=_option,
        metavar="NAME=VALUE",
        help="a solver option, such as lookahead=false or order=random; may be repeated",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="check every solution with the independent validator (needs the 'validate' extra)",
    )
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON")
    return parser


def _summary(result: SolveResult) -> str:
    lines = [f"{result.solver} on {result.instance_hash[:12]} ({result.regime}): {result.status}"]
    if result.exhaustive:
        reach = "the search ran to its end"
    else:
        reach = "the search was stopped before its end"
    proven = "proven" if result.candidates_proven_complete else "not proven"
    lines.append(f"  {reach}; candidates {result.candidate_set}, {proven} complete")
    if result.assumptions:
        lines.append(
            f"  assuming {', '.join(result.assumptions)}: other assemblies are not looked for"
        )
    for index, solution in enumerate(result.solutions):
        verdict = {None: "not validated", True: "valid", False: "INVALID"}[solution.valid]
        lines.append(f"  solution {index + 1}: {len(solution.poses)} pieces, {verdict}")
    shown = ("nodes", "backtracks", "placements", "candidates_generated")
    numbers = ", ".join(
        f"{name}={result.metrics[name]:.6g}" for name in shown if name in result.metrics
    )
    lines.append(f"  {numbers}")
    # Two different questions: how soon a solution turns up, and how long the whole search is.
    times = [
        f"{label} {result.metrics[name]:.3g} s"
        for name, label in (
            ("first_solution_s", "first solution after"),
            ("exhausted_s", "search finished after"),
        )
        if name in result.metrics
    ]
    if "exhausted_s" not in result.metrics and "wall_time_s" in result.metrics:
        times.append(f"stopped after {result.metrics['wall_time_s']:.3g} s")
    lines.append(f"  {'; '.join(times)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        puzzle = load_puzzle(args.puzzle)
        config = SolverConfig(
            solver=args.solver,
            mode=Regime(args.mode),
            time_limit_s=args.time_limit,
            max_solutions=args.max_solutions,
            seed=args.seed,
            options=dict(args.option),
            assumptions=tuple(args.assume),
        )
        result = solve(puzzle, config, validate=args.validate)
    except (FileNotFoundError, InstanceError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_summary(result))
    if any(solution.valid is False for solution in result.solutions):
        return INVALID
    return SOLVED if result.status is SolveStatus.SOLVED else NOT_SOLVED


if __name__ == "__main__":
    sys.exit(main())
