from dataclasses import asdict
import pytest
from app import execution_engine as engine
from app.strategy_research import candidates
from app.execution_broker import parse_order
from app import execution_service


def config():
    return dict(strategy=asdict(candidates()[24]), started_ms=1,
                limits=dict(sizing_mode='available_balance', max_leverage='5', daily_loss_usdc='10'))


class Broker:
    positions = []
    orders = []
    def __init__(self): self.sent = []; self.fail = None; self.positions = []; self.orders = []
    def account(self): return self.positions, self.orders, 100, 80
    def authorized(self): pass
    def daily(self, since): return [], []
    def candles(self, now): return []
    def market(self): return 10000, 5, 40
    def leverage(self, leverage): self.sent.append(('leverage', leverage))
    def entry(self, cloid, **args):
        self.sent.append(('entry', args))
        if self.fail == 'entry': raise TimeoutError()
        self.positions = [dict(coin='BTC', szi=str(args['quantity'] / 2 * (1 if args['buy'] else -1)))]
        return dict(filled=args['quantity'] / 2, price=10000)
    def protect(self, cloid, **args):
        self.sent.append(('protect', args))
        return dict(resting=self.fail != 'protection', filled=0)
    def close(self, cloid, **args):
        self.sent.append(('close', args))
        self.positions = []
        return dict(filled=args['quantity'])
    def lookup(self, cloid): return {'status': 'unknownOid'}
    def entry_evidence(self, cloid, since): return None
    def cancel(self, cloid): self.sent.append(('cancel', cloid))


class Journal:
    def __init__(self): self.saved = []; self.keys = set(); self.results = {}
    def cloid(self, key): return key
    def save(self, state): self.saved.append(dict(state))
    def send(self, key, method, payload):
        assert key not in self.keys
        self.keys.add(key)
        result = method(self.cloid(key), **payload)
        self.results[key] = result
        return result
    def outcome(self, key): return self.results.get(key)


@pytest.fixture
def signal(monkeypatch):
    monkeypatch.setattr(engine, 'signal_from_candles', lambda *args: (1000, 'LONG', 20))


def test_reserve_rounding_and_compounding():
    c = config(); s = engine.Strategy(**c['strategy'])
    qty, lev = engine.size_order(c['limits'], s, 100, 80, 10000, 5, 40)
    assert qty * 10000 / lev < 80
    bigger, _ = engine.size_order(c['limits'], s, 200, 160, 10000, 5, 40)
    assert bigger > qty
    c['limits'].update(sizing_mode='fixed', capital_usdc='50', margin_per_trade_usdc='10')
    fixed, _ = engine.size_order(c['limits'], s, 200, 160, 10000, 5, 40)
    assert fixed * 10000 / lev < 10


def test_partial_entry_protected_at_actual_fill_and_state_persisted(signal):
    b, j, state = Broker(), Journal(), {'phase':'waiting'}
    engine.step(b,j,config(),state,True,2000)
    assert state['phase'] == 'open'
    entry = next(p for kind,p in b.sent if kind=='entry')
    protective = [p for kind,p in b.sent if kind=='protect']
    assert len(protective)==2 and all(p['quantity']==entry['quantity']/2 for p in protective)
    assert j.saved[1]['phase']=='submitting'
    assert any(s['phase']=='protecting' for s in j.saved)


def test_timeout_never_resends(signal):
    b,j,state = Broker(),Journal(),{'phase':'waiting'}
    b.fail='entry'
    with pytest.raises(TimeoutError): engine.step(b,j,config(),state,True,2000)
    assert state['phase']=='submitting'
    engine.step(b,j,config(),state,True,3000)
    assert state['phase']=='submitting' and state['pause_entries']
    assert sum(kind=='entry' for kind,_ in b.sent)==1


def test_rejected_protection_sends_reduce_close_and_halts(signal):
    b,j,state=Broker(),Journal(),{'phase':'waiting'}
    b.fail='protection'
    engine.step(b,j,config(),state,True,2000)
    assert state['phase']=='closing'
    assert any(kind=='close' for kind,_ in b.sent)


def test_stop_entries_keeps_existing_position_managed():
    b,j=Broker(),Journal()
    b.positions=[dict(coin='BTC',szi='0.01')]
    b.orders=[dict(cloid='sl'),dict(cloid='tp')]
    state=dict(phase='open',side='LONG',quantity=.01,entry_cloid='entry',protection_cloids=['sl','tp'],expires_at=100)
    engine.step(b,j,config(),state,False,200)
    assert state['phase']=='closing'
    engine.step(b,j,config(),state,False,12000)
    assert state['phase']=='waiting'
    assert b.sent[0][0]=='close'


def test_external_exposure_blocks_entry(signal):
    b=Broker(); b.positions=[dict(coin='ETH',szi='1')]
    with pytest.raises(engine.ExecutionBlocked): engine.step(b,Journal(),config(),{'phase':'waiting'},True,2000)
    assert not b.sent


def test_daily_limit_blocks_entry(signal):
    b=Broker(); b.daily=lambda since: ([dict(closedPnl='-9',fee='2')], [])
    with pytest.raises(engine.ExecutionBlocked, match='diário'): engine.step(b,Journal(),config(),{'phase':'waiting'},True,2000)
    assert not b.sent


def test_malformed_order_ack_is_not_success():
    with pytest.raises(engine.ExecutionBlocked): parse_order({'status':'ok'})
    assert parse_order({'status':'ok','response':{'data':{'statuses':[{'error':'rejected'}]}}})['filled']==0


def test_networks_disabled_by_default(monkeypatch):
    monkeypatch.delenv('HYPERLIQUID_ENABLE_MAINNET',raising=False)
    monkeypatch.delenv('HYPERLIQUID_ENABLE_TESTNET',raising=False)
    assert not execution_service.enabled('mainnet') and not execution_service.enabled('testnet')


def test_interrupted_protection_attempts_emergency_close_once():
    b,j=Broker(),Journal()
    b.positions=[dict(coin='BTC',szi='.01')]
    state=dict(phase='protecting',side='LONG',quantity=.01,entry_cloid='entry',protection_cloids=[])
    engine.step(b,j,config(),state,False,2000)
    assert state['phase']=='closing'
    engine.step(b,j,config(),state,False,3000)
    assert state['phase']=='waiting'
    assert sum(kind=='close' for kind,_ in b.sent)==1


def test_native_candles_and_staleness():
    rows=[dict(t=i*300000,T=(i+1)*300000-1,o=str(100+i),h=str(102+i),l=str(99+i),c=str(101+i),v='100') for i in range(100)]
    candle, side, atr=engine.signal_from_candles(rows,engine.Strategy(**config()['strategy']),30000000)
    assert candle==29999999 and atr>0
    with pytest.raises(engine.ExecutionBlocked,match='atrasados'):
        engine.signal_from_candles(rows,engine.Strategy(**config()['strategy']),30100000)
    with pytest.raises(engine.ExecutionBlocked,match='lacunas'):
        engine.signal_from_candles(rows[:40]+rows[41:],engine.Strategy(**config()['strategy']),30000000)


def test_already_processed_candle_waits_without_false_staleness():
    b,j=Broker(),Journal()
    b.candles=lambda now:[dict(T=1000)]
    state=dict(phase='waiting',last_candle=1000)
    engine.step(b,j,config(),state,True,200000)
    assert 'já avaliado' in state['message']
    assert not b.sent


def test_late_unprocessed_candle_does_not_trigger_entry():
    b,j=Broker(),Journal()
    b.candles=lambda now:[dict(T=1000)]
    state=dict(phase='waiting')
    engine.step(b,j,config(),state,True,200000)
    assert 'Janela de entrada' in state['message']
    assert not b.sent


def test_sdk_protection_and_close_are_reduce_only():
    from app.execution_broker import Broker as SdkBroker
    class Exchange:
        def __init__(self): self.orders=[]
        def set_expires_after(self, value): pass
        def order(self,*args,**kwargs):
            self.orders.append((args,kwargs))
            return {'status':'ok','response':{'data':{'statuses':[{'resting':{'oid':1}}]}}}
    broker=SdkBroker.__new__(SdkBroker)
    broker.exchange=Exchange()
    broker.market=lambda: (10000,5,40)
    cloid='0x'+'a'*32
    broker.protect(cloid,.01,False,9900,'sl')
    broker.close(cloid,.01,False)
    assert all(kwargs['reduce_only'] is True for _,kwargs in broker.exchange.orders)
    assert broker.exchange.orders[0][0][4]['trigger']['tpsl']=='sl'
