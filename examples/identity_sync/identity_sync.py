"""Fictional identity provisioning sync: the example target specgate tests.

Compares HR records with identity accounts and plans the actions needed to
make the accounts match HR. Pure function, no I/O, so it's easy to test.
"""

from dataclasses import dataclass
from enum import Enum

# Separation-of-duties rules: nobody may hold both roles in a pair.
CONFLICTING_ROLES: tuple[frozenset[str], ...] = (
    frozenset({"payments_submitter", "payments_approver"}),
)


class HrStatus(Enum):
    ACTIVE = "active"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class HrRecord:
    employee_id: str
    status: HrStatus
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Account:
    employee_id: str
    enabled: bool
    roles: frozenset[str] = frozenset()


class ActionKind(Enum):
    CREATE = "create"
    DISABLE = "disable"
    ENABLE = "enable"
    SET_ROLES = "set_roles"
    FLAG_FOR_REVIEW = "flag_for_review"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    employee_id: str
    roles: frozenset[str] = frozenset()


def plan_sync(hr_records: list[HrRecord], accounts: list[Account]) -> list[Action]:
    """Return the actions that bring accounts in line with HR, in input order."""
    accounts_by_id = {account.employee_id: account for account in accounts}
    actions: list[Action] = []
    for record in hr_records:
        actions.extend(_plan_one(record, accounts_by_id.get(record.employee_id)))
    return actions


def _plan_one(record: HrRecord, account: Account | None) -> list[Action]:
    employee = record.employee_id

    if record.status is HrStatus.TERMINATED:
        if account and account.enabled:
            return [Action(ActionKind.DISABLE, employee)]
        return []

    if conflict := _find_conflict(record.roles):
        # Don't grant anything until a human resolves the conflict.
        return [Action(ActionKind.FLAG_FOR_REVIEW, employee, conflict)]

    if account is None:
        return [Action(ActionKind.CREATE, employee, record.roles)]

    actions: list[Action] = []
    if not account.enabled:
        actions.append(Action(ActionKind.ENABLE, employee))
    if account.roles != record.roles:
        actions.append(Action(ActionKind.SET_ROLES, employee, record.roles))
    return actions


def _find_conflict(roles: frozenset[str]) -> frozenset[str] | None:
    for pair in CONFLICTING_ROLES:
        if pair <= roles:  # subset check: roles contains both of the pair
            return pair
    return None
