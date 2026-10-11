"""Command line entry point.

    specgate trace --specs DIR --tests DIR     stage 3: traceability
    specgate assertions --tests DIR            stage 4: assertion strength

Exit codes (what CI looks at):
  0  gate passed
  1  gate failed
  2  bad input (malformed spec, unreadable marker, bad arguments)
"""

import argparse
import sys
from collections.abc import Sequence

from specgate.assertions import AssertionReport, Strength, check_assertions
from specgate.spec import SpecParseError, load_specs
from specgate.traceability import (
    TestScanError,
    TraceabilityReport,
    check_traceability,
    find_spec_refs,
)

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2  # argparse also uses 2 for usage errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specgate")
    commands = parser.add_subparsers(dest="command", required=True)

    trace = commands.add_parser("trace", help="check every spec ID has a test and vice versa")
    trace.add_argument("--specs", nargs="+", required=True, help="spec files or directories")
    trace.add_argument("--tests", nargs="+", required=True, help="test files or directories")

    assertions = commands.add_parser(
        "assertions", help="check every test asserts something that can fail"
    )
    assertions.add_argument("--tests", nargs="+", required=True, help="test files or directories")

    args = parser.parse_args(argv)
    if args.command == "assertions":
        return _run_assertions(args)
    return _run_trace(args)


def _run_trace(args: argparse.Namespace) -> int:
    try:
        scenarios = load_specs(args.specs)
        refs = find_spec_refs(args.tests)
    except (SpecParseError, TestScanError, OSError, SyntaxError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_BAD_INPUT

    report = check_traceability(scenarios, refs)
    print(format_report(report))
    return EXIT_PASSED if report.passed else EXIT_FAILED


def _run_assertions(args: argparse.Namespace) -> int:
    try:
        report = check_assertions(args.tests)
    except (TestScanError, OSError, SyntaxError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_BAD_INPUT

    print(format_assertion_report(report))
    return EXIT_PASSED if report.passed else EXIT_FAILED


def format_report(report: TraceabilityReport) -> str:
    total = len(report.covered) + len(report.uncovered)
    lines = [
        f"Traceability: {'PASS' if report.passed else 'FAIL'}",
        f"  {len(report.covered)}/{total} scenarios covered by tests",
    ]
    if report.uncovered:
        lines.append("  Scenarios with no test:")
        for scenario in report.uncovered:
            lines.append(
                f"    {scenario.id}  {scenario.title}  ({scenario.source}:{scenario.line})"
            )
    if report.unknown:
        lines.append("  Tests claiming IDs no spec defines:")
        for ref in report.unknown:
            lines.append(f"    {ref.spec_id}  {ref.node_id}  (line {ref.line})")
    return "\n".join(lines)


def format_assertion_report(report: AssertionReport) -> str:
    strong = len(report.tests) - len(report.failing)
    lines = [
        f"Assertion strength: {'PASS' if report.passed else 'FAIL'}",
        f"  {strong}/{len(report.tests)} tests have a strong assertion",
    ]
    for test in report.failing:
        claims = f"  [{', '.join(test.spec_ids)}]" if test.spec_ids else ""
        lines.append(f"    {test.strength.value.upper()}  {test.node_id}{claims}")
        if test.strength is Strength.MISSING:
            lines.append("      no assertions")
        for weak in test.weak:
            lines.append(f"      line {weak.line}: {weak.reason}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
