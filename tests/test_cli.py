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
