from pathlib import Path

import pytest

from specgate.spec import parse_spec
from specgate.traceability import TestScanError, check_traceability, find_spec_refs

SPEC = """
## A-1: First
When x
Then y

## A-2: Second
When x
Then y
"""


def write_test_file(tmp_path: Path, body: str) -> Path:
    test_file = tmp_path / "test_example.py"
    test_file.write_text(body)
    return test_file


def test_finds_markers_on_functions_classes_and_methods(tmp_path):
    test_file = write_test_file(
        tmp_path,
        """
import pytest
from pytest import mark

@pytest.mark.spec("A-1")
def test_one(): ...

@mark.spec("A-2", "A-3")
async def test_two(): ...

@pytest.mark.spec("A-4")
class TestGroup:
    @pytest.mark.spec("A-5")
    def test_inner(self): ...
""",
    )

    refs = find_spec_refs([tmp_path])

    assert [(r.spec_id, r.test_name) for r in refs] == [
        ("A-1", "test_one"),
        ("A-2", "test_two"),
        ("A-3", "test_two"),
        ("A-4", "TestGroup"),
        ("A-5", "TestGroup::test_inner"),
    ]
    assert refs[0].node_id == f"{test_file}::test_one"


def test_ignores_other_markers_and_non_test_functions(tmp_path):
    write_test_file(
        tmp_path,
        """
import pytest

@pytest.mark.slow
@pytest.mark.parametrize("x", [1])
def test_unrelated(x): ...

@pytest.mark.spec("A-1")
def helper(): ...
""",
    )

    assert find_spec_refs([tmp_path]) == []


def test_non_literal_marker_argument_is_an_error(tmp_path):
    write_test_file(
        tmp_path,
        """
import pytest
ID = "A-1"

@pytest.mark.spec(ID)
def test_one(): ...
""",
    )

    with pytest.raises(TestScanError, match="must be string literals"):
        find_spec_refs([tmp_path])


def test_passes_when_every_id_is_covered_and_known(tmp_path):
    write_test_file(
        tmp_path,
        """
import pytest

@pytest.mark.spec("A-1")
def test_one(): ...

@pytest.mark.spec("A-1", "A-2")
def test_two(): ...
""",
    )

    report = check_traceability(parse_spec(SPEC), find_spec_refs([tmp_path]))

    assert report.passed
    assert [r.test_name for r in report.covered["A-1"]] == ["test_one", "test_two"]
    assert report.uncovered == ()
    assert report.unknown == ()


def test_fails_on_uncovered_scenario_and_unknown_id(tmp_path):
    write_test_file(
        tmp_path,
        """
import pytest

@pytest.mark.spec("A-1")
def test_one(): ...

@pytest.mark.spec("A-99")
def test_invented(): ...
""",
    )

    report = check_traceability(parse_spec(SPEC), find_spec_refs([tmp_path]))

    assert not report.passed
    assert [s.id for s in report.uncovered] == ["A-2"]
    assert [(r.spec_id, r.test_name) for r in report.unknown] == [("A-99", "test_invented")]
