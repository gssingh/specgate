from pathlib import Path

import pytest

from specgate.assertions import Strength, check_assertions


def grade(tmp_path: Path, body: str):
    """Write body as a test file and grade its only test."""
    (tmp_path / "test_example.py").write_text("import pytest\n\n" + body)
    [test] = check_assertions([tmp_path]).tests
    return test


@pytest.mark.parametrize(
    "assertion",
    [
        "assert result == [1, 2]",
        "assert result != []",
        "assert not errors",
        "assert 'e100' in result",
        "assert compute(1) == 2",
        "assert result is None",
        "assert len(result) == 2",
        "assert ok and result == 2",
        "with pytest.raises(ValueError): compute()",
        "with pytest.raises(Exception, match='bad id'): compute()",
        "self.assertEqual(result, 2)",
        "mock.assert_called_once_with('e100')",
    ],
)
def test_strong_assertions(tmp_path, assertion):
    test = grade(tmp_path, f"def test_x():\n    {assertion}\n")

    assert test.strength is Strength.STRONG
    assert test.weak == ()


@pytest.mark.parametrize(
    ("assertion", "reason"),
    [
        ("assert True", "asserts a constant"),
        ("assert 'done'", "asserts a constant"),
        ("assert result", "only checks truthiness"),
        ("assert response.ok", "only checks truthiness"),
        ("assert result == result", "compares a value with itself"),
        ("assert result is not None", "not None"),
        ("assert isinstance(result, list)", "only checks the type"),
        ("assert hasattr(result, 'id')", "only checks the type"),
        ("assert len(result) > 0", "non-empty"),
        ("assert len(result) >= 0", "non-empty"),
        ("assert result and result is not None", "only checks truthiness"),
        ("with pytest.raises(Exception): compute()", "any error"),
        ("self.assertIsNotNone(result)", "not None"),
        ("mock.assert_called()", "not with what"),
    ],
)
def test_weak_assertions(tmp_path, assertion, reason):
    test = grade(tmp_path, f"def test_x():\n    {assertion}\n")

    assert test.strength is Strength.WEAK
    [weak] = test.weak
    assert reason in weak.reason
    assert weak.line == 4


def test_no_assertions_is_missing(tmp_path):
    test = grade(tmp_path, "def test_x():\n    compute()\n")

    assert test.strength is Strength.MISSING
    assert test.strong_count == 0


def test_one_strong_assertion_is_enough(tmp_path):
    test = grade(
        tmp_path,
        "def test_x():\n    assert result is not None\n    assert result == 2\n",
    )

    assert test.strength is Strength.STRONG
    assert test.strong_count == 1
    assert [w.reason for w in test.weak] == ["only checks the value is not None"]


def test_names_spec_ids_and_methods(tmp_path):
    (tmp_path / "test_example.py").write_text(
        """
import pytest

@pytest.mark.spec("A-1")
def test_one():
    assert True

@pytest.mark.spec("A-2")
class TestGroup:
    @pytest.mark.spec("A-3")
    def test_inner(self):
        assert self.value == 1

    def helper(self):
        pass

def not_a_test():
    pass
"""
    )

    report = check_assertions([tmp_path])

    assert [(t.test_name, t.spec_ids, t.strength) for t in report.tests] == [
        ("test_one", ("A-1",), Strength.WEAK),
        ("TestGroup::test_inner", ("A-3", "A-2"), Strength.STRONG),
    ]
    assert not report.passed
    assert [t.test_name for t in report.failing] == ["test_one"]
