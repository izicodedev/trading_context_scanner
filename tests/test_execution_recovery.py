import pytest
from test_execution_engine import Broker, Journal, config
from app.execution_engine import step
from app import execution_service


def closing():
    return dict(phase='closing',side='LONG',quantity=.01,entry_cloid='entry',protection_cloids=['sl','tp'])


def test_uncertain_entry_recovers_known_fill_and_exits_without_duplicate():
    b,j=Broker(),Journal()
    b.positions=[dict(coin='BTC',szi='.005')]
    b.entry_evidence=lambda *args: dict(quantity=.005,side='LONG')
    state=dict(phase='submitting',side='LONG',entry_cloid='entry',requested_quantity=.01)
    step(b,j,config(),state,False,2000)
    assert state['phase']=='closing' and state['pause_entries']
    step(b,j,config(),state,False,14000)
    assert state['phase']=='waiting'
    assert [kind for kind,_ in b.sent]==['close']


def test_partial_close_retries_only_remaining_after_confirmation():
    b,j=Broker(),Journal(); state=closing()
    b.positions=[dict(coin='BTC',szi='.01')]
    def partial(cloid, **payload):
        b.sent.append(('close',payload))
        filled=payload['quantity']/2
        b.positions=[dict(coin='BTC',szi=str(filled))]
        return dict(filled=filled)
    b.close=partial
    step(b,j,config(),state,False,1000)
    assert len(b.sent)==1
    step(b,j,config(),state,False,12000)
    assert [p['quantity'] for _,p in b.sent]==[.01,.005]
    assert len(j.keys)==2 and state['phase']=='closing'


def test_close_timeout_does_not_retry_until_order_terminal():
    b,j=Broker(),Journal(); state=closing()
    b.positions=[dict(coin='BTC',szi='.01')]
    def timeout(*args,**kwargs): raise TimeoutError()
    b.close=timeout
    with pytest.raises(TimeoutError): step(b,j,config(),state,False,1000)
    step(b,j,config(),state,False,20000)
    assert len(j.keys)==1 and 'sem confirmação' in state['message']
    b.lookup=lambda cloid: dict(status='order',order=dict(status='canceled'))
    b.close=lambda cloid,**kwargs: dict(filled=kwargs['quantity'],resting=False)
    step(b,j,config(),state,False,30000)
    assert len(j.keys)==2


def test_stale_position_after_ack_does_not_repeat_close():
    b,j=Broker(),Journal(); state=closing()
    b.positions=[dict(coin='BTC',szi='.01')]
    b.close=lambda cloid,**kwargs: dict(filled=.01)
    step(b,j,config(),state,False,1000)
    step(b,j,config(),state,False,20000)
    assert len(j.keys)==1 and 'atualização' in state['message']


def test_partial_protective_exit_keeps_remaining_managed():
    b,j=Broker(),Journal()
    b.positions=[dict(coin='BTC',szi='.005')]
    b.orders=[dict(cloid='sl'),dict(cloid='tp')]
    state=closing()|dict(phase='open',expires_at=999999)
    step(b,j,config(),state,False,1000)
    assert state['phase']=='open' and not b.sent


def test_flat_account_does_not_finish_unconfirmed_close():
    b,j=Broker(),Journal()
    state=closing()|dict(close_pending='pending')
    step(b,j,config(),state,False,1000)
    assert state['phase']=='closing' and 'sem confirmação' in state['message']
    assert not b.sent


def test_recovered_position_never_closes_external_larger_exposure():
    b,j=Broker(),Journal()
    b.positions=[dict(coin='BTC',szi='.02')]
    b.entry_evidence=lambda *args: dict(quantity=.005,side='LONG')
    state=dict(phase='submitting',side='LONG',entry_cloid='entry',requested_quantity=.01)
    step(b,j,config(),state,False,1000)
    assert state['phase']=='halted' and not b.sent


def test_stop_before_submission_does_not_create_journal_or_send():
    from app.execution_engine import EntryStopped
    class Connection:
        def execute(self,sql,params):
            assert sql.startswith('SELECT active')
            return self
        def fetchone(self):return dict(active=False)
    with pytest.raises(EntryStopped):
        execution_service.Journal(Connection(),1).send('entry:1',lambda *a:pytest.fail('must not send'),{})


@pytest.mark.parametrize('phase',['open','halted'])
def test_worker_heartbeats_even_without_state_transition(monkeypatch,phase):
    from contextlib import contextmanager
    state=dict(phase=phase)
    row=dict(state=state,configuration=dict(network='testnet',agent_address='agent'),active=False)
    class Connection:
        def execute(self,sql,params):
            self.sql=sql
            return self
        def fetchone(self):
            return {'locked':True} if 'pg_try' in self.sql else row
        def commit(self): pass
        def rollback(self): pass
    @contextmanager
    def connect(): yield Connection()
    saves=[]
    monkeypatch.setattr(execution_service,'_connect',connect)
    monkeypatch.setattr(execution_service,'enabled',lambda network:True)
    monkeypatch.setattr(execution_service,'step',lambda *args:None)
    monkeypatch.setattr(execution_service.Journal,'save',lambda self,state:saves.append(state.copy()))
    execution_service.tick(1,broker_factory=lambda c:object())
    assert saves and saves[-1]['phase']==phase
