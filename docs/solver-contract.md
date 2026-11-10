# The solver contract

Every solver is called the same way and answers in the same form. This document says what the form means: what each status claims, how far a completeness claim reaches, and what the numbers in a result are. The algorithms behind the solvers are in [algorithms.md](algorithms.md).

```python
from maxplus_solvers import SolverConfig, load_puzzle, solve

puzzle = load_puzzle("new5-flat")
result = solve(puzzle, SolverConfig("python.contact_dfs", max_solutions=None), validate=True)
```

```sh
maxplus-solve new5-flat --max-solutions all --validate
```

## The call

`solve(instance, config, *, validate=False) -> SolveResult`

| `SolverConfig` field | Meaning |
| --- | --- |
| `solver` | A registered name; `available_solvers()` lists them. |
| `mode` | The information regime the solver may use: `footprint`, `relief` or `tropical-aware`. Default `footprint`. |
| `time_limit_s` | Wall-clock limit, or `None`. Checked between search nodes, so a run may exceed it by the cost of one node. |
| `max_solutions` | Stop after this many solutions. `None` runs the search to its end. Default 1. |
| `seed` | For solvers that randomize. A deterministic solver ignores it and says so. |
| `tolerances` | A `TolerancePolicy`, or `None` for the instance's published ones. |
| `options` | Solver-specific. An option a solver does not know is an error, not ignored. |

Before the solver runs, the instance is reduced to `config.mode`. A relief puzzle solved in `footprint` mode is handed over without its roofs, and the result's `instance_hash` is that of the reduced instance. Asking for a mode with more information than the instance has is an error, and so is a mode the solver does not declare. Results from different regimes are not comparable.

## Status

| `status` | Returned when | `exhaustive` |
| --- | --- | --- |
| `solved` | At least one solution is in `solutions`. | `true` if the search ran to its end, so that `solutions` is everything it can find; `false` if it stopped at `max_solutions` or at a limit. |
| `no_solution_found` | The search ran to its end and found nothing. | Always `true`. |
| `interrupted` | A limit stopped the search before it found anything. | Always `false`. |

`SolveResult` refuses combinations outside this table.

`no_solution_found` is not "the puzzle has no solution". It says the solver's candidates contain none. The next section says when the stronger statement is allowed.

## Completeness claims

A result carries three fields that bound what may be concluded from it.

- **`exhaustive`**: the search visited everything in its own search space. It says nothing about whether that space is the right one.
- **`candidate_set`**: the name of that space.
- **`candidates_proven_complete`**: the candidate set is known to contain every solution of the instance, as the validator defines a solution.

Only `exhaustive` and `candidates_proven_complete` together turn "none found" into "none exists", or "these were found" into "these are all". With `candidates_proven_complete = false`, a count or an absence is a statement about the candidate set.

No solver in this repository sets `candidates_proven_complete` today, and a solver that computes in floating point should not set it on the strength of an argument about exact arithmetic.

### Candidate sets

| Name | Solvers | Contents |
| --- | --- | --- |
| `corner-contact/1` | `python.contact_dfs` | Placements with a piece vertex at a corner of the uncovered region and the edge leaving it flush against the corner's first side, within the contact noise. Complete for exact assemblies of convex pieces by the argument in [algorithms.md](algorithms.md#why-the-rule-loses-no-assembly), in exact arithmetic. It does not contain assemblies that only pass because of the validation tolerances. |

A change to what a candidate set contains gets a new name.

## Solutions

A `Solution` gives a pose for every piece, by piece id: rotate the local polygon by `theta`, then translate by `(x, y)`, in millimetres and radians.

`residuals` and `valid` are the independent validator's findings. They are `None` unless `solve(..., validate=True)` was asked for, which needs the `validate` extra. A solver never fills them in, and the validator is never part of a search: a solver that used it would be checking its answer with its own oracle.

`valid = false` on a returned solution means the solver and the validator disagree. That is a bug in one of them, and `maxplus-solve` exits with code 3.

### When two solutions are the same

Each solver states which differences it counts.

| Solver | Counted once | Counted separately |
| --- | --- | --- |
| `python.contact_dfs` | Assemblies that differ by exchanging congruent pieces; assemblies that differ by turning a piece onto itself. | Assemblies that differ by a rotation of the whole tray. |

A canonical form that also identifies rotations of the tray comes with phase 5.

## Metrics

`SolveResult.metrics` maps names to numbers. The search counts are deterministic for a deterministic solver; the times are not, and tests assert nothing about them.

| Name | Meaning |
| --- | --- |
| `nodes` | Search nodes expanded, the root included. |
| `backtracks` | Nodes abandoned as dead ends: no candidate for the corner branched on, or all pieces placed with something left uncovered. |
| `placements` | Pieces put down, counting every attempt. |
| `max_depth` | The largest number of pieces down at once. |
| `candidates_generated` | Placements computed from contacts, before any check. |
| `rejected_outside` | Of those, refused for reaching outside the target. |
| `rejected_overlap` | Of the rest, refused for entering a placed piece. |
| `solutions` | Solutions returned. |
| `wall_time_s`, `cpu_time_s` | Elapsed and processor time of the solve. |
| `first_solution_s` | Wall time to the first solution. Absent if there was none. |

A solver for which a count has no meaning leaves it at zero. New metrics are added to `SearchMetrics` and to this table together.

## Reproducibility

A result records `solver`, `solver_version`, `regime`, `instance_hash` and the whole `config`, including seed, tolerances and options. `SolveResult.to_dict()` and `from_dict()` round-trip all of it as JSON; `maxplus-solve --json` prints that document.

## The command

`maxplus-solve PUZZLE [--solver NAME] [--mode REGIME] [--time-limit SECONDS] [--max-solutions N|all] [--seed N] [--validate] [--json]`

`PUZZLE` is an instance file or a fixture id.

| Exit code | Meaning |
| --- | --- |
| 0 | `solved` |
| 1 | `no_solution_found` or `interrupted` |
| 2 | The arguments, the puzzle or the configuration were refused |
| 3 | `--validate` found a returned solution invalid |

## Registered solvers

| Name | Regimes | What it is |
| --- | --- | --- |
| `python.contact_dfs` | footprint | The Python prototype of the corner contact search. Deterministic; ignores `seed`. Option `node_limit`: stop after that many nodes. |

## Adding a solver

A solver is a function `(PuzzleInstance, SolverConfig) -> SolveResult`, registered with `solvers.register(SolverSpec(...))` under a name of the form `<family>.<algorithm>`. It must:

- declare the regimes it uses, and use nothing beyond the instance it is given;
- refuse options it does not know;
- honour `time_limit_s` and `max_solutions`;
- name its candidate set, and add the set to the table above;
- set `exhaustive` only when it visited its whole search space, and `candidates_proven_complete` only with a proof that survives the arithmetic it uses;
- say which differences between solutions it counts;
- fill in the metrics that apply to it;
- never call the validator.
