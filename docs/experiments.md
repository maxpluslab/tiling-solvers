# Experiments

How to run the solvers over the corpus, what is written down for each run, and what the first experiments found. The solvers' own rules and their ablations are in [algorithms.md](algorithms.md); what a result claims is in [solver-contract.md](solver-contract.md).

The question throughout is what makes a puzzle hard and what helps, not how fast a solver is. So the tables below count search effort (nodes, dead ends), and times are kept out of anything committed.

Every number here is relative to the candidates the solvers generate and to `f64` arithmetic with stated tolerances. "One assembly" means one was found by a search that ran to its end over that candidate set, not that uniqueness is proved.

## The command

```sh
uv run maxplus-bench run benchmarks/manifests/corpus.toml --no-times   # run a manifest, print its table
uv run maxplus-bench table benchmarks/results/corpus.jsonl             # the table of a results file again
uv run maxplus-bench proxies --results benchmarks/results/corpus.jsonl # difficulty proxies and rank correlations
```

`run` writes one JSON line per run to `benchmarks/results/<name>.jsonl` (`--out` to choose), prints the table, and with `--table FILE` writes it too. It exits with 1 if any run could not be made. `--no-times` leaves out times and CP-SAT's own counts, which depend on the machine and the OR-Tools build; what is left is reproduced exactly by a deterministic solver.

`benchmarks/results/corpus.md` is the committed table of the corpus manifest: every registered solver on every corpus puzzle it can run. The command above reproduces it, and `tests/corpus/test_benchmark.py` holds that. The `.jsonl` files are not committed.

Needs the `validate` extra for the validity columns and the `cp-sat` extra for `cp_sat.placements`. A run whose solver cannot be loaded is recorded as an error and the rest go on.

## Manifests

A manifest is a TOML file in `benchmarks/manifests/`:

```toml
name = "corpus"
description = "Every registered solver on every corpus puzzle."
fixtures = ["corpus"]          # fixture ids, or the groups "corpus", "synthetic", "all"
validate = true                # check every solution with the independent validator

[[runs]]
solver = "rust.contact_dfs"
mode = "own"                   # "own": the fixture's regime; or "footprint", "relief"
max_solutions = "all"          # or a number
time_limit_s = 60.0            # optional
seeds = [0]
contact_scale = [1.0]          # multiples of the solver's default contact tolerance
fixtures = ["new5-flat"]       # optional: only these of the manifest's fixtures

[runs.options]                 # solver options; a list is a factor to vary
order = ["matched-edges", "random"]
lookahead = false
```

Every list among `mode`, `seeds`, `contact_scale` and the option values is a factor, and a `[[runs]]` block stands for the product of its factors on each fixture. The order is fixed, so a manifest names the same runs in the same order every time. Unknown keys, unknown solvers and unknown fixtures are refused before anything runs.

`contact_scale` multiplies only the contact tolerance the search fits pieces with (`contact_noise_mm`, by default 1e-6 of the span: 0.000144 mm on the corpus). The validator's tolerances are not touched, so a solution found with a wide tolerance is still judged by the browser player's rules. The roof tolerance follows the contact tolerance unless the solver option `roof_tolerance_mm` sets it on its own.

| Manifest | What it runs |
| --- | --- |
| `smoke.toml` | Every solver on the six-piece puzzle, flat and with roofs. A second. |
| `corpus.toml` | Every solver on every corpus puzzle in its own regime; the prototype on the footprints, stopped at 50 000 nodes. Whole searches. |
| `tolerance.toml` | The whole search as the contact tolerance widens from 0.000144 mm to 1.728 mm, and for the relief puzzles a grid of contact tolerance against roof tolerance. |
| `factorial.toml` | Flat against relief × tolerance × heuristic × puzzle: whole searches and first solutions with and without looking ahead, under both fixed orders, and first solutions under five random orders. |

The last two stop a search after 30 s. A stopped search is a result too, but where it stopped depends on the machine.

## Records

One JSON object per line:

| Field | Meaning |
| --- | --- |
| `manifest`, `fixture`, `kind`, `construction`, `pieces`, `fixtureRegime` | What was run on. `construction` is the source's family (`new`, `rat`, `rev`). |
| `solver`, `solverVersion`, `mode`, `contactScale` | Who ran it and in which regime. |
| `config` | The whole `SolverConfig` as run: options, seed, limits and the tolerances after scaling. |
| `instanceHash` | The hash of the instance, as in `SolveResult`. |
| `environment`, `recordedAt` | Platform, Python and package versions; when. |
| `status`, `exhaustive`, `candidateSet`, `candidatesProvenComplete` | The result's claims, as the solver contract defines them. `status = "error"` with `error` for a run that could not be made. |
| `solutions`, `validSolutions`, `worstResiduals` | How many assemblies came back, how many the validator passed, and the largest of each residual over them. `validSolutions` is absent when nothing was validated. |
| `metrics` | The solver's metrics, unchanged. |

The counts in a record are deterministic for a deterministic solver; the times are not. Peak memory is not recorded.

One metric was added for this. `backtrack_depth` is the sum, over dead ends, of how many pieces were placed when the search turned back; divided by `backtracks` it is the mean depth of a dead end. The prototype reports it too and a test holds the two equal.

## The corpus table

[`benchmarks/results/corpus.md`](../benchmarks/results/corpus.md) has all 44 rows. What it shows:

- Both production solvers finish every corpus puzzle but `cor1-flat` and agree on the assemblies; every assembly passes the validator. `cp_sat.placements` shows the search counts of the listing search it starts from, which is `rust.contact_dfs` taking candidates in the order they are generated. A whole search visits the same nodes in any order, so where both finish the counts are the same; stopped at the limit on `cor1-flat` they are not, since the two have gone down different branches by then.
- `cor1-flat`, 27 pieces without their roofs, is stopped at the manifest's node limit of 1 500 000 without an assembly, by both. The limit is there so that the table is the same on any machine; by hand the search was stopped at 3 000 000 nodes, also without one.
- With roofs a whole search takes 26 to 94 nodes, except on `cor1`, built to be hard with its roofs on: 1 529. Without roofs, 45 to 1 064 878 where it ends.
- The footprints have one assembly each, except `rat1-flat` (101) and `rat2-flat` (2).
- The prototype, without tray symmetry or pruning, finishes five of the eight footprints it is given within 50 000 nodes and returns each assembly in the tray's four orientations. It is not given `cor1-flat`.

## Tolerance

`tolerance.toml`, whole searches of `rust.contact_dfs`. The contact tolerance in mm is the scale times 0.000144; the browser player forgives 0.864 mm of overlap. Nodes, footprints (a dash: stopped at 30 s on the machine that ran it):

| Fixture | 0.000144 | 0.00144 | 0.0144 | 0.144 | 0.432 | 0.864 | 1.728 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `rev2-flat` | 45 | 45 | 45 | 45 | 45 | 47 | 50 |
| `new5-flat` | 90 | 90 | 90 | 124 | 159 | 167 | 184 |
| `new4-flat` | 510 | 1 273 | 2 212 | 2 671 | 3 042 | 3 213 | 1 851 |
| `new3-flat` | 6 104 | 6 293 | 7 500 | 8 940 | 9 032 | 9 167 | 9 827 |
| `rat1-flat` | 17 425 | 18 243 | 25 988 | 37 288 | 38 192 | 38 981 | 68 297 |
| `rat2-flat` | 128 230 | 221 345 | 286 401 | 319 172 | 354 232 | 482 201 | – |
| `new2-flat` | 909 750 | 1 037 559 | – | – | – | – | – |
| `new1-flat` | 1 064 878 | 1 070 981 | 1 126 132 | – | – | – | – |

With roofs, the same sweep:

| Fixture | 0.000144 to 0.144 | 0.432 | 0.864 | 1.728 |
| --- | --- | --- | --- | --- |
| `rev2`, `new5` | 26 | 26 | 26 | 26 |
| `new3` | 44 | 44 | 44 | 51 |
| `new4` | 45, 46 at 0.144 | 50 | 50 | 52 |
| `new1` | 68 | 69 | 80 | 94 |
| `new2` | 68 | 68 | 70 | 89 |
| `rat1` | 90 | 90 | 104 | 104 |
| `rat2` | 94 | 94 | 97 | 114 |

And the roof tolerance on its own, at the default contact tolerance (the player forgives a step of 1.75 mm):

| Fixture | 0.01 mm | 0.1 | 0.5 | 1.75 | 5.0 |
| --- | --- | --- | --- | --- | --- |
| `rev2` | 26 | 26 | 26 | 26 | 26 |
| `new5` | 26 | 26 | 26 | 26 | 29 |
| `new3` | 44 | 44 | 44 | 51 | 77 |
| `new4` | 45 | 45 | 50 | 52 | 62 |
| `new1` | 68 | 68 | 69 | 94 | 129 |
| `new2` | 68 | 68 | 69 | 86 | 123 |
| `rat1` | 90 | 90 | 104 | 104 | 149 |
| `rat2` | 94 | 94 | 94 | 122 | 174 |

What it shows:

- **No transition.** Nowhere between numerical noise and twice the player's tolerance does a puzzle change character. The cost of a footprint search grows smoothly, by a factor of 1.1 (`rev2-flat`) to about 4 (`rat1-flat`, `rat2-flat`) and 6 (`new4-flat`) over nearly four orders of magnitude of tolerance. The geometric spacing was meant to find a threshold; there is none in this range to space around.
- **No ambiguity appears.** Every search that finished found the same number of assemblies at every tolerance: one, or 101 for `rat1-flat`, or 2 for `rat2-flat`. All pass the validator. Widening the tolerance lets more wrong placements in, and they all still fail to complete.
- **The roofs do not weaken.** With a roof tolerance of 5 mm, nearly three times what the player forgives and a tenth of the relief on some puzzles, every relief puzzle still has one assembly, found in at most 174 nodes, and its roofs meet to within 1e-13 mm. The roof tolerance decides how many wrong neighbours are tried, not which assembly is found.
- **The two tolerances do not interact.** In the grid of contact against roof tolerance the node count depends on the roof tolerance and, to within two nodes, not on the contact tolerance.
- **A wide tolerance finds looser assemblies.** From 0.432 mm one of the 101 assemblies `rat1-flat` returns leaves 11 mm² uncovered, and at 1.728 mm `new4-flat` returns one with 155 mm² uncovered and 66 mm² outside the tray. Both pass the validator, whose area allowance on these puzzles is 249 mm². That is also why `new4-flat` gets cheaper at the last step: it is a different tree.
- **The 16-piece footprints are at the edge.** They finish within 30 s only at the tightest tolerances, so what widening does to them is not measured here.

## Flat against relief, tolerance, heuristic, puzzle

`factorial.toml`, `rust.contact_dfs`, 368 runs. Every assembly returned passes the validator. Contact tolerances are 0.000144, 0.144 and 0.864 mm. A dash is a search stopped at 30 s.

Nodes of the whole search, without and with `lookahead`:

| Fixture | 0.000144 | with lookahead | 0.144 | with lookahead | 0.864 | with lookahead |
| --- | --- | --- | --- | --- | --- | --- |
| `rev2-flat` | 45 | 12 | 45 | 12 | 47 | 18 |
| `new5-flat` | 90 | 16 | 124 | 43 | 167 | 130 |
| `new4-flat` | 510 | 35 | 2 671 | 578 | 3 213 | 1 221 |
| `new3-flat` | 6 104 | 453 | 8 940 | 1 825 | 9 167 | 2 922 |
| `rat1-flat` | 17 425 | 845 | 37 288 | 7 396 | 38 981 | 15 110 |
| `rat2-flat` | 128 230 | 2 131 | 319 172 | 48 695 | 482 201 | 79 000 |
| `new2-flat` | 909 750 | 22 979 | – | – | – | – |
| `new1-flat` | 1 064 878 | – | – | – | – | – |
| `rev2` | 26 | 12 | 26 | 12 | 26 | 14 |
| `new5` | 26 | 20 | 26 | 24 | 26 | 26 |
| `new3` | 44 | 36 | 44 | 36 | 44 | 36 |
| `new4` | 45 | 29 | 46 | 31 | 50 | 33 |
| `new1` | 68 | 52 | 68 | 52 | 80 | 63 |
| `new2` | 68 | 50 | 68 | 50 | 70 | 52 |
| `rat1` | 90 | 53 | 90 | 56 | 104 | 64 |
| `rat2` | 94 | 75 | 94 | 75 | 97 | 80 |

Nodes to the first assembly, in the order `matched-edges`, without and with `lookahead`:

| Fixture | 0.000144 | with lookahead | 0.144 | with lookahead | 0.864 | with lookahead |
| --- | --- | --- | --- | --- | --- | --- |
| `rev2-flat` | 30 | 11 | 30 | 11 | 32 | 16 |
| `new5-flat` | 55 | 13 | 70 | 26 | 88 | 78 |
| `new3-flat` | 135 | 10 | 157 | 10 | 161 | 10 |
| `rat1-flat` | 334 | 35 | 799 | 159 | 849 | 138 |
| `new4-flat` | 377 | 32 | 2 196 | 435 | 2 630 | 841 |
| `rat2-flat` | 5 555 | 233 | 24 450 | 6 258 | 33 260 | 8 672 |
| `new2-flat` | 392 912 | 11 332 | 534 389 | 45 694 | 601 857 | 50 373 |
| `new1-flat` | 803 543 | – | – | – | – | – |

With roofs the first assembly takes 10 to 93 nodes without looking ahead and 10 to 79 with, and the tolerance moves that by at most four nodes.

Nodes to the first assembly under `order = "random"`, seeds 0 to 4, at the default tolerance:

| Fixture | Least | Median | Most | `matched-edges` |
| --- | --- | --- | --- | --- |
| `rev2-flat` | 13 | 31 | 40 | 30 |
| `new5-flat` | 24 | 46 | 90 | 55 |
| `new4-flat` | 73 | 358 | 485 | 377 |
| `rat1-flat` | 167 | 642 | 1 887 | 334 |
| `new3-flat` | 1 862 | 3 044 | 5 826 | 135 |
| `rat2-flat` | 15 584 | 50 253 | 69 562 | 5 555 |
| `new1-flat` | 98 078 | 276 368 | 955 946 | 803 543 |
| `new2-flat` | 473 425 | 644 074 | 889 623 | 392 912 |
| relief, all eight | 12 | 16 to 58 | 67 | 10 to 93 |

What it shows:

- **Roofs are the factor.** Nothing else in the experiment moves the cost by more than a hundredfold; the roofs move it by more than ten thousandfold on the 16-piece puzzles, on the same polygons. Tolerance, order, luck and looking ahead are all small beside it, and with roofs they hardly matter at all.
- **The expected opposition is not there.** The roadmap expected the time to a first assembly to fall and the time to exhaust to rise as the tolerance widens. Both rise, on every footprint, and by similar factors: `rat2-flat` goes from 5 555 to 33 260 nodes for the first assembly and from 128 230 to 482 201 for the whole search. A wider tolerance admits more wrong placements and no new assemblies, so there is nothing to find sooner. The expectation would hold for puzzles that gain assemblies as the tolerance widens; within the player's tolerance these do not.
- **Looking ahead cuts the tree and pays for it per node.** At the default tolerance it cuts a footprint's whole search by 4 to 60 times in nodes. But `new1-flat` finishes in 30 s without it and not with it: each node costs more than the cut saves. Its cut also shrinks as the tolerance widens, from 20 times to 2.6 on `rat1-flat` and from 5.6 to 1.3 on `new5-flat`, because a wide tolerance leaves fewer corners with no candidate. This is the count behind the switch being off by default; [algorithms.md](algorithms.md) has it with times.
- **The two fixed orders are the same order,** to within a few per cent of nodes everywhere. Ordering candidates by how well their edges match adds nothing to the order they are generated in.
- **Luck is worth about a factor of ten.** Across five random orders the cost of a first footprint assembly spreads by 2 to 11 times. The fixed order is far better than chance on `new3-flat` and `rat2-flat`, a little better on `new2-flat`, worse than the median on `new1-flat`, and otherwise inside the spread. No order tried here is reliably good.
- **For the hardest puzzles, finding is most of proving.** `new1-flat` takes 803 543 nodes to its one assembly and 1 064 878 to show there is no other. On `new3-flat` it is 135 against 6 104. How long the first assembly takes says little about how long the whole search does.
- **Ambiguity is rare and does not make a puzzle easy.** Six of eight footprints have one assembly at every tolerance. `rat1-flat` has 101 and still takes 334 nodes to find one.

The stopped searches make these tables machine-dependent at the 16-piece footprints, so they are not committed as files. The finished rows are reproduced by the manifest.

## Difficulty proxies

`maxplus-bench proxies` reads these off each corpus instance without searching it: for every piece edge, how many edges of other pieces it could lie against (its degree in the edge compatibility graph of [algorithms.md](algorithms.md#the-edge-compatibility-graph), with roofs taken into account in relief); the fraction of edges with exactly one mate, and with none; and the number of symmetries (exchanges of congruent pieces, turns of a piece onto itself, turns of the tray). With `--results` it adds, from the whole searches in a results file, the mean depth of a dead end and the candidates generated per node, and the rank correlation of everything with the node count.

| Fixture | Pieces | Edges | Mean degree | Unique mate | Symmetries | Source diversity | Source rating | Nodes | Mean dead-end depth | Candidates per node |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `new5` | 6 | 28 | 2.29 | 0.071 | 4 | 4.47 | 1 | 26 | 1.19 | 37.8 |
| `rev2` | 9 | 47 | 1.19 | 0.766 | 4 | 5.10 | 2 | 26 | 1.23 | 18.5 |
| `new3` | 9 | 44 | 4.18 | 0.045 | 4 | 5.68 | 2 | 44 | 1.26 | 65.8 |
| `new4` | 9 | 44 | 4.14 | 0.091 | 4 | 3.50 | 3 | 45 | 1.35 | 54.6 |
| `new1` | 16 | 82 | 5.59 | 0.122 | 4 | 5.45 | 4 | 68 | 1.19 | 106 |
| `new2` | 16 | 82 | 5.63 | 0.098 | 4 | 4.50 | 5 | 68 | 1.19 | 98.4 |
| `rat1` | 11 | 47 | 6.55 | 0.128 | 8 | 4.89 | 3 | 90 | 1.90 | 72.2 |
| `rat2` | 20 | 89 | 6.67 | 0.157 | 4 | 5.71 | 5 | 94 | 1.49 | 118 |
| `rev2-flat` | 9 | 47 | 41.7 | 0 | 4 | 4.48 | 3 | 45 | 2.72 | 26.1 |
| `new5-flat` | 6 | 28 | 23.1 | 0 | 16 | 4.19 | 1 | 90 | 2.13 | 10.8 |
| `new4-flat` | 9 | 44 | 39.0 | 0 | 32 | 3.94 | 3 | 510 | 2.88 | 9.1 |
| `new3-flat` | 9 | 44 | 38.8 | 0 | 64 | 6.63 | 1 | 6 104 | 4.14 | 12.4 |
| `rat1-flat` | 11 | 47 | 42.7 | 0 | 256 | 4.54 | 3 | 17 425 | 5.29 | 21.7 |
| `rat2-flat` | 20 | 89 | 84.4 | 0 | 16 | 6.06 | 4 | 128 230 | 6.00 | 50.0 |
| `new2-flat` | 16 | 82 | 76.7 | 0 | 128 | 4.78 | 4 | 909 750 | 5.72 | 22.0 |
| `new1-flat` | 16 | 82 | 76.7 | 0 | 256 | 6.43 | 3 | 1 064 878 | 6.03 | 32.5 |

The source's numbers are the Leinster–Cobbold diversity of the pieces' intrinsic volumes and the one-to-five rating it derives from it, copied into `benchmarks/fixtures/index.json` by the importer. The source reads lower diversity as harder.

Spearman rank correlation with the nodes of the whole search, within each regime, eight puzzles in each:

| Proxy | Footprint | Relief |
| --- | --- | --- |
| Mean dead-end depth | +0.95 | +0.39 |
| Pieces | +0.85 | +0.88 |
| Mean degree | +0.74 | +0.96 |
| Largest degree | +0.73 | +0.99 |
| Edges | +0.73 | +0.75 |
| Symmetries | +0.73 | +0.42 |
| Source diversity | +0.64 | +0.36 |
| Source rating | +0.54 | +0.85 |
| Candidates per node | +0.52 | +0.89 |
| Unique-mate fraction | (constant) | +0.37 |

What it shows, with eight points behind each coefficient:

- **Degree is the regime.** Without roofs a piece edge can lie against nearly every other edge (mean degree 77 of 82 on `new1-flat`) and no edge has a unique mate. With roofs the mean degree is 1.2 to 6.7. That one number separates the two regimes completely, and within relief it ranks the puzzles almost exactly. Roofs make a puzzle easy by saying which edges can meet.
- **Without roofs, size and depth.** The number of pieces ranks the footprints as well as anything static does, and what tracks the cost best is how deep the dead ends are, which is known only after searching. The static proxies do not see why `new3-flat` costs twelve times `new4-flat` with the same number of pieces and edges and the same mean degree. Its symmetry count is twice as large; that is one data point.
- **The source's rating is about people.** It ranks the relief puzzles much as the search does (+0.85) and the footprints less well (+0.54). Its diversity runs the wrong way for a search: the source reads lower diversity as harder, and here higher diversity goes with more nodes, weakly. The rating is designed for a person matching walls, not for this search, and the corpus is too small to say more.
- **`rev2` is the outlier that explains the rest.** Three quarters of its edges have exactly one mate, its mean degree is 1.19, and it is the cheapest puzzle in both regimes although it has nine pieces.

Correlations are taken within a regime only. Across both, any number that differs between footprints and reliefs correlates with the cost, because the roofs change the cost a thousandfold.

## Edge to edge

`maxplus-bench run benchmarks/manifests/edge_to_edge.toml --no-times` reproduces `benchmarks/results/edge_to_edge.md`: every corpus puzzle in its own regime, assuming nothing and assuming that the pieces meet edge to edge, with the assumption's two rules crossed. A manifest says `assume = "edge-to-edge"`, or a list with `"none"` to cross it with the other factors; the table then shows an `assumes` column on every row. What the numbers say is in [algorithms.md](algorithms.md#assuming-the-pieces-meet-edge-to-edge): the footprints that took up to a million nodes take 14 to 80, fewer than their relief twins took assuming nothing, and of `rat1-flat`'s 101 assemblies and `rat2-flat`'s 2 only the answer has no T. `cor1` stays hard under it: 967 nodes with its roofs, and 44 539 and 48 assemblies without them, where the search that assumes nothing does not end.

`proxies.static(instance, edge_to_edge=True)` gives the edge-graph proxies under the assumption: mean degree 0.8 to 2.4 on the footprints, against 23 to 84 without it.

## Figures and the notebook

`maxplus_solvers.experiments.plotting` draws from records: `nodes_by_tolerance` (whole-search nodes against the contact tolerance, a line per fixture) and `proxy_against_cost` (one proxy against the nodes, a point per fixture). It needs the `analysis` extra and is the only module that imports matplotlib. `notebooks/first-look.ipynb` runs a manifest, prints its table and the proxies and draws both; a test runs it from top to bottom.

## What this leaves open

- The corpus is 18 puzzles from four kinds of construction. Every statement about what predicts difficulty rests on nine points a regime, and the proxy correlations above were measured on eight, before `cor1` joined. Generated families of graded size are the next thing these tools should be pointed at.
- Assuming nothing, the 16-piece footprints are where the search is hard, and they sit at the time limit; `cor1-flat` does not finish at all. Remembering dead ends is the lead from phase 6; the manifests here are what to measure it with.
- Nothing here measures a person. In the hand these puzzles are simple with wall matching, which is the unique-mate structure above; the footprint regime removes exactly that.
