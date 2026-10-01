"""Durable execution sessions and journal. No implicit activation."""
import hashlib
import math
import os
import time
from dataclasses import asdict
from psycopg.types.json import Jsonb
from .candle_storage import _connect
from .strategy_research import real_execution_candidates
from .execution_engine import step, prepare_emergency_close, ExecutionBlocked, EntryStopped
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
        strategy = next((s for s in real_execution_candidates() if s.key == row['strategy_key']), None)
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


def activate_bot(user_id, bot_id):
    from .hyperliquid_bot_service import RuntimeQueryError, get_bot_realized_lifetime_pnl

    with _connect() as conn:
        bot = conn.execute(
            """
            SELECT b.*, c.account_address AS connection_master, c.network AS connection_network
            FROM hyperliquid_bots b
            JOIN hyperliquid_connections c ON c.user_id = b.user_id
            WHERE b.user_id=%s AND b.id=%s
            FOR UPDATE OF b
            """,
            (user_id, bot_id),
        ).fetchone()
        if bot is None:
            raise ExecutionBlocked('Robô não encontrado ou conta principal não configurada.')
        if (
            not isinstance(bot['master_address'], str)
            or not isinstance(bot['connection_master'], str)
            or bot['master_address'].lower() != bot['connection_master'].lower()
            or bot['network'] != bot['connection_network']
        ):
            raise ExecutionBlocked('A wallet principal ou a rede do robô não corresponde à conexão salva.')
        if not enabled(bot['network']):
            raise ExecutionBlocked('Execução nesta rede ainda não foi liberada no servidor.')
        if not bot['agent_address'] or not bot['encrypted_key']:
            raise ExecutionBlocked('Cadastre a chave privada da API deste robô antes de iniciar.')
        existing_run = conn.execute(
            """
            SELECT id, configuration FROM hyperliquid_runs
            WHERE user_id=%s AND bot_id=%s AND managing
            ORDER BY created_at DESC, id DESC LIMIT 1
            FOR UPDATE
            """,
            (user_id, bot_id),
        ).fetchone()
        if existing_run is not None:
            if bot['status'] != 'paused':
                raise ExecutionBlocked('Este robô já possui uma sessão em gerenciamento; confira a posição e o estado antes de iniciar.')
            from .execution_broker import Broker
            Broker(existing_run['configuration']).authorized()
            conn.execute(
                "UPDATE hyperliquid_runs SET active=TRUE WHERE id=%s",
                (existing_run['id'],),
            )
            conn.execute(
                "UPDATE hyperliquid_bots SET status='running', is_active=TRUE, updated_at=NOW() WHERE id=%s AND user_id=%s",
                (bot_id, user_id),
            )
            return existing_run['id']
        strategy = next((item for item in real_execution_candidates() if item.key == bot['strategy_key']), None)
        if strategy is None:
            raise ExecutionBlocked('Selecione uma estratégia de execução disponível para este robô.')

        risk_limits = bot['risk_limits'] if isinstance(bot['risk_limits'], dict) else {}
        try:
            initial_bankroll = float(bot['capital_reserved'])
            daily_loss = float(risk_limits.get('daily_loss_usdc'))
            configured_leverage = float(bot['leverage'])
            requested_leverage = float(risk_limits.get('max_leverage', configured_leverage))
            fixed_margin = float(risk_limits.get('margin_per_trade_usdc', 0))
        except (TypeError, ValueError):
            raise ExecutionBlocked('Banca, alavancagem e limites de risco devem estar configurados.') from None
        if not math.isfinite(initial_bankroll) or initial_bankroll <= 0:
            raise ExecutionBlocked('Informe uma banca inicial maior que zero para este robô.')
        if not math.isfinite(daily_loss) or daily_loss <= 0:
            raise ExecutionBlocked('Configure um limite de perda diária maior que zero para este robô.')
        if (
            not math.isfinite(configured_leverage)
            or not math.isfinite(requested_leverage)
            or not requested_leverage.is_integer()
            or not 1 <= requested_leverage <= 40
        ):
            raise ExecutionBlocked('A alavancagem máxima configurada é inválida.')
        max_leverage = min(configured_leverage, requested_leverage)
        if bot['sizing_mode'] == 'fixed' and (not math.isfinite(fixed_margin) or fixed_margin <= 0):
            raise ExecutionBlocked('Configure o valor fixo por entrada deste robô.')

        bot_runtime = {
            'network': bot['network'],
            'master_address': bot['master_address'],
            'account_address': bot['account_address'],
            'created_at': bot['created_at'].isoformat() if bot['created_at'] else None,
        }
        try:
            realized = get_bot_realized_lifetime_pnl(bot_runtime)
        except RuntimeQueryError as exc:
            raise ExecutionBlocked('Não foi possível confirmar a subconta e o histórico realizado deste robô.') from exc
        current_bankroll = initial_bankroll + realized
        if not math.isfinite(current_bankroll) or current_bankroll <= 0:
            raise ExecutionBlocked('A banca atual do robô está zerada ou indisponível; nenhuma entrada pode ser iniciada.')

        limits = {
            'sizing_mode': bot['sizing_mode'],
            'capital_usdc': str(current_bankroll),
            'margin_per_trade_usdc': str(fixed_margin),
            'max_leverage': str(max_leverage),
            'daily_loss_usdc': str(daily_loss),
        }
        config = dict(
            user_id=user_id,
            bot_id=bot_id,
            network=bot['network'],
            master_address=bot['master_address'],
            account_address=bot['account_address'],
            agent_address=bot['agent_address'],
            encrypted_key=bot['encrypted_key'],
            market=bot['market'],
            limits=limits,
            strategy=asdict(strategy),
            capital_reserved=initial_bankroll,
            max_utilization_pct=100,
            configured_leverage=int(max_leverage),
            bot_runtime=bot_runtime,
            started_ms=int(time.time() * 1000),
        )
        try:
            from .hyperliquid_bot_service import bot_service
            bot_service._verify_subaccount(bot_runtime, bot['account_address'].lower())
        except RuntimeQueryError as exc:
            raise ExecutionBlocked('A subconta configurada não pertence à wallet principal deste robô.') from exc
        from .execution_broker import Broker
        broker = Broker(config)
        broker.authorized()
        positions, orders, _, _ = broker.account()
        if positions or orders:
            raise ExecutionBlocked('Use uma subconta sem posições nem ordens abertas para iniciar este robô.')
        state = dict(phase='waiting', message='Aguardando novo fechamento de candle.', strategy=asdict(strategy))
        run = conn.execute(
            """
            INSERT INTO hyperliquid_runs(
                user_id, network, account_address, bot_id, configuration, state, active
            )
            VALUES (%s,%s,%s,%s,%s,%s,TRUE)
            RETURNING id
            """,
            (user_id, bot['network'], bot['account_address'], bot_id, Jsonb(config), Jsonb(state)),
        ).fetchone()
        conn.execute(
            "UPDATE hyperliquid_bots SET status='running', is_active=TRUE, updated_at=NOW() WHERE id=%s AND user_id=%s",
            (bot_id, user_id),
        )
        return run['id']


def stop_entries(user_id):
    with _connect() as conn:
        conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE user_id=%s AND managing', (user_id,))


def emergency_close(user_id):
    """User-initiated BTC flatten. The worker uses its durable reduce-only journal."""
    from .execution_broker import Broker
    with _connect() as conn:
        row = conn.execute('SELECT id FROM hyperliquid_runs WHERE user_id=%s AND managing ORDER BY id DESC LIMIT 1',
                           (user_id,)).fetchone()
        if row is None:
            raise ExecutionBlocked('Nenhuma sessão em gerenciamento.')
        run_id = row['id']
        lock_key = run_id + 8_000_000_000
        if not conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (lock_key,)).fetchone()['locked']:
            raise ExecutionBlocked('Executor processando esta sessão; tente novamente em instantes.')
        try:
            row = conn.execute('SELECT * FROM hyperliquid_runs WHERE id=%s AND user_id=%s AND managing FOR UPDATE',
                               (run_id, user_id)).fetchone()
            if row is None:
                raise ExecutionBlocked('Sessão não encontrada ou já encerrada.')
            # Persist the stop before any external lookup, even if the lookup fails.
            conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE id=%s', (run_id,))
            conn.commit()
            broker = Broker(row['configuration'])
            positions = broker.get_positions()
            position = next((p for p in positions if p['coin'] == 'BTC'), None)
            state = prepare_emergency_close(dict(row['state']), position, int(time.time() * 1000))
            conn.execute('UPDATE hyperliquid_runs SET active=FALSE, state=%s, heartbeat=clock_timestamp() WHERE id=%s',
                         (Jsonb(state), run_id))
            conn.commit()
        finally:
            conn.rollback()
            conn.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
    tick(run_id)


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
                if config.get('bot_id') is not None and row['active'] and state.get('phase') == 'waiting':
                    from .hyperliquid_bot_service import RuntimeQueryError, get_bot_realized_lifetime_pnl
                    try:
                        realized = get_bot_realized_lifetime_pnl(config['bot_runtime'])
                    except RuntimeQueryError as exc:
                        raise ExecutionBlocked('Histórico realizado indisponível; novas entradas pausadas por segurança.') from exc
                    current_bankroll = float(config['capital_reserved']) + realized
                    if not math.isfinite(current_bankroll) or current_bankroll <= 0:
                        raise ExecutionBlocked('A banca atual do robô está zerada; novas entradas bloqueadas.')
                    config['capital_reserved'] = current_bankroll
                    config['limits']['capital_usdc'] = str(current_bankroll)
                step(broker, journal, config, state, row['active'] and network_enabled)
                state.pop('last_error', None)
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
                state['last_error'] = str(exc) if isinstance(exc, ExecutionBlocked) else 'Falha de comunicação ou processamento neste ciclo.'
                state['message'] = state['last_error']
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
