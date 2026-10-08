import pytest

from identity_sync import Account, Action, ActionKind, HrRecord, HrStatus, plan_sync

ACTIVE = HrStatus.ACTIVE
TERMINATED = HrStatus.TERMINATED


@pytest.mark.spec("SYNC-001")
def test_new_hire_gets_an_account():
    hr = [HrRecord("e100", ACTIVE, frozenset({"engineer"}))]

    assert plan_sync(hr, accounts=[]) == [
        Action(ActionKind.CREATE, "e100", frozenset({"engineer"}))
    ]


@pytest.mark.spec("SYNC-002")
def test_termination_disables_the_account():
    hr = [HrRecord("e200", TERMINATED)]
    accounts = [Account("e200", enabled=True, roles=frozenset({"engineer"}))]

    assert plan_sync(hr, accounts) == [Action(ActionKind.DISABLE, "e200")]


@pytest.mark.spec("SYNC-003")
def test_rehire_re_enables_the_existing_account():
    hr = [HrRecord("e300", ACTIVE, frozenset({"analyst"}))]
    accounts = [Account("e300", enabled=False, roles=frozenset({"engineer"}))]

    assert plan_sync(hr, accounts) == [
        Action(ActionKind.ENABLE, "e300"),
        Action(ActionKind.SET_ROLES, "e300", frozenset({"analyst"})),
    ]


@pytest.mark.spec("SYNC-004")
def test_role_change_updates_the_account():
    hr = [HrRecord("e400", ACTIVE, frozenset({"manager"}))]
    accounts = [Account("e400", enabled=True, roles=frozenset({"engineer"}))]

    assert plan_sync(hr, accounts) == [
        Action(ActionKind.SET_ROLES, "e400", frozenset({"manager"}))
    ]


@pytest.mark.spec("SYNC-005")
def test_conflicting_roles_are_flagged_not_applied():
    conflicting = frozenset({"payments_submitter", "payments_approver"})
    hr = [HrRecord("e500", ACTIVE, conflicting)]

    assert plan_sync(hr, accounts=[]) == [
        Action(ActionKind.FLAG_FOR_REVIEW, "e500", conflicting)
    ]


@pytest.mark.spec("SYNC-006")
def test_sync_is_idempotent():
    hr = [HrRecord("e600", ACTIVE, frozenset({"engineer"}))]
    accounts = [Account("e600", enabled=True, roles=frozenset({"engineer"}))]

    assert plan_sync(hr, accounts) == []
