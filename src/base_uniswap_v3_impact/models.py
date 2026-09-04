from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    address: str
    symbol: str
    decimals: int


@dataclass(frozen=True)
class PoolInfo:
    address: str
    token0: Token
    token1: Token
    fee: int
    liquidity: int
    sqrt_price_x96: int
    tick: int
