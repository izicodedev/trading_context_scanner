"""Read-only collateral selection; never transfers funds or changes account mode."""
import math


def trading_balance(mode, perps, spot=None):
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Saldo inválido retornado pela Hyperliquid.')
        return result
    if mode == 'unifiedAccount':
        if not isinstance(spot, dict):
            raise ValueError('Saldo da conta unificada indisponível.')
        usdc = next((b for b in spot['balances'] if b['token'] == 0 and b['coin'] == 'USDC'), None)
        if usdc is None:
            return 0., 0., 'unified_usdc'
        total, held = number(usdc['total']), number(usdc['hold'])
        # This value accounts for maintenance requirements across the unified account.
        available = next((v for token, v in spot.get('tokenToAvailableAfterMaintenance', []) if token == 0), None)
        if available is None:
            raise ValueError('Margem disponível da conta unificada não informada pela Hyperliquid.')
        return max(0., total), max(0., min(total - max(0., held), number(available))), 'unified_usdc'
    if mode in ('disabled', 'default', 'dexAbstraction'):
        return max(0., number(perps['marginSummary']['accountValue'])), max(0., number(perps['withdrawable'])), 'perps_usdc'
    raise ValueError('Modo de margem não suportado pelo executor: nenhuma entrada será enviada.')
