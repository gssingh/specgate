from pathlib import Path

import pytest

from specgate.spec import SpecParseError, load_specs, parse_spec

EXAMPLE_SPECS = Path(__file__).parent.parent / "examples" / "identity_sync" / "specs"


def test_parses_id_title_and_steps():
    text = """
# Feature

## SYNC-001: New hire gets an account
- Given an active HR record
- And no account exists
- When the sync runs
- Then an account is created
- But no review is flagged
"""
    [scenario] = parse_spec(text, "sync.md")

    assert scenario.id == "SYNC-001"
    assert scenario.title == "New hire gets an account"
    assert scenario.given == ("an active HR record", "no account exists")
    assert scenario.when == ("the sync runs",)
    assert scenario.then == ("an account is created", "no review is flagged")
    assert scenario.source == Path("sync.md")
    assert scenario.line == 4


def test_steps_work_without_bullets_and_prose_is_ignored():
    text = """
## DISC-3: Plain lines
Some explanation that is not a step.
When something happens
Then something is true
"""
    [scenario] = parse_spec(text)

    assert scenario.given == ()
    assert scenario.when == ("something happens",)
    assert scenario.then == ("something is true",)


def test_non_id_heading_ends_the_scenario():
    text = """
## A-1: First
When x
Then y

## Notes
Free text here.
"""
    scenarios = parse_spec(text)

    assert [s.id for s in scenarios] == ["A-1"]


def test_steps_inside_code_blocks_are_ignored():
    text = """
## A-1: First
When x
Then y

```
Given this is just an example in a code block
```
"""
    [scenario] = parse_spec(text)

    assert scenario.given == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## A-1: t\nWhen x\n", "scenario A-1 has no Then step"),
        ("## A-1: t\nGiven x\nThen y\n", "scenario A-1 has no When step"),
        ("## A-1: t\nAnd x\nWhen y\nThen z\n", "'And' must follow"),
        ("## A-1: t\nWhen x\nGiven y\nThen z\n", "'Given' step cannot come after a 'When'"),
        ("When x\n", "step found outside a scenario"),
        ("## A-1: t\nWhen x\nThen y\n## A-1: u\nWhen x\nThen y\n", "duplicate scenario ID A-1"),
    ],
)
def test_malformed_specs_are_rejected(text, message):
    with pytest.raises(SpecParseError, match=message):
        parse_spec(text, "bad.md")


def test_error_reports_file_and_line():
    with pytest.raises(SpecParseError) as error:
        parse_spec("# Title\n\n## A-1: t\nWhen x\n", "bad.md")

    assert str(error.value).startswith("bad.md:3:")


def test_duplicate_ids_across_files_are_rejected(tmp_path):
    (tmp_path / "a.md").write_text("## A-1: t\nWhen x\nThen y\n")
    (tmp_path / "b.md").write_text("## A-1: t\nWhen x\nThen y\n")

    with pytest.raises(SpecParseError, match="duplicate scenario ID A-1"):
        load_specs([tmp_path])


def test_example_spec_parses():
    scenarios = load_specs([EXAMPLE_SPECS])

    assert [s.id for s in scenarios] == [f"SYNC-00{n}" for n in range(1, 7)]
