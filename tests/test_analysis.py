from __future__ import annotations

import unittest
from decimal import Decimal, getcontext
from pathlib import Path
from tempfile import TemporaryDirectory

from base_uniswap_v3_impact.analyze import enrich_swaps, load_swap_rows, pool_tokens_from_row
from base_uniswap_v3_impact.db import connect, load_pool_row, upsert_pool
from base_uniswap_v3_impact.models import PoolInfo, Token

getcontext().prec = 80
Q96 = Decimal(2) ** 96


def sqrt_price(price_usdc_per_weth: str) -> int:
    raw = Decimal(price_usdc_per_weth) * (Decimal(10) ** -12)
    return int(Q96 * raw.sqrt())


class AnalysisEnrichmentTest(unittest.TestCase):
    def test_impact_uses_previous_post_swap_price(self) -> None:
        with TemporaryDirectory() as td:
            conn = connect(Path(td) / "swaps.db")
            pool = PoolInfo(
                address="0x1111111111111111111111111111111111111111",
                token0=Token("0x4200000000000000000000000000000000000006", "WETH", 18),
                token1=Token("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "USDC", 6),
                fee=500,
                liquidity=10**18,
                sqrt_price_x96=sqrt_price("2000"),
                tick=0,
            )
            upsert_pool(conn, pool, "synthetic test")
            data = [
                (1, "0xaaa", 0, str(10**18), str(-2000 * 10**6), str(sqrt_price("1999"))),
                (2, "0xbbb", 1, str(-10**18), str(2005 * 10**6), str(sqrt_price("2001"))),
            ]
            for block, tx_hash, tx_index, amount0, amount1, sqrtp in data:
                conn.execute(
                    """
                    INSERT INTO swaps(
                      pool_address, block_number, block_timestamp, tx_hash, tx_index, log_index,
                      sender, recipient, amount0_raw, amount1_raw, sqrt_price_x96, liquidity, tick
                    ) VALUES (?, ?, ?, ?, ?, 0, '0xs', '0xr', ?, ?, ?, ?, 0)
                    """,
                    (pool.address, block, 1700000000 + block, tx_hash, tx_index, amount0, amount1, sqrtp, str(10**18)),
                )
            conn.commit()

            pool_tokens = pool_tokens_from_row(load_pool_row(conn))
            enriched = enrich_swaps(load_swap_rows(conn, pool.address), pool_tokens, "WETH", "USDC")

            self.assertEqual(enriched[0]["direction"], "sell_base")
            self.assertIsNone(enriched[0]["price_impact_pct"])
            self.assertEqual(enriched[1]["direction"], "buy_base")
            self.assertAlmostEqual(float(enriched[1]["price_impact_pct"]), 0.300150075, places=6)


if __name__ == "__main__":
    unittest.main()
