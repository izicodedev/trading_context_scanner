import pytest

from app.reconcile_execution import MIN_AGE_MS, verify_release


NOW = 2_000_000_000_000
CLOID = '0x' + 'a' * 32


def evidence():
    row = {'active': False, 'managing': True,
           'state': {'phase': 'submitting', 'submitted_ms': NOW - MIN_AGE_MS - 1, 'entry_cloid': CLOID}}
    actions = [{'action_key': 'entry:123', 'status': 'pending', 'cloid': CLOID, 'response': None}]
    return row, actions, {'status': 'unknownOid'}, [], [], []


def test_release_requires_unknown_order_and_flat_account():
    verify_release(*evidence(), NOW)
    for index, replacement in ((2, {'status': 'order'}), (3, [{'coin': 'BTC', 'szi': '0.01'}]),
                               (4, [{'coin': 'BTC'}]), (5, [{'coin': 'BTC', 'sz': '0.01'}])):
        args = list(evidence())
        args[index] = replacement
        with pytest.raises(ValueError):
            verify_release(*args, NOW)


def test_release_requires_stopped_run_old_attempt_and_matching_pending_journal():
    for change in ('active', 'managing', 'recent', 'wrong_cloid', 'acknowledged', 'extra_action'):
        row, actions, order, positions, orders, fills = evidence()
        if change == 'active': row['active'] = True
        elif change == 'managing': row['managing'] = False
        elif change == 'recent': row['state']['submitted_ms'] = NOW - MIN_AGE_MS + 1
        elif change == 'wrong_cloid': actions[0]['cloid'] = '0x' + 'b' * 32
        elif change == 'acknowledged': actions[0]['status'] = 'acknowledged'
        else: actions.append(dict(actions[0]))
        with pytest.raises(ValueError):
            verify_release(row, actions, order, positions, orders, fills, NOW)
