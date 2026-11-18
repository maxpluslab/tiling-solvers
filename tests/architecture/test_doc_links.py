"""What the documents point at exists: relative links, their anchors, and quoted repository paths.

A public reader follows the README and ``docs/`` to tables, fixtures, the validator
and the figure. A renamed file or heading must break this test, not the reader's click.
"""

import re
import subprocess
from pathlib import Path

import pytest

from support import corpus

ROOT = corpus.ROOT
DOCUMENTS = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").glob("*.md"))]

LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE_SPAN = re.compile(r"`([^`\s]+)`")
# A code span is taken for a path when it starts at one of these and names no pattern.
TOP_LEVEL = ("benchmarks/", "crates/", "docs/", "notebooks/", "python/", "schemas/", "scripts/",
             "tests/", ".github/")  # fmt: skip
SIBLING = re.compile(r"tropical.puzzle.lab", re.IGNORECASE)
# Generated on a machine and never committed (CLAUDE.md: a committed table has no times).
NOT_COMMITTED = (".jsonl",)


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[`*]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)  # no headings inside code blocks
    return {slug(line.lstrip("#")) for line in text.splitlines() if re.match(r"#{1,6} ", line)}


def broken_links(document: Path) -> list[str]:
    text = document.read_text(encoding="utf-8")
    broken: list[str] = []
    for target in LINK.findall(text):
        if re.match(r"[a-z]+:", target):  # https:, mailto:
            continue
        file_part, _, anchor = target.partition("#")
        path = (document.parent / file_part).resolve() if file_part else document
        if not path.exists() or (anchor and path.suffix == ".md" and anchor not in anchors(path)):
            broken.append(target)
    return broken


def missing_paths(document: Path) -> list[str]:
    text = document.read_text(encoding="utf-8")
    missing: list[str] = []
    # A line about Tropical Puzzle Lab quotes that repository's paths, not this one's.
    own = "\n".join(line for line in text.splitlines() if not SIBLING.search(line))
    for span in CODE_SPAN.findall(own):
        path = span.split("::")[0].rstrip(".,:")
        if not path.startswith(TOP_LEVEL) or any(c in path for c in "*<>{}"):
            continue
        if path.endswith(NOT_COMMITTED):
            continue
        if not (ROOT / path).exists():
            missing.append(span)
    return missing


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_resolves(document: Path) -> None:
    assert broken_links(document) == []


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_quoted_repository_path_exists(document: Path) -> None:
    assert missing_paths(document) == []


def test_a_broken_link_and_a_missing_path_are_caught(tmp_path: Path) -> None:
    # The guard itself, on a document written to fail: a missing file, a missing anchor,
    # and a quoted path that does not exist. The good link and path must pass.
    (tmp_path / "other.md").write_text("# A heading, with `code`\n", encoding="utf-8")
    document = tmp_path / "doc.md"
    document.write_text(
        "[ok](other.md#a-heading-with-code) [gone](nowhere.md) [bad](other.md#no-such)\n"
        "`docs/roadmap.md` `docs/no-such-file.md`\n",
        encoding="utf-8",
    )
    assert broken_links(document) == ["nowhere.md", "other.md#no-such"]
    assert missing_paths(document) == ["docs/no-such-file.md"]


def test_every_linked_file_is_committed() -> None:
    """A link to a file that exists only on this machine is as broken as a missing one."""
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    )
    untracked: list[str] = []
    for document in DOCUMENTS:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            file_part = target.partition("#")[0]
            if not file_part or re.match(r"[a-z]+:", target):
                continue
            path = (document.parent / file_part).resolve()
            relative = path.relative_to(ROOT).as_posix()
            if path.is_file() and relative not in tracked:
                untracked.append(relative)
    assert untracked == []
