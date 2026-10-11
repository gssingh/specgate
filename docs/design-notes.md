# Design notes

Why the code looks the way it does, and the Java idea each piece maps to.

## Project setup

| Choice | Why | Java equivalent |
|---|---|---|
| `pyproject.toml` | The one standard place for build config, dependencies, tool settings | `pom.xml` / `build.gradle` |
| `hatchling` build backend | Small, zero-config builder for pure-Python packages | Maven jar plugin |
| `src/` layout | Tests run against the installed package, not loose files in the repo root, so packaging mistakes show up in tests | `src/main/java` vs `src/test/java` |
| `pip install -e .` | "Editable" install: the package points at your source, edits apply without reinstalling | Running from your IDE's classpath |
| `[project.scripts]` | Creates the `specgate` command that calls `specgate.cli:main` | `Main-Class` in a jar manifest |
| pytest | Plain `assert` statements, fixtures by argument name, markers for metadata | JUnit 5 (`@Tag` ~ marker, `@ParameterizedTest` ~ `parametrize`, `@TempDir` ~ `tmp_path`) |
| `--strict-markers` | A typo like `@pytest.mark.spce` fails instead of being silently ignored | Compile error on an unknown annotation |

## Stage 1: spec parser (`spec.py`)

- **Format.** A scenario is any heading of the form `## ID: title`. Steps are
  lines starting with Given/When/Then/And/But (bullets optional). Everything
  else is ignored, so a spec stays a readable document.
- **Rules enforced.** Unique IDs across all spec files; every scenario has a
  When and a Then (a scenario with no outcome can't be tested); steps go
  Given then When then Then; And/But must follow a real step; a step outside
  a scenario is an error (usually a missing ID heading).
- **Fail fast.** The parser raises on the first problem with `file:line`.
  Collecting every error is nicer but more code; easy to add later.
- **`Scenario` is a frozen dataclass.** Equivalent to a Java `record`:
  generated constructor, `equals`, `hashCode`, `toString`, no setters.
  Steps are tuples (immutable lists) so the whole object stays immutable.
- **`_Draft` is a mutable builder** used only while reading lines, then
  `finish()` validates and produces the immutable `Scenario`. Same shape as
  the Builder pattern.
- **Regex with named groups** (`(?P<id>...)`, then `match["id"]`) is
  `java.util.regex` with named groups.
- **`:=` (walrus)** assigns inside a condition:
  `if heading := PATTERN.match(line):` is
  `Matcher m = ...; if (m.matches()) { ... }` in one line.

## Stage 3: traceability gate (`traceability.py`)

- **Static scan, not a pytest plugin.** We parse test files with Python's
  `ast` module and look for `@pytest.mark.spec(...)` decorators, without
  importing or running anything. That makes the gate fast, safe to run on
  untrusted AI-written code, and immune to import errors. Java equivalent:
  JavaParser reading annotations from source, rather than reflection at
  runtime. Stage 4 (assertion strength) reuses the same approach.
- **What counts.** Markers on `test*` functions, `Test*` classes, and
  `test*` methods inside them, matching pytest's default naming. A marker
  on a helper function is ignored, because pytest would never run it.
- **Marker arguments must be string literals.** `spec(SOME_CONSTANT)` is
  rejected: we can't know its value without running code, and a gate that
  guesses isn't deterministic.
- **Known gaps.** Module-level `pytestmark = pytest.mark.spec(...)` and
  markers added via `pytest.param(..., marks=...)` aren't read yet.
- **Report.** `TraceabilityReport` holds covered IDs, uncovered scenarios
  and unknown IDs; `passed` is a computed property (a getter with no field).

## Stage 4: assertion-strength gate (`assertions.py`)

- **The problem.** A test can claim `SYNC-001`, run `plan_sync()`, and then
  `assert actions is not None`. It passes, traceability passes, and it would
  still pass if the code returned completely wrong actions. That's coverage
  theater, and AI-generated tests do it a lot.
- **Rule: one strong assertion per test.** Each `assert`, `pytest.raises`
  and `assert*` method call is graded strong or weak. A test passes if at
  least one is strong. Weak ones in a passing test are still listed, but
  don't fail the gate: `assert x is not None` before `assert x == expected`
  is a normal guard.
- **What's weak.** Constants (`assert True`), self-comparison (`x == x`),
  bare truthiness (`assert result`), `is not None`, type checks
  (`isinstance`, `hasattr`, `callable`), "non-empty" length checks
  (`len(x) > 0`, and the always-true `len(x) >= 0`), `pytest.raises(Exception)`
  without `match=`, and `assertTrue` / `assertIsNotNone` / `assertIsInstance`
  / `assert_called` / `assert_called_once`. Everything else is strong.
- **Three verdicts.** `Strength` is an `Enum`: `STRONG`, `WEAK` (only weak
  assertions) and `MISSING` (none at all), because "asserts badly" and
  "doesn't assert" need different fixes.
- **Heuristics on purpose.** This gate is cheap and fast but can be fooled
  (`assert result == compute(result)` looks strong). Stage 5 (mutation
  testing) is the expensive gate that measures whether tests catch bugs.
  Stage 4 exists to fail obviously useless tests in milliseconds, before
  paying for mutation runs.
- **Known gaps.** Assertions inside helper functions the test calls aren't
  followed, so `check_result(x)` counts as no assertion. `ok = validate(x);
  assert ok` is flagged as truthiness-only even though `ok` is a real bool;
  `assert validate(x)` is fine.
- **Structural pattern matching.** `match test: case ast.Compare(left=l,
  ops=[op], comparators=[r]): ...` checks the node's type and pulls out its
  fields in one step. It's Java 21's `switch` with record patterns
  (`case Compare(var l, var op, var r) ->`). `ops=[op]` only matches a
  list of exactly one element, so chained comparisons like `a < b < c`
  fall through to "strong".
- **`ast.walk`** visits every node in the test function, including nested
  blocks (`with`, `if`, loops). Java equivalent: a JavaParser
  `VoidVisitorAdapter` that overrides `visit(AssertStmt)` and
  `visit(MethodCallExpr)`.
- **`ast.dump(left) == ast.dump(right)`** compares two expressions by
  structure, ignoring line numbers. Like comparing two JavaParser nodes
  with `equals()`, which also ignores position.
- **Sharing with stage 3.** `find_test_files` and `find_spec_refs` come from
  `traceability.py`, so both gates see the same files and the report can
  show which spec IDs a weak test claims.

## CLI (`cli.py`)

- `argparse` with subcommands so later stages slot in as `specgate mutate`
  etc. Similar to picocli subcommands.
- `main()` returns an exit code instead of calling `sys.exit` itself, which
  makes it testable: tests call `main([...])` and check the number.
- Exit codes: `0` pass, `1` gate failed, `2` bad input. CI only needs to
  look at the exit code.
- `specgate assertions --tests DIR` runs stage 4 with the same exit codes.

## Example target (`examples/identity_sync`)

- `plan_sync()` is a pure function: data in, list of `Action`s out, no I/O.
  Applying the actions (calling an identity system) is deliberately out of
  scope, which keeps tests simple and is a good fit for mutation testing.
- `Enum` classes map directly to Java enums. `frozenset` is an immutable
  `Set` (like `Set.of(...)`), and `pair <= roles` is `roles.containsAll(pair)`.
- A role conflict blocks every other action for that person, including
  account creation. Granting partial access before a human reviews felt
  wrong for an identity system.
