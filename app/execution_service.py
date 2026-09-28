"""Durable execution sessions and journal. No implicit activation."""
import hashlib
import os
import time
from dataclasses import asdict
from psycopg.types.json import Jsonb
from .candle_storage import _connect
from .strategy_research import candidates
from .execution_engine import step, ExecutionBlocked, EntryStopped
from .hyperliquid_setup import validate_limits


def enabled(network):
    return os.getenv('HYPERLIQUID_ENABLE_' + network.upper(), 'false').lower() == 'true'


def status(user_id):
    with _connect() as conn:
        row = conn.execute('SELECT id, network, active, managing, state, heartbeat FROM hyperliquid_runs WHERE user_id=%s ORDER BY id DESC LIMIT 1', (user_id,)).fetchone()
    if row and row['heartbeat']:
        row['heartbeat'] = row['heartbeat'].isoformat()
    return dict(run=row, mainnet_enabled=enabled('mainnet'), testnet_enabled=enabled('testnet'))


def activate(user_id):
    with _connect() as conn:
        row = conn.execute('SELECT * FROM hyperliquid_connections WHERE user_id=%s FOR UPDATE', (user_id,)).fetchone()
        if row is None or not row['encrypted_key'] or not row['risk_limits']:
            raise ExecutionBlocked('Cadastre carteira de API e limites primeiro.')
        if not enabled(row['network']):
            raise ExecutionBlocked('Execução nesta rede ainda não liberada no servidor. Falta validação operacional em testnet.')
        strategy = next((s for s in candidates() if s.key == row['strategy_key']), None)
        if strategy is None:
            raise ExecutionBlocked('Selecione uma estratégia.')
        config = dict(user_id=user_id, network=row['network'], account_address=row['account_address'], agent_address=row['agent_address'],
                      encrypted_key=row['encrypted_key'], limits=validate_limits(row['risk_limits']), strategy=asdict(strategy), started_ms=int(time.time() * 1000))
        from .execution_broker import Broker
        broker = Broker(config)
        broker.authorized()
        positions, orders, _, _ = broker.account()
        if positions or orders:
            raise ExecutionBlocked('Use uma conta sem posições nem ordens abertas para iniciar.')
        state = dict(phase='waiting', message='Aguardando novo fechamento de candle.', strategy=asdict(strategy))
        conn.execute('INSERT INTO hyperliquid_runs(user_id, network, account_address, configuration, state, active) VALUES(%s,%s,%s,%s,%s,TRUE)',
                     (user_id, row['network'], row['account_address'], Jsonb(config), Jsonb(state)))


def stop_entries(user_id):
    with _connect() as conn:
        conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE user_id=%s AND managing', (user_id,))


class Journal:
    def __init__(self, conn, run_id):
        self.conn, self.run_id = conn, run_id

    def cloid(self, key):
        return '0x' + hashlib.sha256(f'{self.run_id}:{key}'.encode()).hexdigest()[:32]

    def save(self, state):
        self.conn.execute('UPDATE hyperliquid_runs SET state=%s, heartbeat=clock_timestamp() WHERE id=%s', (Jsonb(state), self.run_id))
        self.conn.commit()

    def send(self, key, submit, payload):
        if key.startswith('entry:'):
            active = self.conn.execute('SELECT active FROM hyperliquid_runs WHERE id=%s', (self.run_id,)).fetchone()['active']
            if not active:
                raise EntryStopped('Novas entradas foram paradas antes do envio.')
        row = self.conn.execute('INSERT INTO hyperliquid_actions(run_id,action_key,cloid,request) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',
                                (self.run_id, key, self.cloid(key), Jsonb(payload))).fetchone()
        self.conn.commit()
        if row is None:
            raise ExecutionBlocked('Ação já registrada. Reenvio automático bloqueado.')
        result = submit(self.cloid(key), **payload)
        self.conn.execute("UPDATE hyperliquid_actions SET status='acknowledged', response=%s WHERE id=%s", (Jsonb(result), row['id']))
        self.conn.commit()
        return result

    def outcome(self, key):
        row = self.conn.execute('SELECT response FROM hyperliquid_actions WHERE run_id=%s AND action_key=%s', (self.run_id, key)).fetchone()
        return row['response'] if row else None


def tick(run_id, broker_factory=None):
    from .execution_broker import Broker
    with _connect() as conn:
        # Session-level lock survives journal commits. Different workers cannot send concurrently.
        locked = conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (run_id + 8_000_000_000,)).fetchone()['locked']
        if not locked:
            return
        try:
            row = conn.execute('SELECT * FROM hyperliquid_runs WHERE id=%s AND managing', (run_id,)).fetchone()
            if row is None:
                return
            state, config = row['state'], row['configuration']
            # Nonces are per signer, including across accounts and networks.
            signer_lock = int(hashlib.sha256(config['agent_address'].encode()).hexdigest()[:15], 16)
            signer_locked = conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (signer_lock,)).fetchone()['locked']
            if not signer_locked:
                return
            journal = Journal(conn, run_id)
            network_enabled = enabled(config['network'])
            if not network_enabled and state.get('phase') == 'waiting':
                state['message'] = 'Novas entradas bloqueadas no servidor.'
                journal.save(state)
                return
            try:
                broker = (broker_factory or Broker)(config)
                step(broker, journal, config, state, row['active'] and network_enabled)
                journal.save(state)  # Includes open/halted/wait paths that send no action.
                if state['phase'] == 'halted' or state.get('pause_entries'):
                    conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE id=%s', (run_id,))
                if (not row['active'] or state.get('pause_entries')) and state['phase'] == 'waiting':
                    conn.execute('UPDATE hyperliquid_runs SET managing=FALSE WHERE id=%s', (run_id,))
            except Exception as exc:
                conn.rollback()
                if isinstance(exc, EntryStopped):
                    state.update(phase='waiting', pause_entries=True)
                # Never log secrets, SDK payloads or raw transport errors.
                state['message'] = str(exc) if isinstance(exc, ExecutionBlocked) else 'Falha de comunicação ou processamento; nenhuma nova entrada permitida neste ciclo.'
                if state.get('phase') in ('submitting', 'protecting', 'closing'):
                    state['message'] += ' Confira imediatamente posição e proteções na Hyperliquid.'
                journal.save(state)
                if state.get('pause_entries'):
                    conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE id=%s', (run_id,))
                    if state['phase'] == 'waiting':
                        conn.execute('UPDATE hyperliquid_runs SET managing=FALSE WHERE id=%s', (run_id,))
            conn.commit()
        finally:
            if locals().get('signer_locked'):
                conn.execute('SELECT pg_advisory_unlock(%s)', (signer_lock,))
            conn.execute('SELECT pg_advisory_unlock(%s)', (run_id + 8_000_000_000,))
            conn.commit()


def main():
    while True:
        try:
            with _connect() as conn:
                rows = conn.execute('SELECT id FROM hyperliquid_runs WHERE managing ORDER BY id').fetchall()
            for row in rows:
                tick(row['id'])
        except Exception:
            print('Executor indisponível; verifique banco e conectividade.', flush=True)
        time.sleep(10)


if __name__ == '__main__':
    main()
