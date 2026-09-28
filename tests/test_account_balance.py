import pytest
from app.account_balance import trading_balance
from app.execution_broker import Broker


def perps():
    return dict(marginSummary={'accountValue':'0'}, withdrawable='0', assetPositions=[])


def spot(total='58.914823', hold='0', available='58.914823'):
    return dict(balances=[dict(coin='USDC',token=0,total=total,hold=hold)], tokenToAvailableAfterMaintenance=[[0,available]])


def test_unified_uses_spot_not_zero_perps():
    assert trading_balance('unifiedAccount',perps(),spot()) == (58.914823,58.914823,'unified_usdc')


def test_holds_and_maintenance_are_not_spendable():
    assert trading_balance('unifiedAccount',perps(),spot('100','30','80'))[1]==70
    assert trading_balance('unifiedAccount',perps(),spot('100','10','60'))[1]==60


def test_standard_does_not_spend_spot():
    assert trading_balance('disabled',perps(),spot())==(0,0,'perps_usdc')


@pytest.mark.parametrize('data', [dict(balances=spot()['balances']),spot(available='NaN')])
def test_missing_or_nonfinite_available_blocks(data):
    with pytest.raises(ValueError): trading_balance('unifiedAccount',perps(),data)


def test_portfolio_mode_not_silently_treated_as_unified():
    with pytest.raises(ValueError): trading_balance('portfolioMargin',perps(),spot())


def test_broker_reads_unified_collateral_without_exchange_actions():
    class Info:
        def user_state(self,owner): return perps()
        def query_user_abstraction_state(self,owner): return 'unifiedAccount'
        def spot_user_state(self,owner): return spot()
        def frontend_open_orders(self,owner): return []
    b=Broker.__new__(Broker); b.info=Info(); b.owner='test'
    assert b.account()==([],[],58.914823,58.914823)
