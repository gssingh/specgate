"""Stage 3: traceability gate.

Checks two things:
  1. every spec scenario ID is claimed by at least one test, and
  2. no test claims an ID that the specs don't define.

Tests claim IDs with a pytest marker:

    @pytest.mark.spec("SYNC-001")
    def test_new_hire_gets_account(): ...

We find markers by reading test files as syntax trees (the `ast` module),
not by importing or running them. That keeps the gate fast and safe, and
means a broken test file can't hide its markers behind an import error.
"""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from specgate.spec import Scenario


class TestScanError(ValueError):
    """A spec marker we can't read statically, e.g. spec(some_variable)."""

    __test__ = False  # stop pytest trying to collect this as a test class

    def __init__(self, source: Path, line: int, message: str):
        self.source = source
        self.line = line
        super().__init__(f"{source}:{line}: {message}")


@dataclass(frozen=True)
class SpecRef:
    """One test claiming one spec ID."""

    spec_id: str
    test_name: str  # e.g. "test_rehire" or "TestRoles::test_change"
    source: Path
    line: int

    @property
    def node_id(self) -> str:
        """The test's pytest node ID, e.g. tests/test_sync.py::test_rehire."""
        return f"{self.source}::{self.test_name}"


@dataclass(frozen=True)
class TraceabilityReport:
    covered: dict[str, tuple[SpecRef, ...]]  # spec ID -> tests claiming it
    uncovered: tuple[Scenario, ...]  # scenarios no test claims
    unknown: tuple[SpecRef, ...]  # tests claiming IDs no spec defines

    @property
    def passed(self) -> bool:
        return not self.uncovered and not self.unknown


def check_traceability(
    scenarios: Iterable[Scenario], refs: Iterable[SpecRef]
) -> TraceabilityReport:
    scenarios = list(scenarios)
    known_ids = {scenario.id for scenario in scenarios}

    covered: dict[str, list[SpecRef]] = {}
    unknown: list[SpecRef] = []
    for ref in refs:
        if ref.spec_id in known_ids:
            covered.setdefault(ref.spec_id, []).append(ref)
        else:
            unknown.append(ref)

    return TraceabilityReport(
        covered={spec_id: tuple(found) for spec_id, found in covered.items()},
        uncovered=tuple(s for s in scenarios if s.id not in covered),
        unknown=tuple(unknown),
    )


def find_spec_refs(paths: Iterable[Path | str]) -> list[SpecRef]:
    """Collect spec markers from every test file under the given paths."""
    refs: list[SpecRef] = []
    for test_file in find_test_files(paths):
        tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        refs.extend(_refs_in_module(tree, test_file))
    return refs


def find_test_files(paths: Iterable[Path | str]) -> list[Path]:
    """Test files under the given paths, named like pytest expects: test_*.py, *_test.py."""
    files: list[Path] = []
    for path in map(Path, paths):
        if path.is_dir():
            found = set(path.rglob("test_*.py")) | set(path.rglob("*_test.py"))
            files.extend(sorted(found))
        else:
            files.append(path)
    return files


def _refs_in_module(tree: ast.Module, source: Path) -> list[SpecRef]:
    refs: list[SpecRef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                refs.extend(_refs_on(node, node.name, source))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            # A marker on the class applies to every test inside it.
            refs.extend(_refs_on(node, node.name, source))
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if member.name.startswith("test"):
                        refs.extend(_refs_on(member, f"{node.name}::{member.name}", source))
    return refs


def _refs_on(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, test_name: str, source: Path
) -> list[SpecRef]:
    refs: list[SpecRef] = []
    for decorator in node.decorator_list:
        if not _is_spec_marker(decorator):
            continue
        for arg in decorator.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                raise TestScanError(
                    source, arg.lineno, "spec marker arguments must be string literals"
                )
            refs.append(SpecRef(arg.value, test_name, source, node.lineno))
    return refs


def _is_spec_marker(decorator: ast.expr) -> bool:
    """True for @pytest.mark.spec(...) and @mark.spec(...)."""
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "spec"
    ):
        return False
    owner = decorator.func.value  # the thing before ".spec"
    return (isinstance(owner, ast.Attribute) and owner.attr == "mark") or (
        isinstance(owner, ast.Name) and owner.id == "mark"
    )
