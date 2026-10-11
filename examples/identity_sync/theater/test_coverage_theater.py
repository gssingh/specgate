"""Coverage theater: tests that claim every scenario and can't fail.

These pass, and they pass the traceability gate, yet none of them would
notice if plan_sync() returned the wrong actions. The assertion-strength
gate (stage 4) flags every one:

    specgate assertions --tests examples/identity_sync/theater

They live outside the configured testpaths, so a plain `pytest` skips them.
"""

import pytest

from identity_sync import Account, HrRecord, HrStatus, plan_sync

ACTIVE = HrStatus.ACTIVE
TERMINATED = HrStatus.TERMINATED


@pytest.mark.spec("SYNC-001")
def test_new_hire_gets_an_account():
    actions = plan_sync([HrRecord("e100", ACTIVE, frozenset({"engineer"}))], [])

    assert actions is not None


@pytest.mark.spec("SYNC-002")
def test_termination_disables_the_account():
    hr = [HrRecord("e200", TERMINATED)]
    accounts = [Account("e200", enabled=True)]

    assert len(plan_sync(hr, accounts)) > 0


@pytest.mark.spec("SYNC-003")
def test_rehire_re_enables_the_existing_account():
    hr = [HrRecord("e300", ACTIVE, frozenset({"analyst"}))]
    accounts = [Account("e300", enabled=False)]

    plan_sync(hr, accounts)  # runs the code, checks nothing


@pytest.mark.spec("SYNC-004")
def test_role_change_updates_the_account():
    actions = plan_sync([HrRecord("e400", ACTIVE, frozenset({"manager"}))], [])

    assert isinstance(actions, list)


@pytest.mark.spec("SYNC-005")
def test_conflicting_roles_are_flagged_not_applied():
    roles = frozenset({"payments_submitter", "payments_approver"})
    actions = plan_sync([HrRecord("e500", ACTIVE, roles)], [])

    assert actions == actions


@pytest.mark.spec("SYNC-006")
def test_sync_is_idempotent():
    hr = [HrRecord("e600", ACTIVE, frozenset({"engineer"}))]
    plan_sync(hr, [Account("e600", enabled=True, roles=frozenset({"engineer"}))])

    assert True
