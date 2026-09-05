from __future__ import annotations

import unittest
from decimal import Decimal, getcontext

from base_uniswap_v3_impact.advanced_insights import add_fee_adjusted_metrics

getcontext().prec = 80


class FeeAdjustedSlippageTest(unittest.TestCase):
    def test_buy_extra_cost_uses_fee_only_reference(self) -> None:
        rows = [
            {
                "pre_price_usdc_per_weth": Decimal("2000"),
                "execution_price_usdc_per_weth": Decimal("2003"),
                "base_amount": Decimal("1"),
                "quote_amount": Decimal("2003"),
                "direction": "buy_base",
                "post_price_change_pct": Decimal("0.1"),
            }
        ]

        enriched = add_fee_adjusted_metrics(rows, pool_fee=500)[0]

        fee_only_price = Decimal("2000") / Decimal("0.9995")
        expected_cost = Decimal("2003") - fee_only_price
        self.assertAlmostEqual(float(enriched["extra_slippage_usd"]), float(expected_cost), places=12)
        self.assertAlmostEqual(
            float(enriched["extra_slippage_bps"]),
            float(expected_cost / Decimal("2003") * Decimal("10000")),
            places=12,
        )

    def test_sell_extra_cost_uses_fee_only_reference(self) -> None:
        rows = [
            {
                "pre_price_usdc_per_weth": Decimal("2000"),
                "execution_price_usdc_per_weth": Decimal("1997"),
                "base_amount": Decimal("1"),
                "quote_amount": Decimal("1997"),
                "direction": "sell_base",
                "post_price_change_pct": Decimal("-0.1"),
            }
        ]

        enriched = add_fee_adjusted_metrics(rows, pool_fee=500)[0]

        expected_cost = Decimal("2000") * Decimal("0.9995") - Decimal("1997")
        self.assertEqual(enriched["extra_slippage_usd"], expected_cost)
        self.assertAlmostEqual(
            float(enriched["extra_slippage_bps"]),
            float(expected_cost / Decimal("1997") * Decimal("10000")),
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
