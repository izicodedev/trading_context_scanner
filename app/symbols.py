"""Market symbols supported throughout the scanner and paper simulator."""

SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_SYMBOL = SYMBOLS[0]


def validate_symbol(value: object) -> str:
    if not isinstance(value, str) or value not in SYMBOLS:
        raise ValueError("Moeda inválida. Escolha BTCUSDT ou ETHUSDT.")
    return value
