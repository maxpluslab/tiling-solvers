# The solver contract

Every solver is called the same way and answers in the same form. This document says what the form means: what each status claims, how far a completeness claim reaches, and what the numbers in a result are. The algorithms behind the solvers are in [algorithms.md](algorithms.md).

```python
from maxplus_solvers import SolverConfig, load_puzzle, solve

puzzle = load_puzzle("new5-flat")
result = solve(puzzle, SolverConfig("rust.contact_dfs", max_solutions=None), validate=True)
```

```sh
maxplus-solve new5-flat --max-solutions all --validate
maxplus-solve new5 --mode relief --max-solutions all --option closure_pruning=false
```

## The call

`solve(instance, config, *, validate=False) -> SolveResult`

| `SolverConfig` field | Meaning |
| --- | --- |
| `solver` | A registered name; `available_solvers()` lists them. |
| `mode` | The information regime the solver may use: `footprint`, `relief` or `tropical-aware`. Default `footprint`. |
| `time_limit_s` | Wall-clock limit, or `None`. Checked between search nodes, so a run may exceed it by the cost of one node. |
| `max_solutions` | Stop after this many solutions. `None` runs the search to its end. Default 1. |
| `seed` | For solvers that randomize. A deterministic solver ignores it and says so. A solver that uses it gives the same result for the same seed. |
| `tolerances` | A `TolerancePolicy`, or `None` for the instance's published ones. |
| `options` | Solver-specific. An option a solver does not know is an error, not ignored. |
| `assumptions` | What the solver is to take for granted about the assemblies it looks for. Today one: `edge-to-edge`. Default none. See [Assumptions](#assumptions). |

Before the solver runs, the instance is reduced to `config.mode`. A relief puzzle solved in `footprint` mode is handed over without its roofs, and the result's `instance_hash` is that of the reduced instance. Asking for a mode with more information than the instance has is an error, and so is a mode the solver does not declare. Results from different regimes are not comparable.

## Status

| `status` | Returned when | `exhaustive` |
| --- | --- | --- |
| `solved` | At least one solution is in `solutions`. | `true` if the search ran to its end, so that `solutions` is everything it can find; `false` if it stopped at `max_solutions` or at a limit. |
| `no_solution_found` | The search ran to its end and found nothing. | Always `true`. |
| `interrupted` | A limit stopped the search before it found anything. | Always `false`. |

`SolveResult` refuses combinations outside this table.

`no_solution_found` is not "the puzzle has no solution". It says the solver's candidates contain none. The next section says when the stronger statement is allowed.

## Assumptions

An assumption narrows what a solver looks for, where a regime limits what it is told. It is a statement about the assembly sought, such as "the pieces meet edge to edge", and a solver that makes it does not look for assemblies that break it. That makes it unlike an option: a pruning rule must not change what a whole search finds, an assumption does by design.

| Assumption | Meaning | Solvers |
| --- | --- | --- |
| `edge-to-edge` | No vertex of a piece lies strictly inside an edge of another piece. Inside the tray two pieces share a whole edge of both, or a point, and never meet in a T. True of every puzzle cut from a tropical curve, which is a polyhedral complex. | `rust.contact_dfs` |

A solver declares the assumptions it can make, and `solve` refuses one it has not declared. The result's `assumptions` repeat what was assumed, and its `candidate_set` names a set that says so. Every claim of the result, `no_solution_found` and solution counts included, is about the assemblies that satisfy its assumptions: "one assembly, assuming edge to edge" leaves open how many there are with a T. Results under different assumptions are not comparable, any more than results in different regimes; benchmark tables show the assumption on every row whenever one is made.

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
| `corner-contact/1` | `python.contact_dfs`, `rust.contact_dfs` (footprint) | Placements with a piece vertex at a corner of the uncovered region and the edge leaving it flush against the corner's first side, within the contact noise. Complete for exact assemblies of convex pieces by the argument in [algorithms.md](algorithms.md#why-the-rule-loses-no-assembly), in exact arithmetic. It does not contain assemblies that only pass because of the validation tolerances. |
| `corner-contact-relief/1` | `rust.contact_dfs` (relief) | The placements of `corner-contact/1` whose roofs continue the roofs already down: at the corner, and along every edge stretch shared with a placed piece, the two roofs differ in height by no more than the contact noise times the steepest roof gradient (at least the contact noise). Complete, in exact arithmetic, for exact assemblies whose roofs are exactly continuous. The validator allows a roof step of 1.75 mm on the corpus; assemblies that need any of that allowance are not in the set. |
| `corner-contact-reachable/1` | `cp_sat.placements` (footprint) | The placements of `corner-contact/1` that the search of `rust.contact_dfs` puts down somewhere in its tree, with the listing options the result records. A finite list, built by running that search to its end. It holds every assembly that search finds and, being a subset of `corner-contact/1`, no more. If the listing was cut short by a limit the list is a part of this set and the result is not `exhaustive`. |
| `corner-contact-relief-reachable/1` | `cp_sat.placements` (relief) | The same, of `corner-contact-relief/1`. |
| `corner-contact-edge-to-edge/1` | `rust.contact_dfs` (footprint, assuming `edge-to-edge`) | The placements of `corner-contact/1` that put no vertex strictly inside an edge of a placed piece, and no vertex of a placed piece strictly inside one of theirs, by more than the contact noise from either end. Complete, in exact arithmetic, for exact assemblies without a T. |
| `corner-contact-relief-edge-to-edge/1` | `rust.contact_dfs` (relief, assuming `edge-to-edge`) | The same, of `corner-contact-relief/1`. |

A change to what a candidate set contains gets a new name. A rule that only removes candidates which cannot be part of any assembly in the set (the pruning rules of `rust.contact_dfs`) does not change the set: by the arguments in [algorithms.md](algorithms.md#the-rust-contact-search), and by test, the whole search finds the same assemblies with the rule on or off.

## Solutions

A `Solution` gives a pose for every piece, by piece id: rotate the local polygon by `theta`, then translate by `(x, y)`, in millimetres and radians.

`residuals` and `valid` are the independent validator's findings. They are `None` unless `solve(..., validate=True)` was asked for, which needs the `validate` extra. A solver never fills them in, and the validator is never part of a search: a solver that used it would be checking its answer with its own oracle.

`valid = false` on a returned solution means the solver and the validator disagree. That is a bug in one of them, and `maxplus-solve` exits with code 3.

### When two solutions are the same

Each solver states which differences it counts.

| Solver | Counted once | Counted separately |
| --- | --- | --- |
| `python.contact_dfs` | Assemblies that differ by exchanging congruent pieces; assemblies that differ by turning a piece onto itself. | Assemblies that differ by a rotation of the whole tray. |
| `rust.contact_dfs` | The same, and with `tray_rotations=once` (the default) assemblies that differ by a rotation of the whole tray. | With `tray_rotations=all`, assemblies that differ by a rotation of the tray. Mirror images always: pieces are not turned over. |

In the relief regime "congruent" and "onto itself" include the roof: two pieces of one shape under different roofs are different pieces, and a rectangle under a sloping roof is not its own half turn. A footprint solution of a relief puzzle may therefore put a symmetric piece either way round, and need not pass the relief validator.

| `cp_sat.placements` | As `rust.contact_dfs`. With `tray_rotations=once`, a choice that is a tray rotation of one already returned is recognised from the listed placements and counted in `duplicates`. | As `rust.contact_dfs`. |

`rust.contact_dfs` returns each solution in a canonical form: of the poses that describe the same assembly, a fixed one. With `tray_rotations=once` the orientation of the tray is part of that choice, so the assembly returned may be the answer key turned by a rotation of the tray.

`cp_sat.placements` returns the same assemblies but not in that form: of an assembly and its tray rotations it returns whichever it chose first, and congruent pieces take the chosen places in piece order. Compare its solutions with another solver's as placed polygons, not pose by pose.

## Metrics

`SolveResult.metrics` maps names to numbers. The search counts are deterministic for a deterministic solver; the times are not, and tests assert nothing about them.

| Name | Meaning |
| --- | --- |
| `nodes` | Search nodes expanded, the root included. |
| `backtracks` | Nodes abandoned as dead ends: no candidate for the corner branched on, all pieces placed with something left uncovered, or a pruning rule. |
| `backtrack_depth` | The number of pieces down at each backtrack, added up. `backtrack_depth / backtracks` is the mean contradiction depth: how many pieces are placed, on average, when the search finds it is wrong. |
| `placements` | Pieces put down, counting every attempt. |
| `max_depth` | The largest number of pieces down at once. |
| `candidates_generated` | Placements computed from contacts, before any check. |
| `rejected_outside` | Of those, refused for reaching outside the target. |
| `rejected_overlap` | Of the rest, refused for entering a placed piece. |
| `rejected_roof` | Refused because the roof would not continue a neighbour's: at the corner, before any polygon work, or along a shared edge, after the two checks above. Zero in the footprint regime. |
| `rejected_junction` | Assuming `edge-to-edge`: refused for meeting a placed piece in a T. Absent without the assumption. |
| `rejected_wall` | Assuming `edge-to-edge`: refused for taking an edge that no other piece's edge can lie against off the tray. Absent without the assumption. |
| `pruned_cavity` | Nodes abandoned because a cavity could not be filled: its area is no sum of areas of remaining pieces that fit it, or some remaining piece fits no cavity. |
| `pruned_closure` | Nodes abandoned because a straight run or a convex corner of the uncovered region could not be closed by the remaining pieces. |
| `pruned_anchor` | Placements of the anchor piece left out for lying outside its sector of the tray. |
| `pruned_lookahead` | Placements examined one step ahead and found to lead to a dead end. Each costs about what a node does; `nodes + pruned_lookahead` is the number of states examined. |
| `duplicates` | Complete assemblies reached and not returned, being a tray rotation of one already found. |
| `solutions` | Solutions returned. |
| `wall_time_s`, `cpu_time_s` | Elapsed and processor time of the solve. |
| `first_solution_s` | Wall time to the first solution. Absent if there was none. |
| `exhausted_s` | Wall time to the end of the search. Absent unless the result is `exhaustive`. With `first_solution_s` it separates finding an assembly from showing there is no other. |

A solver that chooses from a list of placements (`cp_sat.placements`) reports the counts above for the search that built the list, with `duplicates` and `solutions` for the choosing, and adds:

| Name | Meaning |
| --- | --- |
| `model_placements` | Placements listed: one Boolean each. |
| `model_cliques` | Sets of placements stated as "at most one": those that hold one probe point well inside them. |
| `model_pairs` | Conflicting pairs no clique states: overlaps too thin for a probe, and roof steps between neighbours. |
| `model_covers` | Sets of placements stated as "at least one": those that reach one probe point of the target. Zero with `coverage=false`. |
| `sat_branches`, `sat_conflicts` | CP-SAT's count of decisions and of conflicts, with one worker. Zero conflicts means propagation and decisions alone reached every answer. |
| `listing_s`, `model_s`, `sat_s` | Wall time of the listing search with its conflict computation, of building the model, and of CP-SAT. |

A solver for which a count has no meaning leaves it at zero; the model metrics are absent from solvers that have no model. New metrics are added to `SearchMetrics` and to these tables together.

## Reproducibility

A result records `solver`, `solver_version`, `regime`, `instance_hash` and the whole `config`, including seed, tolerances and options. `SolveResult.to_dict()` and `from_dict()` round-trip all of it as JSON; `maxplus-solve --json` prints that document.

## The command

`maxplus-solve PUZZLE [--solver NAME] [--mode REGIME] [--time-limit SECONDS] [--max-solutions N|all] [--seed N] [--option NAME=VALUE]... [--validate] [--json]`

`PUZZLE` is an instance file or a fixture id. The solver defaults to `rust.contact_dfs` and the mode to `footprint`. `--option` sets one entry of `SolverConfig.options`; the value is read as JSON where it is JSON (`false`, `1000`) and as a word otherwise (`random`). The summary prints the time to the first solution and, when the search ran to its end, the time that took.

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
| `rust.contact_dfs` | footprint, relief | The corner contact search in Rust, one call per solve. Deterministic unless `order=random`, which uses `seed`. Options below. |
| `cp_sat.placements` | footprint, relief | CP-SAT choosing among the placements the Rust search reaches: one call into Rust for the list, then OR-Tools with one worker and no objective. Needs the `cp-sat` extra. Deterministic for a given OR-Tools version; `seed` is CP-SAT's random seed. `time_limit_s` covers the listing and the choosing together. `no_solution_found` is CP-SAT's `INFEASIBLE` on a whole list: the list holds no assembly. Options below. |

### Options of `rust.contact_dfs`

Every rule the search adds to the prototype's can be switched off, so that its effect can be measured. None of the switches changes what a whole search finds; `tray_rotations` changes how it is counted.

| Option | Default | Meaning |
| --- | --- | --- |
| `node_limit` | none | Stop after that many nodes. |
| `roof_tolerance_mm` | none | The step in height allowed between two roofs along a shared edge. By default it follows the contact noise: that times the steepest roof gradient, and at least the contact noise. Setting it moves the roof tolerance on its own, which changes the candidate set: a result records the option. Ignored in the footprint regime. |
| `tray_rotations` | `once` | `once`: assemblies that are rotations of one another with the tray are one solution. `all`: each is returned, as the prototype does. |
| `anchor` | `true` | Hold one piece to a sector of the tray, so that rotated copies are not searched for at all. Only with `tray_rotations=once`; without it they are found and discarded. |
| `cavity_pruning` | `true` | Abandon a state with a cavity the remaining pieces cannot fill, by area or by width. |
| `closure_pruning` | `true` | Abandon a state with a straight run or a convex corner the remaining pieces cannot close. |
| `lookahead` | `false` | Count a placement towards a corner only if the state it leads to is not a dead end by the pruning rules that are on. Fewer nodes, usually more states examined. |
| `order` | `matched-edges` | The order in which a node's placements are tried: `matched-edges` (most whole edges shared with placed pieces first), `generated` (the prototype's order) or `random` (shuffled, from `seed`). It changes which solution comes first and how soon. |
| `equal_edges` | `true` | Only assuming `edge-to-edge`, an error otherwise: let a piece edge lie against another piece's edge only if the two are equally long and, with roofs, equally high at both ends. |
| `wall_edges` | `true` | Only assuming `edge-to-edge`, an error otherwise: keep an edge that no other piece's edge can lie against on the tray. |

### Options of `cp_sat.placements`

The first seven shape the search that lists the placements and mean what they mean for `rust.contact_dfs`; a rule that is off makes the list longer and never changes what is chosen from it. `coverage` and `targeted_probes` shape the model.

| Option | Default | Meaning |
| --- | --- | --- |
| `node_limit` | none | Stop the listing search after that many nodes. The list is then partial. |
| `roof_tolerance_mm` | none | As for `rust.contact_dfs`. |
| `max_placements` | none | Stop the listing search once that many placements are listed. The list is then partial. |
| `tray_rotations` | `once` | `once`: a choice and its tray rotations are one solution. `all`: each is returned. |
| `anchor` | `true` | List only placements the anchored search reaches, so that rotated copies are mostly not in the list. Without it they are chosen and discarded. |
| `cavity_pruning` | `true` | The listing search's cavity pruning. |
| `closure_pruning` | `true` | The listing search's closure pruning. |
| `coverage` | `true` | State, for each probe point of the target, that some chosen placement reaches it. Implied by the rest of the model, so it excludes nothing; it is what lets CP-SAT see that a partial choice cannot be completed. |
| `targeted_probes` | `false` | Give each overlap the probe grid missed a probe of its own, so that it is stated in a clique instead of as a pair. Far fewer pairs, many more cliques; the same exclusions. |

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
