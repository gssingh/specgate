"""The words stage 2 sends to the model, kept apart from the code that sends them.

The system prompt holds the rules, which are the same for every scenario.
The user message holds what changes: one scenario, the code under test,
and (on a retry) what was wrong with the previous attempt.
"""

from specgate.spec import Scenario

SYSTEM_PROMPT = """\
You write one pytest test for one behaviour scenario. The scenario is the \
source of truth; the module source shows you the real names and types.

Rules:
- Write exactly one test function whose name starts with test_.
- Decorate it with @pytest.mark.spec("<scenario ID>") using the ID you are given, \
and no other ID.
- Import only pytest and names from the module under test. No mocks, no network, \
no files, no randomness, no sleeping.
- Build the state the Given steps describe, call the code once for the When step, \
then assert what every Then step says.
- Assert exact expected values, for example `assert result == [Action(...)]`. \
Never settle for `is not None`, `isinstance`, `len(x) > 0`, bare truthiness or \
`pytest.raises(Exception)`; those can't tell right from wrong.
- If the scenario and the code seem to disagree, test what the scenario says. \
Do not adjust expectations to match the code.
- Put everything the spec leaves open that you had to decide in `assumptions`, \
in one or two plain sentences. Use an empty string if there were none.

Return `test_code` as a complete Python file: imports first, then the test."""

# JSON schema for structured output. The API guarantees the reply matches it,
# so we never have to scrape code out of Markdown fences.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "test_code": {"type": "string"},
        "assumptions": {"type": "string"},
    },
    "required": ["test_code", "assumptions"],
    "additionalProperties": False,
}


def build_user_message(
    scenario: Scenario, module_name: str, module_source: str, feedback: str | None = None
) -> str:
    steps = "\n".join(
        [f"Given {step}" for step in scenario.given]
        + [f"When {step}" for step in scenario.when]
        + [f"Then {step}" for step in scenario.then]
    )
    message = (
        f"Scenario {scenario.id}: {scenario.title}\n"
        f"{steps}\n\n"
        f"Module under test, imported as `{module_name}`:\n"
        f"```python\n{module_source}\n```"
    )
    if feedback:
        message += (
            "\n\nYour previous test for this scenario was rejected:\n"
            f"{feedback}\n"
            "Write a corrected test."
        )
    return message
