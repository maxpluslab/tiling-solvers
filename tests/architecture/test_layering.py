"""Invariants of the repository itself, from CLAUDE.md. They fail when the structure is broken."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from maxplus_solvers import _native
from support import corpus

ROOT = corpus.ROOT
PACKAGE = ROOT / "python" / "maxplus_solvers"
CRATES = ROOT / "crates"

# core <- geometry <- search <- py
ALLOWED_CRATE_DEPENDENCIES = {
    "tiling-core": set(),
    "tiling-geometry": {"tiling-core"},
    "tiling-search": {"tiling-core", "tiling-geometry"},
    "tiling-py": {"tiling-core", "tiling-geometry", "tiling-search"},
}

# Top-level modules that only an optional extra provides, and the one place each may be imported.
OPTIONAL_IMPORTS = {
    "shapely": "validation.py",
    "ortools": "solvers/cp_sat.py",
    "polars": "experiments/",
    "matplotlib": "experiments/",
    "numpy": "experiments/",
}


def package_sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def in_package_imports(path: Path) -> set[Path]:
    """Files of the package that ``path`` imports directly."""
    found: set[Path] = set()
    for module in imported_modules(path):
        parts = module.split(".")
        if parts[0] != "maxplus_solvers":
            continue
        for depth in range(len(parts), 1, -1):
            base = PACKAGE.joinpath(*parts[1:depth])
            for candidate in (
                base.with_suffix(".py"),
                base.with_suffix(".pyi"),
                base / "__init__.py",
            ):
                if candidate.is_file():
                    found.add(candidate)
    return found


def test_the_validator_is_independent_of_the_rust_geometry() -> None:
    """Neither validation.py nor anything it imports from the package may touch ``_native``.

    The package's own ``__init__`` is left out: it reads the version from
    ``_native`` and contains no geometry.
    """
    seen: set[Path] = set()
    queue = [PACKAGE / "validation.py"]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        assert path.name != "_native.pyi", "the validator reaches _native"
        assert not any("_native" in module for module in imported_modules(path)), path.name
        queue.extend(in_package_imports(path))
    names = {path.relative_to(PACKAGE).as_posix() for path in seen}
    assert "validation.py" in names and "models.py" in names, "the import walk found nothing"


def test_no_solver_reaches_the_validator() -> None:
    """A search that consulted the validator would be checking its answer with its own oracle.

    Neither a solver nor anything it imports from the package may import
    ``validation``. Only ``api.solve`` brings the two together, after the search.
    """
    solver_sources = [p for p in package_sources() if "solvers" in p.relative_to(PACKAGE).parts]
    assert any(p.name == "contact_dfs.py" for p in solver_sources), "found no solver"
    seen: set[Path] = set()
    queue = list(solver_sources)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        assert path.name != "validation.py", "a solver reaches the validator"
        # The package's __init__ re-exports the API; solvers import from the modules themselves.
        queue.extend(p for p in in_package_imports(path) if p != PACKAGE / "__init__.py")
    importers = [
        path.relative_to(PACKAGE).as_posix()
        for path in package_sources()
        if any(module.startswith("maxplus_solvers.validation") for module in imported_modules(path))
    ]
    assert importers == ["api.py"]


def test_solvers_are_registered_under_the_family_they_live_in() -> None:
    """``python.*`` are the prototypes; every solver declares its regimes and its candidate set."""
    from maxplus_solvers import solvers

    assert solvers.available(), "nothing is registered"
    for name in solvers.available():
        spec = solvers.get(name)
        family, _, algorithm = name.partition(".")
        assert family and algorithm, name
        assert spec.regimes and spec.candidate_set and spec.description, name
        module = spec.run.__module__
        if family == "python":
            assert module == f"maxplus_solvers.solvers.prototypes.{algorithm}", name
        contract = (ROOT / "docs" / "solver-contract.md").read_text(encoding="utf-8")
        assert f"`{name}`" in contract and f"`{spec.candidate_set}`" in contract, name


def test_importing_the_package_does_not_need_the_optional_extras() -> None:
    """Shapely is loaded by the validator only, so the solvers run without it."""
    code = (
        "import sys, maxplus_solvers, maxplus_solvers.api, maxplus_solvers.sanitize; "
        "print(sorted(m for m in ('shapely', 'ortools', 'numpy') if m in sys.modules))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]"


def test_the_stub_declares_exactly_what_the_extension_exports() -> None:
    stub = ast.parse((PACKAGE / "_native.pyi").read_text(encoding="utf-8"))
    declared = {node.name for node in stub.body if isinstance(node, ast.FunctionDef | ast.ClassDef)}
    exported = {name for name in dir(_native) if not name.startswith("_")}
    assert declared == exported


def test_crates_depend_only_downwards() -> None:
    manifests = {path.parent.name: path for path in CRATES.glob("*/Cargo.toml")}
    assert set(manifests) == set(ALLOWED_CRATE_DEPENDENCIES)
    for crate, path in manifests.items():
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
        internal = {
            name
            for table in ("dependencies", "dev-dependencies", "build-dependencies")
            for name in manifest.get(table, {})
            if name.startswith("tiling-")
        }
        assert internal <= ALLOWED_CRATE_DEPENDENCIES[crate], crate


def test_the_binding_crate_is_the_only_one_that_knows_python() -> None:
    for path in CRATES.glob("*/Cargo.toml"):
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
        assert ("pyo3" in manifest.get("dependencies", {})) == (path.parent.name == "tiling-py")


def test_the_package_has_no_required_dependencies() -> None:
    """Shapely, OR-Tools and the analysis stack are extras; the Rust solvers run without them."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == []


@pytest.mark.parametrize("path", package_sources(), ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_optional_packages_are_imported_only_where_they_belong(path: Path) -> None:
    relative = path.relative_to(PACKAGE).as_posix()
    for module in imported_modules(path):
        home = OPTIONAL_IMPORTS.get(module.split(".")[0])
        if home is not None:
            assert relative == home or (home.endswith("/") and relative.startswith(home)), module
    # Test-only packages never belong in the package.
    assert not {m.split(".")[0] for m in imported_modules(path)} & {
        "pytest",
        "hypothesis",
        "jsonschema",
    }


@pytest.mark.parametrize("path", package_sources(), ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_the_package_never_reaches_for_the_answer_keys(path: Path) -> None:
    """Keys live under tests/ and only tests load them. The package does not mention that tree."""
    text = path.read_text(encoding="utf-8")
    assert "tests/" not in text and "tests\\" not in text and '"tests"' not in text
    assert "keys/" not in text and '"keys"' not in text


def test_only_the_fixture_generator_writes_keys() -> None:
    mentioning = [
        path.name
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if '"keys"' in path.read_text(encoding="utf-8")
    ]
    assert mentioning == ["import_fixtures.py"]


def test_only_the_importer_reads_the_source_reference() -> None:
    """`reference` is the answer. One module may read it, and it hands over to the sanitizer."""
    readers = [
        path.relative_to(PACKAGE).as_posix()
        for path in package_sources()
        if '["reference"]' in path.read_text(encoding="utf-8")
    ]
    assert readers == ["io/tropical.py"]
