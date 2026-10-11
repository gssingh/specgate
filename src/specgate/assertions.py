"""Stage 4: assertion-strength gate.

Traceability proves a test *claims* a scenario. It doesn't prove the test
checks anything. AI-written tests are prone to "coverage theater": they call
the code, then assert something that can't fail, or nothing at all:

    def test_new_hire():
        actions = plan_sync(hr, [])
        assert actions is not None      # passes for any return value

This gate reads every test as a syntax tree (like stage 3, nothing is run)
and sorts each assertion into strong or weak. A test passes if it has at
least one strong assertion. Weak means "can only fail if the code crashes
or returns nothing", for example:

    assert True                         constant
    assert x == x                       compares a value with itself
    assert result                       only truthiness
    assert result is not None           only existence
    assert isinstance(result, list)     only the type
    assert len(result) > 0              only non-empty
    with pytest.raises(Exception):      any exception at all
    mock.assert_called()                called, with any arguments

Anything else (comparing to an expected value, `assert not errors`,
`pytest.raises(ValueError)`, `assertEqual`) counts as strong. The rules are
deliberately simple heuristics: stage 5 (mutation testing) is the gate that
measures whether assertions really catch bugs.
"""

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from specgate.traceability import find_spec_refs, find_test_files

# unittest / mock assertion methods that only prove existence or a call.
_WEAK_ASSERT_METHODS = {
    "assertTrue": "only checks truthiness",
    "assertIsNotNone": "only checks the value is not None",
    "assertIsInstance": "only checks the type",
    "assert_called": "only checks the mock was called, not with what",
    "assert_called_once": "only checks the mock was called, not with what",
}

_TYPE_CHECKS = {"isinstance", "callable", "hasattr"}
_BROAD_EXCEPTIONS = {"Exception", "BaseException"}


class Strength(Enum):
    STRONG = "strong"  # at least one assertion that can catch a wrong value
    WEAK = "weak"  # only assertions that can't tell right from wrong
    MISSING = "missing"  # no assertions at all


@dataclass(frozen=True)
class WeakAssertion:
    line: int
    reason: str


@dataclass(frozen=True)
class TestStrength:
    """How well one test function asserts."""

    __test__ = False  # stop pytest trying to collect this as a test class

    test_name: str  # e.g. "test_rehire" or "TestRoles::test_change"
    source: Path
    line: int
    spec_ids: tuple[str, ...]
    strong_count: int
    weak: tuple[WeakAssertion, ...]

    @property
    def strength(self) -> Strength:
        if self.strong_count:
            return Strength.STRONG
        return Strength.WEAK if self.weak else Strength.MISSING

    @property
    def node_id(self) -> str:
        return f"{self.source}::{self.test_name}"


@dataclass(frozen=True)
class AssertionReport:
    tests: tuple[TestStrength, ...]

    @property
    def failing(self) -> tuple[TestStrength, ...]:
        return tuple(t for t in self.tests if t.strength is not Strength.STRONG)

    @property
    def passed(self) -> bool:
        return not self.failing


def check_assertions(paths: Iterable[Path | str]) -> AssertionReport:
    """Grade every test function in the test files under the given paths."""
    files = find_test_files(paths)
    spec_ids = _spec_ids_by_test(files)
    results: list[TestStrength] = []
    for test_file in files:
        tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        for name, class_name, func in _test_functions(tree):
            # A spec marker on the class applies to its methods too.
            ids = spec_ids.get((test_file, name), ()) + spec_ids.get((test_file, class_name), ())
            results.append(_grade(func, name, test_file, ids))
    return AssertionReport(tuple(results))


def _spec_ids_by_test(files: list[Path]) -> dict[tuple[Path, str | None], tuple[str, ...]]:
    ids: dict[tuple[Path, str | None], tuple[str, ...]] = {}
    for ref in find_spec_refs(files):
        key = (ref.source, ref.test_name)
        ids[key] = ids.get(key, ()) + (ref.spec_id,)
    return ids


def _test_functions(
    tree: ast.Module,
) -> Iterator[tuple[str, str | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield (test name, enclosing class name or None, function node).

    Same naming rules as stage 3: test* functions, and test* methods
    inside Test* classes.
    """
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, functions) and node.name.startswith("test"):
            yield node.name, None, node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for member in node.body:
                if isinstance(member, functions) and member.name.startswith("test"):
                    yield f"{node.name}::{member.name}", node.name, member


def _grade(
    func: ast.FunctionDef | ast.AsyncFunctionDef, name: str, source: Path, spec_ids: tuple[str, ...]
) -> TestStrength:
    strong = 0
    weak: list[WeakAssertion] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            reason = _weak_assert_reason(node.test)
        elif isinstance(node, ast.Call) and _is_assertion_call(node):
            reason = _weak_call_reason(node)
        else:
            continue
        if reason:
            weak.append(WeakAssertion(node.lineno, reason))
        else:
            strong += 1
    return TestStrength(name, source, func.lineno, spec_ids, strong, tuple(weak))


def _weak_assert_reason(test: ast.expr) -> str | None:
    """Why `assert <test>` is weak, or None if it's strong."""
    match test:
        case ast.Constant():
            return "asserts a constant, so it can never fail"
        case ast.Name() | ast.Attribute():
            return "only checks truthiness, not the value"
        case ast.Call(func=ast.Name(id=func_name)) if func_name in _TYPE_CHECKS:
            return f"only checks the type ({func_name})"
        case ast.Compare(left=left, ops=[op], comparators=[right]):
            if ast.dump(left) == ast.dump(right):
                return "compares a value with itself"
            if isinstance(op, ast.IsNot) and _is_none(right):
                return "only checks the value is not None"
            if _is_len_call(left) and _is_non_empty_check(op, right):
                return "only checks the collection is non-empty"
        case ast.BoolOp(values=values):
            # `assert a and b` is as strong as its strongest part.
            reasons = [_weak_assert_reason(value) for value in values]
            if all(reasons):
                return reasons[0]
    return None


def _is_assertion_call(call: ast.Call) -> bool:
    """pytest.raises(...), raises(...), or a method named assert*."""
    match call.func:
        case ast.Attribute(attr="raises") | ast.Name(id="raises"):
            return True
        case ast.Attribute(attr=attr):
            return attr.startswith("assert")
    return False


def _weak_call_reason(call: ast.Call) -> str | None:
    match call.func:
        case ast.Attribute(attr="raises") | ast.Name(id="raises"):
            broad = bool(call.args) and _name_of(call.args[0]) in _BROAD_EXCEPTIONS
            checks_message = any(keyword.arg == "match" for keyword in call.keywords)
            if broad and not checks_message:
                return "pytest.raises(Exception) passes for any error, including bugs"
        case ast.Attribute(attr=attr) if attr in _WEAK_ASSERT_METHODS:
            return _WEAK_ASSERT_METHODS[attr]
    return None


def _name_of(node: ast.expr) -> str | None:
    """'Exception' for both Exception and builtins.Exception."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
    return None


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_len_call(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _name_of(node.func) == "len"


def _is_non_empty_check(op: ast.cmpop, right: ast.expr) -> bool:
    """len(x) > 0, len(x) >= 1, len(x) != 0, and the always-true len(x) >= 0."""
    if not (isinstance(right, ast.Constant) and isinstance(right.value, int)):
        return False
    return (type(op), right.value) in {
        (ast.Gt, 0),
        (ast.GtE, 1),
        (ast.GtE, 0),
        (ast.NotEq, 0),
    }
