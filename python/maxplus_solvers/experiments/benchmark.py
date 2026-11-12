"""The benchmark runner: a manifest in, one JSON line per run out.

Each line says what was run and what came of it, with everything needed to run
it again: the solver and its version, the hash of the instance, the seed, the
tolerances and the whole configuration. The counts in a line are deterministic
for a deterministic solver; the times are not.

A run that cannot be made, a mode the solver does not offer or an extra that
is not installed, is recorded as ``status = "error"`` with the reason, and the
experiment goes on. A run that is not asked for because the fixture has no
such regime (``mode = "relief"`` on a footprint puzzle) is left out.
"""

import json
import platform
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maxplus_solvers.api import solve
from maxplus_solvers.experiments.manifest import (
    NOTHING,
    OWN,
    Manifest,
    Run,
    expand,
    fixture_ids,
)
from maxplus_solvers.io.instance import load_instance
from maxplus_solvers.models import (
    Assumption,
    PuzzleInstance,
    Regime,
    SolverConfig,
    TolerancePolicy,
)

FORMAT_VERSION = 1
# Regimes from least to most information. A puzzle can be solved in its own or a lower one.
_ORDER = (Regime.FOOTPRINT, Regime.RELIEF, Regime.TROPICAL_AWARE)


def read_index(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "index.json").read_text(encoding="utf-8"))


def _environment() -> dict[str, str]:
    return {"python": platform.python_version(), "platform": sys.platform}


def _mode(run: Run, instance: PuzzleInstance) -> Regime | None:
    """The regime a run asks for on this instance, or ``None`` if the instance lacks it."""
    if run.mode == OWN:
        return instance.regime
    mode = Regime(run.mode)
    return mode if _ORDER.index(mode) <= _ORDER.index(instance.regime) else None


def _tolerances(instance: PuzzleInstance, scale: float) -> TolerancePolicy:
    """The browser player's tolerances with the contact noise scaled.

    The contact noise is what the solvers fit pieces to. The validator's own
    thresholds are left alone, so that ``valid`` always means valid by the
    player's rules, however loosely the search was allowed to fit.
    """
    policy = TolerancePolicy.from_instance(instance)
    return replace(policy, contact_noise_mm=policy.contact_noise_mm * scale)


def _worst(solutions: Iterable[Any]) -> dict[str, float]:
    """The largest of each residual over the solutions that were validated."""
    worst: dict[str, float] = {}
    for solution in solutions:
        for name, value in (solution.residuals or {}).items():
            worst[name] = max(worst.get(name, 0.0), value)
    return worst


def run_one(
    run: Run, instance: PuzzleInstance, entry: Mapping[str, Any], *, validate: bool
) -> dict[str, Any] | None:
    """One run as a record, or ``None`` if the instance has no such regime."""
    mode = _mode(run, instance)
    if mode is None:
        return None
    seen = instance.as_regime(mode)
    tolerances = _tolerances(seen, run.contact_scale)
    config = SolverConfig(
        solver=run.solver,
        mode=mode,
        time_limit_s=run.time_limit_s,
        max_solutions=run.max_solutions,
        seed=run.seed,
        tolerances=tolerances,
        options=dict(run.options),
        assumptions=() if run.assume == NOTHING else (Assumption(run.assume),),
    )
    record: dict[str, Any] = {
        "formatVersion": FORMAT_VERSION,
        "fixture": run.fixture,
        "kind": entry["kind"],
        "construction": entry.get("construction"),
        "pieces": len(instance.pieces),
        "fixtureRegime": instance.regime.value,
        "solver": run.solver,
        "mode": mode.value,
        "contactScale": run.contact_scale,
        "config": config.to_dict(),
        "instanceHash": seen.instance_hash(),
        "environment": _environment(),
        "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        result = solve(instance, config, validate=validate)
    except (ValueError, ImportError) as error:
        record.update(status="error", error=f"{type(error).__name__}: {error}")
        return record
    validated = [solution for solution in result.solutions if solution.valid is not None]
    record.update(
        status=result.status.value,
        solverVersion=result.solver_version,
        exhaustive=result.exhaustive,
        candidateSet=result.candidate_set,
        candidatesProvenComplete=result.candidates_proven_complete,
        solutions=len(result.solutions),
        # Absent when nothing was validated: not the same as none valid.
        validSolutions=sum(s.valid is True for s in validated) if validate else None,
        worstResiduals=_worst(validated),
        metrics=dict(result.metrics),
    )
    return record


def records(
    manifest: Manifest,
    fixtures_dir: Path,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Run a manifest, yielding each record as its run finishes."""
    index = read_index(fixtures_dir)
    entries = {entry["id"]: entry for entry in index["fixtures"]}
    instances: dict[str, PuzzleInstance] = {}
    for run in expand(manifest, fixture_ids(manifest, index)):
        if run.fixture not in instances:
            instances[run.fixture] = load_instance(fixtures_dir / f"{run.fixture}.json")
        record = run_one(
            run, instances[run.fixture], entries[run.fixture], validate=manifest.validate
        )
        if record is None:
            continue
        record = {"manifest": manifest.name, **record}
        if progress is not None:
            progress(record)
        yield record


def run(
    manifest: Manifest,
    fixtures_dir: Path,
    out: Path | None = None,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run a manifest. With ``out``, write the records there as JSON lines as they come."""
    found = []
    handle = None if out is None else out.open("w", encoding="utf-8", newline="\n")
    try:
        for record in records(manifest, fixtures_dir, progress=progress):
            found.append(record)
            if handle is not None:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
    finally:
        if handle is not None:
            handle.close()
    return found


def read(path: Path) -> list[dict[str, Any]]:
    """The records of a results file."""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
