from pathlib import Path

from specgate.cli import EXIT_BAD_INPUT, EXIT_FAILED, EXIT_PASSED, main

EXAMPLE = Path(__file__).parent.parent / "examples" / "identity_sync"


def test_example_project_passes(capsys):
    exit_code = main(["trace", "--specs", str(EXAMPLE / "specs"), "--tests", str(EXAMPLE / "tests")])

    assert exit_code == EXIT_PASSED
    assert "Traceability: PASS" in capsys.readouterr().out


def test_gap_fails_and_is_listed(tmp_path, capsys):
    (tmp_path / "spec.md").write_text("## A-1: Lonely scenario\nWhen x\nThen y\n")
    (tmp_path / "test_x.py").write_text(
        'import pytest\n\n@pytest.mark.spec("B-1")\ndef test_x(): ...\n'
    )

    exit_code = main(["trace", "--specs", str(tmp_path), "--tests", str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == EXIT_FAILED
    assert "A-1  Lonely scenario" in out
    assert "B-1" in out


def test_malformed_spec_is_bad_input(tmp_path, capsys):
    (tmp_path / "spec.md").write_text("## A-1: No outcome\nWhen x\n")

    exit_code = main(["trace", "--specs", str(tmp_path), "--tests", str(tmp_path)])

    assert exit_code == EXIT_BAD_INPUT
    assert "has no Then step" in capsys.readouterr().err


def test_assertions_pass_on_the_example(capsys):
    exit_code = main(["assertions", "--tests", str(EXAMPLE / "tests")])

    assert exit_code == EXIT_PASSED
    assert "Assertion strength: PASS" in capsys.readouterr().out


def test_assertions_fail_on_coverage_theater(capsys):
    exit_code = main(["assertions", "--tests", str(EXAMPLE / "theater")])

    out = capsys.readouterr().out
    assert exit_code == EXIT_FAILED
    assert "0/6 tests have a strong assertion" in out
    assert "MISSING" in out
    assert "compares a value with itself" in out


def test_assertions_on_unparseable_file_is_bad_input(tmp_path, capsys):
    (tmp_path / "test_broken.py").write_text("def test_x(:\n")

    exit_code = main(["assertions", "--tests", str(tmp_path)])

    assert exit_code == EXIT_BAD_INPUT
    assert "error:" in capsys.readouterr().err
