"""Explicit order intents, one position, no automatic retry after an uncertain send."""
from decimal import Decimal, ROUND_DOWN
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from .indicators import enrich
from .strategy_lab import Strategy, decision


class ExecutionBlocked(ValueError):
    pass


class EntryStopped(ExecutionBlocked):
    """Locally canceled before any entry request was persisted or sent."""
    pass


def terminal_status(status):
    return isinstance(status, str) and (status in {'filled', 'canceled', 'rejected', 'scheduledCancel'} or status.endswith(('Canceled', 'Rejected')))


def prepare_emergency_close(state, position, now, market='BTC'):
    """Turn a user-requested flatten into the existing reduce-only close flow."""
    if state.get('phase') not in {'submitting', 'protecting', 'open', 'halted'}:
        raise ExecutionBlocked('Não há posição gerenciada disponível para zeragem imediata.')
    if position is None:
        raise ExecutionBlocked(f'Nenhuma posição {market} aberta na Hyperliquid.')
    try:
        size = float(position['szi'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionBlocked(f'Posição {market} inválida; confira e zere pela Hyperliquid.') from exc
    expected = state.get('quantity', state.get('requested_quantity'))
    side = state.get('side')
    if not isinstance(state.get('entry_cloid'), str) or not isinstance(expected, (int, float)) or \
            not math.isfinite(expected) or expected <= 0 or \
            not math.isfinite(size) or size == 0 or side not in {'LONG', 'SHORT'} or \
            size * (1 if side == 'LONG' else -1) <= 0 or abs(size) > expected * (1 + 1e-8):
        raise ExecutionBlocked(f'Posição {market} divergente da sessão; confira e zere pela Hyperliquid.')
    settle_after = state.get('protection_settle_after', 0)
    if not isinstance(settle_after, (int, float)) or not math.isfinite(settle_after):
        settle_after = 0
    state.update(phase='closing', pause_entries=True, quantity=expected, next_close_at=0,
                 protection_cloids=state.get('protection_cloids', []),
                 protection_settle_after=max(settle_after, now + 60_000),
                 message='Zeragem solicitada; enviando ordem reduce-only e conferindo a posição restante.')
    return state


def finish_position(broker, journal, state):
    for cloid in state.get('protection_cloids', []):
        broker.cancel(cloid)
    state.update(phase='waiting', message='Posição zerada confirmada; proteções remanescentes canceladas.')
    state.pop('close_pending', None)
    journal.save(state)


def close_remaining(broker, journal, state, position, now, market='BTC'):
    """Reconcile each IOC before submitting another reduce-only order for the residual."""
    pending = state.get('close_pending')
    if pending:
        ack = journal.outcome(pending)
        confirmed = ack is not None and not ack.get('resting')
        if not confirmed:
            known = broker.lookup(journal.cloid(pending))
            record = known.get('order', {}) if known.get('status') == 'order' else {}
            confirmed = terminal_status(record.get('status'))
        if not confirmed:
            state['message'] = 'Saída ainda sem confirmação final; reconciliando sem reenviar.'
            journal.save(state)
            return
        # Re-read the position AFTER the order status, not the earlier account snapshot.
        positions = broker.get_positions()
        position = next((p for p in positions if p['coin'] == market), None)
        if ack and ack.get('filled', 0) > 0 and position is not None:
            expected_remaining = max(0, state.get('close_quantity', state['quantity']) - ack['filled'])
            if abs(float(position['szi'])) > expected_remaining + 1e-10:
                state['message'] = 'Saída confirmada; aguardando atualização da posição na corretora.'
                journal.save(state)
                return
        state.pop('close_pending', None)
    if position is None:
        if now < state.get('protection_settle_after', 0):
            state['message'] = 'Posição zerada; aguardando expiração de envios de proteção antes da limpeza.'
            journal.save(state)
            return
        finish_position(broker, journal, state)
        return
    size = float(position['szi'])
    expected_sign = 1 if state['side'] == 'LONG' else -1
    if not math.isfinite(size) or size * expected_sign <= 0 or abs(size) > state['quantity'] * (1 + 1e-8):
        state.update(phase='halted', pause_entries=True, message='Exposição divergente: intervenção externa detectada; confira a conta.')
        journal.save(state)
        return
    if now < state.get('next_close_at', 0):
        return
    broker.check_clock()
    attempt = state.get('close_attempt', 0) + 1
    key = f"close:{state['entry_cloid']}:{attempt}"
    state.update(phase='closing', close_pending=key, close_attempt=attempt,
                 close_quantity=abs(size), next_close_at=now + 10000, message='Enviando saída reduce-only para a quantidade restante.')
    journal.save(state)
    # Even a successful ack is reconciled on the next tick before cleanup or retry.
    journal.send(key, broker.close, dict(quantity=abs(size), buy=size < 0))
    state['message'] = 'Saída enviada; aguardando confirmação e conferência do saldo da posição.'
    journal.save(state)


def price_round(value, decimals):
    if not math.isfinite(value) or value <= 0:
        raise ExecutionBlocked('Preço inválido.')
    return round(float(f'{value:.5g}'), max(0, 6 - decimals))


def size_order(
    limits, strategy, equity, available, price, decimals, market_leverage,
    capital_reserved=None, max_utilization_pct=100, configured_leverage=None,
):
    if not all(math.isfinite(x) and x > 0 for x in (equity, available, price)):
        raise ExecutionBlocked('Saldo ou preço insuficiente.')
    leverage = min(int(limits['max_leverage']), strategy.leverage, int(market_leverage))
    if configured_leverage is not None:
        leverage = min(leverage, int(configured_leverage))
    budget = min(equity, available)
    if capital_reserved is not None:
        if not math.isfinite(capital_reserved) or capital_reserved <= 0:
            raise ExecutionBlocked('Capital reservado do bot precisa ser maior que zero.')
        budget = min(budget, capital_reserved)
    if not math.isfinite(max_utilization_pct) or not 0 < max_utilization_pct <= 100:
        raise ExecutionBlocked('Limite de utilização do bot inválido.')
    budget *= max_utilization_pct / 100
    if limits['sizing_mode'] == 'fixed':
        budget = min(budget, float(limits['capital_usdc']), float(limits['margin_per_trade_usdc']))
    # Reserve for two taker executions, adverse price movement and rounding.
    margin = budget / (1 + leverage * .004)
    qty = float(Decimal(str(margin * leverage / price)).quantize(Decimal(10) ** -decimals, rounding=ROUND_DOWN))
    if qty * price < 12:
        raise ExecutionBlocked('Saldo insuficiente para o mínimo operacional de 12 USDC.')
    return qty, leverage


def signal_from_candles(candles, strategy, now):
    rows = sorted((c for c in candles if int(c['T']) < now), key=lambda c: c['t'])
    if len(rows) < 61 or now - int(rows[-1]['T']) > 90_000:
        raise ExecutionBlocked('Candles da Hyperliquid ausentes ou atrasados.')
    if any(b['t'] - a['t'] != 300_000 for a, b in zip(rows, rows[1:])):
        raise ExecutionBlocked('Histórico da Hyperliquid contém lacunas.')
    frame = pd.DataFrame([dict(open=float(c['o']), high=float(c['h']), low=float(c['l']), close=float(c['c']), volume=float(c['v'])) for c in rows])
    if not all(math.isfinite(v) for v in frame.to_numpy().flat):
        raise ExecutionBlocked('Candles inválidos.')
    data = enrich(frame)
    return int(rows[-1]['T']), decision(strategy, data.iloc[-2], data.iloc[-1]), float(data.iloc[-1].atr)


def day_start(now):
    dt = datetime.fromtimestamp(now / 1000, ZoneInfo('America/Sao_Paulo'))
    return int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def daily_pnl(fills, funding, unrealized):
    if len(fills) >= 2000 or len(funding) >= 500:
        raise ExecutionBlocked('Histórico diário truncado; novas entradas bloqueadas.')
    if any(item.get('feeToken', 'USDC') != 'USDC' for item in fills):
        raise ExecutionBlocked('Taxa em moeda não suportada para o limite diário.')
    result = sum(float(f['closedPnl']) - float(f['fee']) for f in fills)
    result += sum(float(f['delta']['usdc']) for f in funding)
    result += unrealized
    if not math.isfinite(result):
        raise ExecutionBlocked('PnL diário inválido.')
    return result


def step(broker, journal, config, state, active, now=None):
    """Journal.save commits before each external action. Broker is injectable for tests."""
    now = now or int(time.time() * 1000)
    strategy = Strategy(**config['strategy'])
    limits = config['limits']
    market = config.get('market', 'BTC')
    # Always reconcile before new signals, including when entries have been stopped.
    phase = state.get('phase', 'waiting')
    if phase == 'halted':
        return state
    if phase in {'submitting', 'protecting', 'closing'}:
        positions, orders, equity, available = broker.get_positions(), [], 0, 0
    else:
        positions, orders, equity, available = broker.account(management=phase == 'open')
    if phase == 'waiting':
        state.update(balance_source=getattr(broker, 'balance_source', 'perps_usdc'), equity=equity, available_margin=available)
    position = next((p for p in positions if p['coin'] == market), None)
    if phase == 'submitting':
        state['pause_entries'] = True
        evidence = broker.entry_evidence(state['entry_cloid'], state.get('submitted_ms', config['started_ms']))
        if evidence is None:
            state['message'] = 'Entrada incerta; consultando ordem e fills. Novas entradas bloqueadas; confira a conta.'
            journal.save(state)
            return state
        if evidence['side'] != state['side'] or not math.isfinite(evidence['quantity']) or evidence['quantity'] < 0 or evidence['quantity'] > state.get('requested_quantity', float('inf')) * (1 + 1e-8):
            raise ExecutionBlocked('Lado da entrada divergente.')
        if evidence['quantity'] == 0:
            if position is None:
                state.update(phase='waiting', message='Ordem terminal sem preenchimento confirmado. Novas entradas paradas.')
            else:
                state.update(phase='halted', message='Posição sem preenchimento correspondente; confira a conta.')
            journal.save(state)
            return state
        state.update(phase='closing', quantity=evidence['quantity'], message='Preenchimento recuperado após falha; zerando exposição confirmada.')
        journal.save(state)
        positions = broker.get_positions()
        position = next((p for p in positions if p['coin'] == market), None)
        close_remaining(broker, journal, state, position, now, market)
        return state
    if phase == 'protecting':
        state.update(phase='closing', pause_entries=True, message='Proteção interrompida; zerando exposição confirmada.')
        journal.save(state)
        close_remaining(broker, journal, state, position, now, market)
        return state
    if phase == 'closing':
        close_remaining(broker, journal, state, position, now, market)
        return state
    if phase == 'open':
        if position is None:
            # Cancel only orders owned by this run. Cancellation retries are safe.
            finish_position(broker, journal, state)
            return state
        signed_qty = float(position['szi'])
        expected = state['quantity'] * (1 if state['side'] == 'LONG' else -1)
        if signed_qty * expected <= 0 or abs(signed_qty) > abs(expected) * (1 + 1e-8):
            state.update(phase='halted', message='Posição alterada fora do executor. Gestão automática bloqueada; confira as proteções.')
            journal.save(state)
            return state
        live_cloids = {o.get('cloid') for o in orders}
        missing = not set(state['protection_cloids']).issubset(live_cloids)
        if missing or now >= state['expires_at']:
            state.update(phase='closing', message='Fechamento por proteção ausente ou prazo máximo.')
            journal.save(state)
            close_remaining(broker, journal, state, position, now, market)
        return state
    if not active or state.get('pause_entries'):
        state.update(message='Novas entradas paradas.')
        journal.save(state)
        return state
    if positions or orders:
        raise ExecutionBlocked('Há posições ou ordens externas na conta. Nenhuma nova entrada será enviada.')
    broker.authorized()
    pnl = daily_pnl(*broker.daily(day_start(now)), 0)
    state['daily_pnl'] = pnl
    if pnl <= -float(limits['daily_loss_usdc']):
        raise ExecutionBlocked('Limite diário atingido. Novas entradas bloqueadas.')
    candles = broker.candles(now)
    closed_times = [int(c['T']) for c in candles if int(c['T']) < now]
    if closed_times and max(closed_times) <= state.get('last_candle', config['started_ms']):
        state['message'] = 'Candle já avaliado. Aguardando o próximo fechamento de 5 minutos.'
        journal.save(state)
        return state
    if closed_times and 90_000 < now - max(closed_times) <= 330_000:
        state['message'] = 'Janela de entrada deste candle encerrada. Aguardando novo fechamento de 5 minutos.'
        journal.save(state)
        return state
    candle, side, atr = signal_from_candles(candles, strategy, now)
    if candle <= state.get('last_candle', config['started_ms']):
        return state
    state['last_candle'] = candle
    state['message'] = 'Aguardando sinal no fechamento de 5 minutos.'
    journal.save(state)
    if not side:
        return state
    price, decimals, max_leverage = broker.market()
    qty, leverage = size_order(
        limits, strategy, equity, available, price, decimals, max_leverage,
        capital_reserved=config.get('capital_reserved'),
        max_utilization_pct=config.get('max_utilization_pct', 100),
        configured_leverage=config.get('configured_leverage'),
    )
    distance = max(strategy.stop_floor * price, atr * strategy.atr_multiple)
    if not math.isfinite(distance) or distance <= 0 or distance / price >= .8 / leverage:
        raise ExecutionBlocked('Stop incompatível com a alavancagem configurada.')
    try:
        broker.check_clock()
    except ExecutionBlocked:
        state['pause_entries'] = True
        journal.save(state)
        raise
    broker.leverage(leverage)
    entry_limit = price_round(price * (1.001 if side == 'LONG' else .999), decimals)
    cloid = journal.cloid('entry:' + str(candle))
    state.update(phase='submitting', entry_cloid=cloid, side=side, submitted_ms=now, requested_quantity=qty, message='Enviando entrada.')
    journal.save(state)
    try:
        result = journal.send('entry:' + str(candle), broker.entry,
                              dict(quantity=qty, buy=side == 'LONG', limit_price=entry_limit))
    except Exception as exc:
        # Keep only a safe diagnostic code; SDK exceptions may include signed payloads.
        diagnostic = {'type': type(exc).__name__}
        response_code = getattr(exc, 'code', None)
        if isinstance(response_code, str) and response_code in {
            'invalid_payload', 'exchange_error', 'status_count', 'invalid_status', 'invalid_fill', 'unknown_status'
        }:
            diagnostic['response_code'] = response_code
        response_detail = getattr(exc, 'detail', None)
        if isinstance(response_detail, str):
            diagnostic['exchange_message'] = response_detail
        status_code = getattr(exc, 'status_code', None)
        if type(status_code) is int and 400 <= status_code <= 599:
            diagnostic['http_status'] = status_code
        state['entry_error'] = diagnostic
        raise
    if result['filled'] == 0:
        if result.get('rejected'):
            state.update(phase='waiting', pause_entries=True,
                         message='Entrada rejeitada pela Hyperliquid; novas entradas paradas. Confira o relógio da VPS.')
            journal.save(state)
            return state
        if result.get('resting'):
            raise ExecutionBlocked('Entrada inesperadamente pendente. Confira a ordem na Hyperliquid.')
        state.update(phase='waiting', message='Entrada não executada.')
        journal.save(state)
        return state
    qty, entry = result['filled'], result['price']
    if not all(math.isfinite(v) and v > 0 for v in (qty, entry)):
        raise ExecutionBlocked('Execução com preço ou quantidade inválidos.')
    sign = 1 if side == 'LONG' else -1
    stop = price_round(entry - sign * distance, decimals)
    target = price_round(entry + sign * distance * strategy.reward_risk, decimals)
    state.update(phase='protecting', quantity=qty, entry_price=entry, stop=stop, target=target,
                 expires_at=now + strategy.max_candles * 300_000, protection_cloids=[], close_attempt=0, next_close_at=0)
    journal.save(state)
    # Both protective orders are reduce-only; a failure never permits another entry.
    for kind, trigger in [('sl', stop), ('tp', target)]:
        key = kind + ':' + cloid
        state['protection_cloids'].append(journal.cloid(key))
        state['protection_settle_after'] = now + 60000
        journal.save(state)
        result = journal.send(key, broker.protect, dict(quantity=qty, buy=side != 'LONG', trigger=trigger, kind=kind))
        if not result.get('resting'):
            state.update(phase='closing', pause_entries=True, message='Proteção rejeitada; tentando zerar a posição.')
            journal.save(state)
            positions = broker.get_positions()
            position = next((p for p in positions if p['coin'] == market), None)
            close_remaining(broker, journal, state, position, now, market)
            return state
        journal.save(state)
    state.update(phase='open', message='Posição aberta com stop e alvo na Hyperliquid.')
    journal.save(state)
    return state
