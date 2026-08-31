"""The Dockerfile's COPY list, checked against what the code actually imports.

This list has broken the deployment twice. Once `swarm/` was missing and the container
booted healthy, passed its health check, and failed on the first real request. Once `obs/`
was missing and it would not start at all — caught only because the deploy failed loudly.

Both were the same mistake: a list maintained by remembering. This walks the imports
instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Packages the container never needs: test-only, or tooling that does not ship.
EXEMPT = {"tests", "console", "docs", "infra"}


def local_packages() -> set[str]:
    return {
        p.name for p in ROOT.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
        and any(p.glob("*.py")) and p.name not in EXEMPT
    }


def copied() -> set[str]:
    text = (ROOT / "Dockerfile").read_text()
    return set(re.findall(r"^COPY ([a-z_]+)/ \./", text, re.M))


def imports_of(path: Path, packages: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in packages:
                found.add(root)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in packages:
                    found.add(root)
    return found


def reachable_from_api() -> set[str]:
    """Transitive closure of what `api/` imports, over local packages only."""
    packages = local_packages()
    seen: set[str] = set()
    frontier = {"api"}
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        directory = ROOT / current
        if not directory.is_dir():
            continue
        for module in directory.rglob("*.py"):
            frontier |= imports_of(module, packages) - seen
    return seen


class TestCopyList:
    def test_every_reachable_package_is_copied(self) -> None:
        """The failure this exists to prevent: ModuleNotFoundError at container start, or
        worse, on the first request after a healthy boot."""
        missing = sorted(reachable_from_api() - copied())
        assert not missing, (
            f"Dockerfile does not COPY {missing}, which api/ imports transitively. "
            f"The container will fail to start or fail on first use."
        )

    def test_the_copy_list_names_real_directories(self) -> None:
        """A COPY of a directory that no longer exists fails the build late and loudly,
        which is better than silently, but is still worth catching here."""
        for name in copied():
            assert (ROOT / name).is_dir(), f"Dockerfile copies {name}/, which is absent"

    def test_api_itself_is_copied(self) -> None:
        assert "api" in copied()
