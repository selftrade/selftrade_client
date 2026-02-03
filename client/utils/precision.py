# client/utils/precision.py - Exchange-specific precision handling
from decimal import Decimal, ROUND_DOWN
from typing import Dict

from client.config import PRECISION_RULES


def get_step_size(exchange: str, symbol: str, type: str = 'qty') -> float:
    """
    Get step size for a symbol on an exchange.

    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        type: 'qty' for quantity, 'price' for price

    Returns:
        Step size value
    """
    precision = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES['binance'])
    symbol_rules = precision.get(symbol.upper(), precision.get('DEFAULT', {'price': 6, 'qty': 2}))

    decimals = symbol_rules.get(type, 2)
    return 10 ** (-decimals)


def round_quantity(exchange: str, symbol: str, quantity: float) -> float:
    """
    Round quantity to exchange-specific precision.

    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        quantity: Raw quantity value

    Returns:
        Rounded quantity
    """
    step_size = get_step_size(exchange, symbol, 'qty')
    precision = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES['binance'])
    symbol_rules = precision.get(symbol.upper(), precision.get('DEFAULT', {'qty': 2}))
    decimals = symbol_rules.get('qty', 2)

    # Use Decimal for precise rounding
    d_qty = Decimal(str(quantity))
    d_step = Decimal(str(step_size))

    # Round down to step size
    rounded = float((d_qty / d_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * d_step)

    return rounded


def round_price(exchange: str, symbol: str, price: float) -> float:
    """
    Round price to exchange-specific precision.

    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        price: Raw price value

    Returns:
        Rounded price
    """
    step_size = get_step_size(exchange, symbol, 'price')
    precision = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES['binance'])
    symbol_rules = precision.get(symbol.upper(), precision.get('DEFAULT', {'price': 6}))
    decimals = symbol_rules.get('price', 6)

    # Use Decimal for precise rounding
    d_price = Decimal(str(price))
    d_step = Decimal(str(step_size))

    # Round down to step size
    rounded = float((d_price / d_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * d_step)

    return rounded


def format_quantity(exchange: str, symbol: str, quantity: float) -> str:
    """
    Format quantity as string with proper precision.

    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        quantity: Quantity value

    Returns:
        Formatted string
    """
    precision = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES['binance'])
    symbol_rules = precision.get(symbol.upper(), precision.get('DEFAULT', {'qty': 2}))
    decimals = symbol_rules.get('qty', 2)

    rounded = round_quantity(exchange, symbol, quantity)
    return f"{rounded:.{decimals}f}"


def format_price(exchange: str, symbol: str, price: float) -> str:
    """
    Format price as string with proper precision.

    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        price: Price value

    Returns:
        Formatted string
    """
    precision = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES['binance'])
    symbol_rules = precision.get(symbol.upper(), precision.get('DEFAULT', {'price': 6}))
    decimals = symbol_rules.get('price', 6)

    rounded = round_price(exchange, symbol, price)
    return f"{rounded:.{decimals}f}"
