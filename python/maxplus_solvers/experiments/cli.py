"""``maxplus-bench``: run an experiment manifest, and print tables from its results.

``maxplus-bench run MANIFEST`` runs every run the manifest names, writes one
JSON line per run and prints the results table. ``maxplus-bench table FILE``
prints the table of a results file again. ``maxplus-bench proxies`` prints the
difficulty proxies of the corpus beside the source's rating.
"""

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from maxplus_solvers.experiments import benchmark, proxies, report
from maxplus_solvers.experiments.manifest import ManifestError, load
from maxplus_solvers.io.instance import load_instance

DEFAULT_FIXTURES = Path("benchmarks") / "fixtures"
DEFAULT_RESULTS = Path("benchmarks") / "results"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maxplus-bench", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a manifest and print its results table")
    run.add_argument("manifest", type=Path, help="a manifest file, benchmarks/manifests/*.toml")
    run.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES, help="fixture directory")
    run.add_argument(
        "--out",
        type=Path,
        help="where to write the JSON lines (default: benchmarks/results/<name>.jsonl)",
    )
    run.add_argument("--table", type=Path, help="also write the table to this file")
    run.add_argument(
        "--no-times",
        action="store_true",
        help="leave out times and other machine-dependent columns: the reproducible table",
    )
    run.add_argument("--quiet", action="store_true", help="do not report each run as it ends")

    table = commands.add_parser("table", help="print the table of a results file")
    table.add_argument("results", type=Path, help="a results file written by 'run'")
    table.add_argument("--no-times", action="store_true")

    prox = commands.add_parser("proxies", help="difficulty proxies of the corpus")
    prox.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    prox.add_argument(
        "--results",
        type=Path,
        help="a results file: adds what its whole searches cost, and rank correlations",
    )
    prox.add_argument(
        "--solver", default="rust.contact_dfs", help="whose records to read from --results"
    )
    return parser


def _progress(record: Mapping[str, Any]) -> None:
    options = record["config"]["options"]
    setting = " ".join(f"{name}={value}" for name, value in sorted(options.items()))
    if record["status"] == "error":
        outcome = record["error"]
    else:
        seconds = record["metrics"].get("wall_time_s", 0.0)
        outcome = f"{record['status']}, {record['solutions']} solutions, {seconds:.3g} s"
    print(
        f"{record['fixture']} {record['solver']} {record['mode']} {setting}: {outcome}",
        file=sys.stderr,
        flush=True,
    )


def proxy_table(
    fixtures_dir: Path, records: Sequence[Mapping[str, Any]] = (), solver: str = "rust.contact_dfs"
) -> tuple[str, str]:
    """The proxies of every corpus fixture as a Markdown table, and their rank correlations.

    With ``records``, the whole searches of ``solver`` found there (each fixture
    in its own regime, the first such record) add the dynamic proxies and the
    node count, and the correlations are with that node count; without, with
    the source's diversity. Correlations are taken within each regime.
    """
    index = benchmark.read_index(fixtures_dir)
    searched = {}
    for record in records:
        if (
            record["solver"] == solver
            and record["status"] != "error"
            and record["exhaustive"]
            and record["mode"] == record["fixtureRegime"]
        ):
            searched.setdefault(record["fixture"], record)
    numbers: dict[str, dict[str, float]] = {}
    regimes: dict[str, str] = {}
    for entry in index["fixtures"]:
        if entry["kind"] != "corpus":
            continue
        instance = load_instance(fixtures_dir / f"{entry['id']}.json")
        row = proxies.static(instance).to_dict()
        row["source_diversity"] = entry["sourceDifficulty"]["diversity"]
        row["source_rating"] = entry["sourceDifficulty"]["rating"]
        if entry["id"] in searched:
            row.update(proxies.dynamic(searched[entry["id"]]))
        numbers[entry["id"]] = row
        regimes[entry["id"]] = entry["regime"]
    columns = [
        ("pieces", "Pieces"),
        ("edges", "Edges"),
        ("mean_degree", "Mean degree"),
        ("unique_mate_fraction", "Unique mate"),
        ("no_mate_fraction", "No mate"),
        ("symmetry_count", "Symmetries"),
        ("source_diversity", "Source diversity"),
        ("source_rating", "Source rating"),
        ("nodes", "Nodes"),
        ("mean_dead_end_depth", "Mean dead-end depth"),
        ("candidates_per_node", "Candidates per node"),
    ]
    present = [(name, title) for name, title in columns if any(name in r for r in numbers.values())]

    def cell(value: float | None) -> str:
        if value is None:
            return ""
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", " ")
        return f"{value:.3g}"

    cells = [["Fixture", *(title for _, title in present)]]
    for fixture, row in numbers.items():
        cells.append([f"`{fixture}`", *(cell(row.get(name)) for name, _ in present)])
    # Within a regime only. Across both, any number that differs between footprints and
    # reliefs correlates with the cost, because the roofs change the cost a thousandfold.
    against = "nodes" if searched else "source_diversity"
    by_regime = {
        regime: proxies.correlations(
            {fixture: row for fixture, row in numbers.items() if regimes[fixture] == regime},
            against,
        )
        for regime in ("footprint", "relief")
    }
    found = [["Proxy", f"Spearman with {against}: footprint", "relief", "Fixtures in each"]]
    for flat, roofed in zip(by_regime["footprint"], by_regime["relief"], strict=True):
        found.append(
            [
                flat[0],
                "" if flat[1] is None else f"{flat[1]:+.2f}",
                "" if roofed[1] is None else f"{roofed[1]:+.2f}",
                f"{flat[2]}, {roofed[2]}",
            ]
        )
    return report.markdown(cells), report.markdown(found)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            manifest = load(args.manifest)
            out = args.out or DEFAULT_RESULTS / f"{manifest.name}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            records = benchmark.run(
                manifest, args.fixtures, out, progress=None if args.quiet else _progress
            )
            text = report.table(records, times=not args.no_times)
            if args.table is not None:
                args.table.parent.mkdir(parents=True, exist_ok=True)
                args.table.write_text(text, encoding="utf-8", newline="\n")
            print(text, end="")
            return 1 if any(record["status"] == "error" for record in records) else 0
        if args.command == "table":
            print(report.table(benchmark.read(args.results), times=not args.no_times), end="")
            return 0
        records = benchmark.read(args.results) if args.results else []
        table, correlations = proxy_table(args.fixtures, records, args.solver)
        print(table)
        print(correlations, end="")
        return 0
    except (ManifestError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
