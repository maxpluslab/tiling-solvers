"""Experiment manifests: which fixtures, which solvers, which settings to vary.

A manifest is a TOML file::

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
    contact_scale = [1.0]          # multiples of the browser player's contact noise
    fixtures = ["new5-flat"]       # optional: only these of the manifest's fixtures

    [runs.options]                 # solver options; a list is a factor to vary
    order = ["matched-edges", "random"]
    lookahead = false

Every list among ``mode``, ``seeds``, ``contact_scale`` and the option values
is a factor, and a ``[[runs]]`` block stands for the product of its factors on
each fixture. The order of the product is fixed, so a manifest names the same
runs in the same order every time.
"""

import itertools
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maxplus_solvers import solvers
from maxplus_solvers.models import Regime

GROUPS = ("corpus", "synthetic", "all")
OWN = "own"
_RUN_KEYS = {
    "solver",
    "mode",
    "max_solutions",
    "time_limit_s",
    "seeds",
    "contact_scale",
    "fixtures",
    "options",
}
_TOP_KEYS = {"name", "description", "fixtures", "validate", "runs"}


class ManifestError(ValueError):
    """A manifest that cannot be run as written."""


@dataclass(frozen=True, slots=True)
class RunBlock:
    """One ``[[runs]]`` block: a solver and the factors to vary for it."""

    solver: str
    modes: tuple[str, ...] = (OWN,)
    max_solutions: int | None = None
    time_limit_s: float | None = None
    seeds: tuple[int, ...] = (0,)
    contact_scales: tuple[float, ...] = (1.0,)
    # Restricts the manifest's fixtures; empty means all of them.
    fixtures: tuple[str, ...] = ()
    # Option name -> the values to try, in order. A fixed option has one value.
    options: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Manifest:
    name: str
    description: str
    fixtures: tuple[str, ...]
    validate: bool
    runs: tuple[RunBlock, ...]


@dataclass(frozen=True, slots=True)
class Run:
    """One solve: a fixture, a solver and one value of every factor."""

    fixture: str
    solver: str
    # A regime, or "own" for the fixture's.
    mode: str
    max_solutions: int | None
    time_limit_s: float | None
    seed: int
    contact_scale: float
    options: Mapping[str, Any]


def _listed(value: Any, where: str) -> tuple[Any, ...]:
    values = tuple(value) if isinstance(value, list) else (value,)
    if not values:
        raise ManifestError(f"{where}: an empty list leaves nothing to run")
    return values


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ManifestError(f"{where}: expected a positive number, got {value!r}")
    return float(value)


def _block(data: Any, where: str) -> RunBlock:
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: expected a table")
    unknown = sorted(set(data) - _RUN_KEYS)
    if unknown:
        raise ManifestError(f"{where}: unknown keys {', '.join(unknown)}")
    solver = data.get("solver")
    if solver not in solvers.available():
        known = ", ".join(solvers.available())
        raise ManifestError(f"{where}: solver {solver!r} is not registered; there are {known}")
    modes = tuple(str(mode) for mode in _listed(data.get("mode", OWN), f"{where}.mode"))
    for mode in modes:
        if mode != OWN and mode not in {regime.value for regime in Regime}:
            raise ManifestError(f"{where}.mode: {mode!r} is neither 'own' nor a regime")
    limit = data.get("max_solutions", "all")
    if limit == "all":
        max_solutions = None
    elif isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1:
        max_solutions = limit
    else:
        raise ManifestError(f"{where}.max_solutions: expected a positive integer or 'all'")
    time_limit = data.get("time_limit_s")
    if time_limit is not None:
        time_limit = _number(time_limit, f"{where}.time_limit_s")
    seeds = _listed(data.get("seeds", [0]), f"{where}.seeds")
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ManifestError(f"{where}.seeds: {seed!r} is not a seed")
    scales = tuple(
        _number(scale, f"{where}.contact_scale")
        for scale in _listed(data.get("contact_scale", [1.0]), f"{where}.contact_scale")
    )
    options = data.get("options", {})
    if not isinstance(options, dict):
        raise ManifestError(f"{where}.options: expected a table")
    only = data.get("fixtures", [])
    if not isinstance(only, list) or not all(isinstance(name, str) for name in only):
        raise ManifestError(f"{where}.fixtures: expected a list of fixture ids")
    return RunBlock(
        solver=solver,
        modes=modes,
        max_solutions=max_solutions,
        time_limit_s=time_limit,
        seeds=tuple(seeds),
        contact_scales=scales,
        fixtures=tuple(only),
        options={
            name: _listed(value, f"{where}.options.{name}") for name, value in options.items()
        },
    )


def parse(data: Mapping[str, Any]) -> Manifest:
    """A manifest from its parsed TOML. Refuses what it does not understand."""
    unknown = sorted(set(data) - _TOP_KEYS)
    if unknown:
        raise ManifestError(f"unknown keys {', '.join(unknown)}")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ManifestError("name: a manifest needs a name")
    fixtures = data.get("fixtures")
    if (
        not isinstance(fixtures, list)
        or not fixtures
        or not all(isinstance(entry, str) for entry in fixtures)
    ):
        raise ManifestError("fixtures: expected a list of fixture ids or groups")
    validate = data.get("validate", True)
    if not isinstance(validate, bool):
        raise ManifestError("validate: expected true or false")
    blocks = data.get("runs")
    if not isinstance(blocks, list) or not blocks:
        raise ManifestError("runs: a manifest needs at least one [[runs]] block")
    return Manifest(
        name=name,
        description=str(data.get("description", "")),
        fixtures=tuple(fixtures),
        validate=validate,
        runs=tuple(_block(block, f"runs[{index}]") for index, block in enumerate(blocks)),
    )


def load(path: Path) -> Manifest:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(f"{path}: {error}") from error
    try:
        return parse(data)
    except ManifestError as error:
        raise ManifestError(f"{path}: {error}") from None


def fixture_ids(manifest: Manifest, index: Mapping[str, Any]) -> list[str]:
    """The fixtures a manifest names, groups expanded, in the order of the fixture index."""
    known = {entry["id"]: entry["kind"] for entry in index["fixtures"]}
    wanted: set[str] = set()
    for name in manifest.fixtures:
        if name in GROUPS:
            wanted.update(fixture for fixture, kind in known.items() if name in ("all", kind))
        elif name in known:
            wanted.add(name)
        else:
            raise ManifestError(f"fixtures: {name!r} is neither a fixture id nor a group")
    for block in manifest.runs:
        for name in block.fixtures:
            if name not in known:
                raise ManifestError(f"runs: {name!r} is not a fixture id")
    return [fixture for fixture in known if fixture in wanted]


def expand(manifest: Manifest, fixtures: Sequence[str]) -> Iterator[Run]:
    """Every run of the manifest, in a fixed order: block, fixture, then the factors."""
    for block in manifest.runs:
        names = list(block.options)
        for fixture in fixtures:
            if block.fixtures and fixture not in block.fixtures:
                continue
            settings = itertools.product(*(block.options[name] for name in names))
            for mode, scale, seed, values in itertools.product(
                block.modes, block.contact_scales, block.seeds, list(settings)
            ):
                yield Run(
                    fixture=fixture,
                    solver=block.solver,
                    mode=mode,
                    max_solutions=block.max_solutions,
                    time_limit_s=block.time_limit_s,
                    seed=seed,
                    contact_scale=scale,
                    options=dict(zip(names, values, strict=True)),
                )
