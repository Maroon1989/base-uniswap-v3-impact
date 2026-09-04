from __future__ import annotations

import unittest
from decimal import Decimal, getcontext

from base_uniswap_v3_impact.models import Token
from base_uniswap_v3_impact.uniswap_v3 import decode_swap_log, price_quote_per_base

getcontext().prec = 80
Q96 = Decimal(2) ** 96


def word(value: int) -> str:
    if value < 0:
        value += 2**256
    return f"{value:064x}"


def sqrt_price(price_usdc_per_weth: str) -> int:
    raw = Decimal(price_usdc_per_weth) * (Decimal(10) ** -12)
    return int(Q96 * raw.sqrt())


class UniswapV3MathTest(unittest.TestCase):
    def test_decode_swap_log_signed_values(self) -> None:
        log = {
            "address": "0x1111111111111111111111111111111111111111",
            "blockNumber": 10,
            "transactionHash": "0x" + "aa" * 32,
            "transactionIndex": 3,
            "logIndex": 4,
            "topics": [
                "0x" + "00" * 32,
                "0x" + "00" * 12 + "12" * 20,
                "0x" + "00" * 12 + "34" * 20,
            ],
            "data": "0x" + word(-10**18) + word(2_000_000_000) + word(sqrt_price("2000")) + word(123456) + word(-1),
        }
        decoded = decode_swap_log(log)
        self.assertEqual(decoded.amount0, -10**18)
        self.assertEqual(decoded.amount1, 2_000_000_000)
        self.assertEqual(decoded.tick, -1)
        self.assertEqual(decoded.sender, "0x" + "12" * 20)

    def test_price_quote_per_base_for_weth_usdc(self) -> None:
        token0 = Token("0xweth", "WETH", 18)
        token1 = Token("0xusdc", "USDC", 6)
        price = price_quote_per_base(sqrt_price("2000"), token0, token1)
        self.assertAlmostEqual(float(price), 2000.0, places=6)


if __name__ == "__main__":
    unittest.main()
