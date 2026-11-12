"""The first notebook runs from top to bottom.

A notebook is code nobody imports, so nothing else notices when it breaks. Its
code cells are run here in order, in one namespace, as Jupyter would run them.
It uses the ``smoke`` manifest, so this takes a second.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "first-look.ipynb"


def code_cells() -> list[str]:
    document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert document["nbformat"] == 4
    return ["".join(c["source"]) for c in document["cells"] if c["cell_type"] == "code"]


def test_the_notebook_is_committed_without_outputs() -> None:
    document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in document["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
    assert document["cells"][0]["cell_type"] == "markdown"


@pytest.mark.parametrize("start", ["root", "notebooks"])
def test_the_notebook_runs_from_top_to_bottom(
    start: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT if start == "root" else ROOT / "notebooks")
    namespace: dict[str, Any] = {}
    cells = code_cells()
    assert len(cells) >= 5
    for source in cells:
        exec(compile(source, str(NOTEBOOK), "exec"), namespace)
    assert namespace["MANIFEST"] == "smoke"
    # Every solver ran on the two smoke fixtures.
    assert len(namespace["records"]) == 6
    assert all(record["status"] == "solved" for record in namespace["records"])
    assert isinstance(namespace["figure"], Figure)
    assert set(namespace["rows"]) == {"new5", "new5-flat"}
    printed = capsys.readouterr().out
    assert "| `new5-flat` |" in printed and "Spearman with nodes" in printed
