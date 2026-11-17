"""Committed tables read back: ``report.parse_markdown`` is the inverse of ``report.markdown``."""

import pytest

from maxplus_solvers.experiments import report

# Written by hand in the shape of benchmarks/results/*.md.
TABLE = """\
| Fixture | Nodes | Whole search |
| --- | --- | --- |
| `a-flat` | 1 064 878 | yes |
| `b` | 26 |  |
"""


def test_a_table_is_read_by_its_header() -> None:
    assert report.parse_markdown(TABLE) == [
        {"Fixture": "`a-flat`", "Nodes": "1 064 878", "Whole search": "yes"},
        {"Fixture": "`b`", "Nodes": "26", "Whole search": ""},
    ]


def test_what_markdown_writes_is_read_back_unchanged() -> None:
    cells = [["x", "y"], ["1", "`two`"], ["", "3 000"]]
    rows = report.parse_markdown(report.markdown(cells))
    assert [[row["x"], row["y"]] for row in rows] == cells[1:]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("| a | b |\n| 1 | 2 |\n", "rule"),  # the rule is missing
        ("| a | b |\n| --- | --- |\n| 1 |\n", "line 3 has 1 cells"),  # a short row
        ("| a |\n| --- |\n1\n", "not a table row"),  # a line that is not a row
        ("| a |\n", "header and a rule"),
    ],
)
def test_a_damaged_table_is_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        report.parse_markdown(text)
