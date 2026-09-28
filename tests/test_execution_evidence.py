import pytest
from app.execution_broker import Broker
from app.execution_engine import ExecutionBlocked


def broker(status='filled', fills=None):
    b=Broker.__new__(Broker);b.owner='owner'
    b.lookup=lambda cloid:dict(status='order',order=dict(status=status,order=dict(coin='BTC',cloid=cloid,oid=7,side='B')))
    class Info:
        def user_fills_by_time(self,owner,since): return fills or []
    b.info=Info()
    return b


def test_fills_deduplicated_and_unrelated_orders_ignored():
    fill=dict(tid=1,oid=7,coin='BTC',sz='.01')
    b=broker(fills=[fill,fill,dict(tid=2,oid=8,coin='BTC',sz='2')])
    assert b.entry_evidence('cloid',0)==dict(quantity=.01,side='LONG')


def test_filled_order_waits_for_fill_history_consistency():
    assert broker().entry_evidence('cloid',0) is None


def test_nonterminal_entry_waits():
    assert broker(status='open').entry_evidence('cloid',0) is None


def test_canceled_without_fills_is_confirmed_zero():
    assert broker(status='canceled').entry_evidence('cloid',0)['quantity']==0


def test_foreign_order_identity_rejected():
    b=broker(); b.lookup=lambda c:dict(status='order',order=dict(status='filled',order=dict(coin='ETH',cloid=c)))
    with pytest.raises(ExecutionBlocked):b.entry_evidence('cloid',0)
