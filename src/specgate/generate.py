"""Stage 2: AI test generation, checked by the deterministic gates.

For each scenario we ask a TestWriter (Claude, in real use) for one pytest
test, then decide with plain code whether to keep it:

  1. it parses,
  2. it claims exactly this scenario's ID (stage 3's marker scan),
  3. it has a strong assertion (stage 4's rules),
  4. it passes when run against the real code.

A failed check is sent back to the writer as feedback for another attempt.
A test that passes 1-3 but still fails when run is kept aside for a human,
because the code may be wrong rather than the test.

Step 4 runs AI-written code in a subprocess, so only point this at code you'd
be happy to run your own tests against.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from specgate.assertions import Strength, check_assertions
from specgate.prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_user_message
from specgate.spec import Scenario
from specgate.traceability import TestScanError, find_spec_refs

DEFAULT_MODEL = "claude-opus-5-5"
RUN_TIMEOUT_SECONDS = 60

# Lets the throwaway pytest run accept @pytest.mark.spec without warnings.
_PYTEST_INI = """\
[pytest]
addopts = --strict-markers -p no:cacheprovider
markers =
    spec(*ids): links a test to spec scenario IDs
"""


class GenerationError(RuntimeError):
    """The writer couldn't produce a draft at all (refusal, truncated reply...)."""


@dataclass(frozen=True)
class Target:
    """The module the generated tests exercise."""

    path: Path

    @property
    def module_name(self) -> str:
        return self.path.stem

    @property
    def source(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Draft:
    test_code: str
    assumptions: str = ""


class TestWriter(Protocol):
    """Anything that can draft a test. Java: an interface with one method."""

    __test__ = False  # stop pytest trying to collect this as a test class

    def write(self, scenario: Scenario, target: Target, feedback: str | None) -> Draft: ...


class Outcome(Enum):
    KEPT = "kept"  # passed every check
    NEEDS_REVIEW = "needs review"  # well formed, but fails against the code
    REJECTED = "rejected"  # never produced a well-formed, strong test


@dataclass(frozen=True)
class GeneratedTest:
    scenario: Scenario
    outcome: Outcome
    attempts: int
    draft: Draft | None  # the last draft, if any
    problem: str  # why it wasn't kept; empty when KEPT


def generate_tests(
    scenarios: Iterable[Scenario], target: Target, writer: TestWriter, max_attempts: int = 2
) -> list[GeneratedTest]:
    return [_generate_one(scenario, target, writer, max_attempts) for scenario in scenarios]


def _generate_one(
    scenario: Scenario, target: Target, writer: TestWriter, max_attempts: int
) -> GeneratedTest:
    feedback: str | None = None
    draft: Draft | None = None
    failed_run = False
    for attempt in range(1, max_attempts + 1):
        try:
            draft = writer.write(scenario, target, feedback)
        except GenerationError as error:
            feedback = str(error)
            continue
        failed_run = False
        problem = check_draft(draft, scenario)
        if not problem:
            problem = run_draft(draft, target)
            failed_run = bool(problem)
        if not problem:
            return GeneratedTest(scenario, Outcome.KEPT, attempt, draft, "")
        feedback = problem

    outcome = Outcome.NEEDS_REVIEW if failed_run else Outcome.REJECTED
    return GeneratedTest(scenario, outcome, max_attempts, draft, feedback or "")


def check_draft(draft: Draft, scenario: Scenario) -> str:
    """Static checks 1-3. Returns the problem, or "" if the draft is fine."""
    try:
        ast.parse(draft.test_code)
    except SyntaxError as error:
        return f"The code doesn't parse: {error}"

    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "test_draft.py"
        test_file.write_text(draft.test_code, encoding="utf-8")
        try:
            claimed = sorted({ref.spec_id for ref in find_spec_refs([test_file])})
        except TestScanError as error:
            return str(error)
        if claimed != [scenario.id]:
            return (
                f'The test must claim exactly @pytest.mark.spec("{scenario.id}"); found {claimed}.'
            )

        tests = check_assertions([test_file]).tests
        if len(tests) != 1:
            return f"Write exactly one test function; found {len(tests)}."
        [test] = tests
        if test.strength is Strength.MISSING:
            return "The test has no assertions."
        if test.strength is Strength.WEAK:
            reasons = "; ".join(f"line {w.line}: {w.reason}" for w in test.weak)
            return f"Every assertion is weak ({reasons}). Assert the exact expected value."
    return ""


def run_draft(draft: Draft, target: Target) -> str:
    """Check 4: run the test with pytest. Returns the failure output, or ""."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "pytest.ini").write_text(_PYTEST_INI, encoding="utf-8")
        (Path(tmp) / "test_draft.py").write_text(draft.test_code, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(target.path.parent.resolve())}
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header", "test_draft.py"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SECONDS,
                check=False,  # a failing test is an answer, not an error
            )
        except subprocess.TimeoutExpired:
            return f"The test didn't finish within {RUN_TIMEOUT_SECONDS} seconds."
    if result.returncode == 0:
        return ""
    # The tail of pytest's output has the assertion diff, which is what matters.
    output = (result.stdout + result.stderr).strip().splitlines()
    return "The test fails against the code:\n" + "\n".join(output[-40:])


def write_outputs(results: Iterable[GeneratedTest], out_dir: Path) -> list[Path]:
    """Write kept tests as test_<id>.py, and needs-review ones aside.

    Needs-review files have no test_ prefix, so neither pytest nor the
    traceability gate picks them up until a human has looked at them.
    """
    written: list[Path] = []
    for result in results:
        if result.draft is None or result.outcome is Outcome.REJECTED:
            continue
        stem = result.scenario.id.lower().replace("-", "_")
        if result.outcome is Outcome.KEPT:
            path = out_dir / f"test_{stem}.py"
            header = (
                f"# Generated by specgate from {result.scenario.id}. Review before committing.\n"
            )
        else:
            path = out_dir / "needs_review" / f"{stem}_needs_review.py"
            header = (
                f"# Generated by specgate from {result.scenario.id}; FAILS against the code.\n"
                "# Decide whether the spec, the code or this test is wrong.\n"
            )
        if result.draft.assumptions:
            header += f"# Assumptions: {result.draft.assumptions}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + "\n" + result.draft.test_code.rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written


class ClaudeTestWriter:
    """TestWriter backed by Claude through the Anthropic SDK.

    The SDK finds credentials itself (ANTHROPIC_API_KEY in the environment,
    usually), so no key ever passes through specgate's code.
    """

    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        if client is None:
            import anthropic  # optional dependency: pip install -e ".[ai]"

            client = anthropic.Anthropic()
        self.model = model
        self.client = client

    def write(self, scenario: Scenario, target: Target, feedback: str | None) -> Draft:
        message = build_user_message(scenario, target.module_name, target.source, feedback)
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            # If a safety classifier declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason != "end_turn":
            raise GenerationError(f"{scenario.id}: model stopped with {response.stop_reason!r}")
        text = next(block.text for block in response.content if block.type == "text")
        reply = json.loads(text)
        return Draft(reply["test_code"], reply["assumptions"])
