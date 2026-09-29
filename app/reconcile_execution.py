"""Operator-only release of an unconfirmed entry after fresh exchange checks.

This command never submits, cancels, or closes an order. It refuses to release a
run unless the recorded CLOID is unknown and the account has no position,
open order, or fill since the attempted submission.
"""
import argparse
import time

from psycopg.types.json import Jsonb

from .candle_storage import _connect
from .execution_broker import Broker


MIN_AGE_MS = 60 * 1000


def verify_release(row, actions, order_status, positions, orders, fills, now_ms):
    state = row['state']
    if row['active'] or not row['managing'] or state.get('phase') != 'submitting':
        raise ValueError('A sessão não é uma entrada incerta com novas entradas paradas.')
    submitted_ms = state.get('submitted_ms')
    if type(submitted_ms) is not int or not MIN_AGE_MS <= now_ms - submitted_ms < 30 * 24 * 60 * 60 * 1000:
        raise ValueError('Aguarde 60 segundos após o envio para encerrar uma entrada sem execução.')
    if len(actions) != 1 or not actions[0]['action_key'].startswith('entry:') or actions[0]['status'] != 'pending' \
            or actions[0]['cloid'] != state.get('entry_cloid') or actions[0]['response'] is not None:
        raise ValueError('O journal não contém uma única entrada pendente correspondente ao CLOID.')
    if order_status.get('status') != 'unknownOid':
        raise ValueError('A corretora conhece a ordem; a sessão deve continuar em reconciliação.')
    if positions or orders:
        raise ValueError('Há posição ou ordem aberta na conta; não liberar a sessão.')
    if not isinstance(fills, list) or len(fills) >= 2000 or fills:
        raise ValueError('Há fills após o envio ou o histórico está incompleto; não liberar a sessão.')


def reconcile(run_id, release=False, broker_factory=Broker):
    with _connect() as conn:
        lock_key = run_id + 8_000_000_000
        locked = conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (lock_key,)).fetchone()['locked']
        if not locked:
            raise ValueError('Executor processando a sessão; tente novamente em alguns segundos.')
        try:
            row = conn.execute('SELECT * FROM hyperliquid_runs WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
            if row is None:
                raise ValueError('Sessão não encontrada.')
            if row['active'] or not row['managing'] or row['state'].get('phase') != 'submitting':
                raise ValueError('A sessão não é uma entrada incerta com novas entradas paradas.')
            if row['network'] != row['configuration'].get('network') or \
                    row['account_address'].lower() != row['configuration'].get('account_address', '').lower():
                raise ValueError('Conta ou rede divergente na configuração da sessão.')
            actions = conn.execute('SELECT action_key, status, cloid, response FROM hyperliquid_actions WHERE run_id=%s',
                                   (run_id,)).fetchall()
            broker = broker_factory(row['configuration'])
            def check_exchange():
                order_status = broker.lookup(row['state'].get('entry_cloid'))
                positions, orders, _, _ = broker.account(management=True)
                fills = broker.info.user_fills_by_time(broker.owner, row['state'].get('submitted_ms'))
                verify_release(row, actions, order_status, positions, orders, fills, int(time.time() * 1000))
            check_exchange()
            if release:
                # A second fresh snapshot catches delayed API visibility while the
                # executor is excluded by the session advisory lock.
                time.sleep(3)
                check_exchange()
                state = dict(row['state'])
                state.update(phase='waiting', pause_entries=True,
                             message='Entrada não encontrada na reconciliação operacional; sessão encerrada sem nova ordem.')
                conn.execute('UPDATE hyperliquid_runs SET active=FALSE, managing=FALSE, state=%s, '
                             'heartbeat=clock_timestamp() WHERE id=%s', (Jsonb(state), run_id))
            return 'Sessão liberada para uma nova ativação manual.' if release else 'Verificações concluídas; nenhuma alteração feita.'
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))


def main():
    parser = argparse.ArgumentParser(description='Reconcilia uma entrada incerta sem enviar ordens')
    parser.add_argument('run_id', type=int)
    parser.add_argument('--release', action='store_true', help='encerra a sessão somente se todas as verificações passarem')
    args = parser.parse_args()
    if args.run_id <= 0:
        parser.error('run_id precisa ser positivo')
    try:
        print(reconcile(args.run_id, args.release))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f'Reconciliação recusada: {exc}\n')


if __name__ == '__main__':
    main()
