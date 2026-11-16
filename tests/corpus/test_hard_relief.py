"""A relief puzzle harder than ``cor1`` for the contact search: the Pleat puzzles.

``plt1`` to ``plt5`` were built in Tropical Puzzle Lab to be hard with their roofs on: a
grid of rectangles, each cut along a diagonal, with every grid corner at one of two
heights, so that many edges share a height profile. Their searches are in
``corpus.EXPENSIVE``, so this reads what the committed tables say rather than searching:
``maxplus-bench run benchmarks/manifests/corpus.toml --no-times`` (and ``edge_to_edge.toml``)
is what checks those rows against a search. ``cor1``'s rows are reproduced by a search in
``test_benchmark.py``, so the comparison is with a number the suite does check.

A whole search visits the same nodes in any order, so its count is the measure; the number
of nodes to the first assembly is the one that depends on luck, and is not asserted here.
"""

from pathlib import Path

from support import corpus

RESULTS = Path(__file__).resolve().parents[2] / "benchmarks" / "results"
SEARCH = "`rust.contact_dfs`"
NODE_LIMIT = 1_500_000


def rows(table: str) -> list[dict[str, str]]:
    return corpus.table((RESULTS / table).read_text(encoding="utf-8"))


def count(cell: str) -> int:
    return int(cell.replace(" ", ""))


def plain() -> dict[str, dict[str, str]]:
    return {row["Fixture"]: row for row in rows("corpus.md") if row["Solver"] == SEARCH}


def test_every_pleat_relief_puzzle_has_one_assembly_found_by_a_whole_search() -> None:
    table = plain()
    for fixture in sorted(corpus.PLEAT):
        row = table[fixture]
        assert row["Mode"] == "relief"
        assert (row["Status"], row["Whole search"], row["Solutions"], row["Valid"]) == (
            "solved",
            "yes",
            "1",
            "1",
        ), fixture


def test_the_hardest_pleat_is_harder_than_cor1_with_its_roofs_on() -> None:
    """The exit criterion: at least 10 000 nodes, rating 4 in Tropical Puzzle Lab, and more
    than ``cor1``'s 1 529. Every 4 x 4 Pleat (32 pieces) is past ``cor1`` too."""
    table = plain()
    nodes = {fixture: count(table[fixture]["Nodes"]) for fixture in corpus.PLEAT}
    cor1 = count(table["cor1"]["Nodes"])
    assert max(nodes.values()) >= 10_000
    assert max(nodes.values()) > cor1
    assert all(nodes[f] > cor1 for f in corpus.PLEAT if count(table[f]["Pieces"]) == 32)
    # And past every other relief puzzle by more than that.
    others = [
        count(row["Nodes"])
        for fixture, row in table.items()
        if row["Mode"] == "relief" and fixture not in corpus.PLEAT
    ]
    assert max(others) == cor1


def test_without_roofs_the_pleat_footprints_have_many_assemblies() -> None:
    """The other side of the design: two heights make the roofs matter, and without them the
    triangles fit together in tens of thousands of ways, all valid. The search stops at
    its node limit still finding more, so the count is a lower bound. (A stopped search that
    found something reports ``solved``; ``Whole search`` says it did not end.)"""
    table = plain()
    for fixture in sorted(corpus.PLEAT_FLAT):
        row = table[fixture]
        assert (row["Status"], row["Whole search"]) == ("solved", "no"), fixture
        assert count(row["Nodes"]) == NODE_LIMIT
        assert row["Solutions"] == row["Valid"]
        assert count(row["Solutions"]) > 10_000, fixture


def test_assuming_edge_to_edge_takes_most_of_the_difficulty_away() -> None:
    """Pleat is cut edge to edge, so the assumption holds of its answer. Under it the relief
    search keeps its one assembly and drops below ``cor1``'s 967: the long edges that a short
    one could lie against part way along are what made it hard."""
    assumed = {
        row["Fixture"]: row
        for row in rows("edge_to_edge.md")
        if row["assumes"] == "edge-to-edge"
        and row["equal_edges"] == "true"
        and row["wall_edges"] == "true"
    }
    cor1 = count(assumed["cor1"]["Nodes"])
    for fixture in sorted(corpus.PLEAT):
        row = assumed[fixture]
        assert (row["Whole search"], row["Solutions"], row["Valid"]) == ("yes", "1", "1"), fixture
        assert count(row["Nodes"]) < cor1, fixture
