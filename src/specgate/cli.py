"""Command line entry point: `specgate trace --specs DIR --tests DIR`.

Exit codes (what CI looks at):
  0  gate passed
  1  gate failed
  2  bad input (malformed spec, unreadable marker, bad arguments)
"""

import argparse
import sys
from collections.abc import Sequence

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

    args = parser.parse_args(argv)

    try:
        scenarios = load_specs(args.specs)
        refs = find_spec_refs(args.tests)
    except (SpecParseError, TestScanError, OSError, SyntaxError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_BAD_INPUT

    report = check_traceability(scenarios, refs)
    print(format_report(report))
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


if __name__ == "__main__":
    sys.exit(main())
