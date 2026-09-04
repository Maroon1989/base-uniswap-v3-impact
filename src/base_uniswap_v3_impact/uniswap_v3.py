from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any

from .models import Token

getcontext().prec = 80

Q96 = Decimal(2) ** 96
SWAP_EVENT_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


@dataclass(frozen=True)
class DecodedSwap:
    pool_address: str
    block_number: int
    transaction_hash: str
    transaction_index: int
    log_index: int
    sender: str
    recipient: str
    amount0: int
    amount1: int
    sqrt_price_x96: int
    liquidity: int
    tick: int


def _hex(value: Any) -> str:
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if hasattr(value, "hex"):
        h = value.hex()
        return h if h.startswith("0x") else f"0x{h}"
    raise TypeError(f"Cannot convert {value!r} to hex")


def _address_from_topic(topic: Any) -> str:
    return "0x" + _hex(topic)[-40:]


def _signed_256(word_hex: str) -> int:
    value = int(word_hex, 16)
    if value >= 2**255:
        value -= 2**256
    return value


def _unsigned(word_hex: str) -> int:
    return int(word_hex, 16)


def decode_swap_log(log: Any) -> DecodedSwap:
    data = _hex(log["data"])[2:]
    words = [data[i : i + 64] for i in range(0, len(data), 64)]
    if len(words) != 5:
        raise ValueError(f"Swap log has {len(words)} data words, expected 5")
    topics = log["topics"]
    return DecodedSwap(
        pool_address=log["address"],
        block_number=int(log["blockNumber"]),
        transaction_hash=_hex(log["transactionHash"]),
        transaction_index=int(log.get("transactionIndex", 0)),
        log_index=int(log["logIndex"]),
        sender=_address_from_topic(topics[1]),
        recipient=_address_from_topic(topics[2]),
        amount0=_signed_256(words[0]),
        amount1=_signed_256(words[1]),
        sqrt_price_x96=_unsigned(words[2]),
        liquidity=_unsigned(words[3]),
        tick=_signed_256(words[4]),
    )


def decimal_amount(raw_amount: int | str, decimals: int) -> Decimal:
    return Decimal(int(raw_amount)) / (Decimal(10) ** decimals)


def price_token1_per_token0(sqrt_price_x96: int | str, token0_decimals: int, token1_decimals: int) -> Decimal:
    raw_price = (Decimal(int(sqrt_price_x96)) / Q96) ** 2
    return raw_price * (Decimal(10) ** (token0_decimals - token1_decimals))


def price_quote_per_base(
    sqrt_price_x96: int | str,
    token0: Token,
    token1: Token,
    base_symbol: str = "WETH",
    quote_symbol: str = "USDC",
) -> Decimal:
    token1_per_token0 = price_token1_per_token0(sqrt_price_x96, token0.decimals, token1.decimals)
    token0_is_base = token0.symbol.upper() == base_symbol.upper()
    token1_is_base = token1.symbol.upper() == base_symbol.upper()
    token0_is_quote = token0.symbol.upper() == quote_symbol.upper()
    token1_is_quote = token1.symbol.upper() == quote_symbol.upper()

    if token0_is_base and token1_is_quote:
        return token1_per_token0
    if token1_is_base and token0_is_quote:
        return Decimal(1) / token1_per_token0
    raise ValueError(
        f"Pool tokens {token0.symbol}/{token1.symbol} do not match requested "
        f"base/quote {base_symbol}/{quote_symbol}"
    )
