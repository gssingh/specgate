"""Stage 1: parse Markdown Given/When/Then specs into Scenario objects.

A spec file is ordinary Markdown. Every scenario starts with a heading that
carries a stable ID, followed by its steps:

    ## SYNC-001: New hire gets an account
    - Given an active HR record for "e100"
    - And no account exists for "e100"
    - When the sync runs
    - Then an account is created for "e100"

Anything else (prose, lists, tables, code blocks) is ignored, so specs can
stay readable documents rather than a rigid file format.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# IDs look like SYNC-001 or DISC-3: an uppercase prefix, a dash, a number.
SPEC_ID_PATTERN = r"[A-Z][A-Z0-9]*-\d+"

_SCENARIO_HEADING = re.compile(
    rf"^#{{2,6}}\s+(?P<id>{SPEC_ID_PATTERN})\s*:\s*(?P<title>.+?)\s*$"
)
_ANY_HEADING = re.compile(r"^#{1,6}\s")
_STEP = re.compile(r"^(?:[-*]\s+)?(?P<keyword>Given|When|Then|And|But)\s+(?P<text>.+?)\s*$")
_CODE_FENCE = re.compile(r"^(```|~~~)")

# Steps must appear in this order; And/But continue whichever came last.
_PHASES = ("Given", "When", "Then")


class SpecParseError(ValueError):
    """A spec file is malformed. The message points at file and line."""

    def __init__(self, source: Path, line: int, message: str):
        self.source = source
        self.line = line
        super().__init__(f"{source}:{line}: {message}")


@dataclass(frozen=True)
class Scenario:
    """One Given/When/Then scenario. Immutable, like a Java record."""

    id: str
    title: str
    given: tuple[str, ...]
    when: tuple[str, ...]
    then: tuple[str, ...]
    source: Path
    line: int


@dataclass
class _Draft:
    """Mutable builder used while a scenario is being read (Java: a Builder)."""

    id: str
    title: str
    source: Path
    line: int
    phase: str | None = None
    steps: dict[str, list[str]] = field(
        default_factory=lambda: {phase: [] for phase in _PHASES}
    )

    def add_step(self, keyword: str, text: str, line_no: int) -> None:
        if keyword in ("And", "But"):
            if self.phase is None:
                raise SpecParseError(
                    self.source, line_no, f"'{keyword}' must follow a Given, When or Then step"
                )
            keyword = self.phase
        elif self.phase and _PHASES.index(keyword) < _PHASES.index(self.phase):
            raise SpecParseError(
                self.source, line_no, f"'{keyword}' step cannot come after a '{self.phase}' step"
            )
        self.phase = keyword
        self.steps[keyword].append(text)

    def finish(self) -> Scenario:
        for required in ("When", "Then"):
            if not self.steps[required]:
                raise SpecParseError(
                    self.source, self.line, f"scenario {self.id} has no {required} step"
                )
        return Scenario(
            id=self.id,
            title=self.title,
            given=tuple(self.steps["Given"]),
            when=tuple(self.steps["When"]),
            then=tuple(self.steps["Then"]),
            source=self.source,
            line=self.line,
        )


def parse_spec(text: str, source: Path | str = "<string>") -> list[Scenario]:
    """Parse one Markdown document into its scenarios, in file order."""
    source = Path(source)
    scenarios: list[Scenario] = []
    draft: _Draft | None = None
    in_code_block = False

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if _CODE_FENCE.match(line):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if heading := _SCENARIO_HEADING.match(line):
            if draft:
                scenarios.append(draft.finish())
            draft = _Draft(heading["id"], heading["title"], source, line_no)
        elif _ANY_HEADING.match(line):
            # Any other heading (e.g. "## Notes") closes the current scenario.
            if draft:
                scenarios.append(draft.finish())
            draft = None
        elif step := _STEP.match(line):
            if draft is None:
                raise SpecParseError(
                    source, line_no, "step found outside a scenario; add a '## ID: title' heading"
                )
            draft.add_step(step["keyword"], step["text"], line_no)

    if draft:
        scenarios.append(draft.finish())
    _check_unique_ids(scenarios)
    return scenarios


def load_specs(paths: Iterable[Path | str]) -> list[Scenario]:
    """Parse every spec file under the given files or directories.

    IDs must be unique across all of them, not just within one file.
    """
    scenarios: list[Scenario] = []
    for spec_file in _markdown_files(paths):
        scenarios.extend(parse_spec(spec_file.read_text(encoding="utf-8"), spec_file))
    _check_unique_ids(scenarios)
    return scenarios


def _markdown_files(paths: Iterable[Path | str]) -> list[Path]:
    files: list[Path] = []
    for path in map(Path, paths):
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        else:
            files.append(path)
    return files


def _check_unique_ids(scenarios: list[Scenario]) -> None:
    first_seen: dict[str, Scenario] = {}
    for scenario in scenarios:
        if original := first_seen.get(scenario.id):
            raise SpecParseError(
                scenario.source,
                scenario.line,
                f"duplicate scenario ID {scenario.id} "
                f"(first defined at {original.source}:{original.line})",
            )
        first_seen[scenario.id] = scenario
