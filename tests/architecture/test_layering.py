"""Invariants of the repository itself, from CLAUDE.md. They fail when the structure is broken."""

import ast
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
