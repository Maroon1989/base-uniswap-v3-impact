# Advanced Research Notes

## Metric Definition

This report uses realized execution deviation, not wallet UI slippage tolerance. For each Swap, `execution_price = abs(USDC_delta / WETH_delta)`. The pre-swap pool price is approximated with the previous Swap event's post-swap price.

The 0.05% pool fee is removed before calling a trade expensive. For a buy-WETH swap, the fee-only reference price is `pre_price / (1 - fee_rate)`. For a sell-WETH swap, it is `pre_price * (1 - fee_rate)`. Extra slippage cost is the USDC difference between the realized quote amount and that fee-only reference.

## Snapshot

- Window: 2026-09-04T09:00:01+00:00 to 2026-09-04T12:59:53+00:00
- Pool: `0xd0b53D9277642d899DF5C87A3966A349A798F224` (WETH/USDC, fee tier 500; fee rate 0.05%)
- Swaps with pre-price: 4,676
- Quote-side volume: $9,118,395.18
- Median raw absolute impact: 5.099 bps
- Median extra slippage after fee: 0.098 bps; p95 1.628 bps
- Estimated fee-floor cost: $4,561.52; estimated extra slippage cost: $6,656.71
- Full-window pool price move: -293.369 bps
- Top 10% by size: 74.3% of volume and 98.7% of extra slippage cost
- Same-tx opposite-direction target-pool candidates: 6
- Backrun-like local candidates: 27
- Largest raw impact is 625.000 bps on a $0.00001700 swap, so raw maxima need a notional floor.

## Fee-Adjusted Slippage By Size

| Size bucket | Swaps | Volume | Volume share | Median raw bps | Median extra bps | P95 extra bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| <1k | 3,297 | $728,424.52 | 8.0% | 5.032 | 0.031 | 0.229 |
| 1k-10k | 1,235 | $3,285,589.92 | 36.0% | 5.462 | 0.461 | 1.522 |
| 10k-50k | 113 | $2,411,792.37 | 26.4% | 8.767 | 3.762 | 8.446 |
| 50k-100k | 24 | $1,818,633.84 | 19.9% | 20.559 | 15.557 | 18.223 |
| 100k-250k | 7 | $873,954.52 | 9.6% | 27.381 | 22.443 | 32.893 |

## Concentration

| Segment | Swaps | Volume share | Extra-slippage cost share | Extra-slippage cost |
| --- | ---: | ---: | ---: | ---: |
| Top 1% | 47 | 36.7% | 84.0% | $5,593.97 |
| Top 5% | 234 | 63.5% | 97.3% | $6,474.87 |
| Top 10% | 468 | 74.3% | 98.7% | $6,573.23 |

## Peak Minutes

| UTC minute | Swaps | Volume | Net buy-WETH | Price move bps | Extra cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-09-04 12:30 | 528 | $4,500,983.63 | $-488,145.82 | -201.957 | $5,062.15 |
| 2026-09-04 12:32 | 109 | $506,150.33 | $-34,019.54 | -13.299 | $782.12 |
| 2026-09-04 09:16 | 97 | $403,610.23 | $72,836.86 | 38.625 | $349.80 |
| 2026-09-04 12:39 | 121 | $314,163.27 | $24,725.32 | 9.918 | $95.96 |
| 2026-09-04 12:31 | 123 | $208,287.68 | $-49,347.22 | -19.244 | $51.21 |
| 2026-09-04 12:48 | 71 | $134,649.44 | $22,698.85 | 9.794 | $45.67 |
| 2026-09-04 09:19 | 63 | $84,808.54 | $-39,247.89 | -21.766 | $5.53 |
| 2026-09-04 12:43 | 34 | $81,772.97 | $-74,131.43 | -29.549 | $7.34 |

## Peak Blocks

| Block | UTC time | Swaps | Volume | Net buy-WETH | Price move bps |
| ---: | --- | ---: | ---: | ---: | ---: |
| 50867834 | 2026-09-04 12:30:15 | 60 | $785,464.86 | $-80,560.32 | -31.229 |
| 50867835 | 2026-09-04 12:30:17 | 56 | $546,887.11 | $-29,775.50 | -11.593 |
| 50867828 | 2026-09-04 12:30:03 | 42 | $421,351.07 | $-174,298.44 | -77.301 |
| 50867839 | 2026-09-04 12:30:25 | 24 | $402,422.19 | $-9,250.14 | -3.628 |
| 50867847 | 2026-09-04 12:30:41 | 30 | $390,531.41 | $1,034.37 | 0.362 |
| 50867838 | 2026-09-04 12:30:23 | 26 | $297,804.36 | $-8,031.23 | -3.145 |
| 50868100 | 2026-09-04 12:39:07 | 60 | $266,064.62 | $-22,423.47 | -9.561 |
| 50867837 | 2026-09-04 12:30:21 | 21 | $261,757.55 | $-3,268.30 | -1.293 |
| 50867897 | 2026-09-04 12:32:21 | 7 | $229,637.49 | $-22,042.02 | -8.609 |
| 50867898 | 2026-09-04 12:32:23 | 8 | $199,014.23 | $-2,200.29 | -0.877 |

## Economic Outliers

Minimum notional: $1,000.

| UTC time | Block | Direction | Size | Extra bps | Extra cost | Tx |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| 2026-09-04 12:30:17 | 50867835 | sell_base | $179,740.86 | 35.040 | $629.82 | [0x611bd3...cfd349](https://basescan.org/tx/0x611bd37d94438d25b4b486ab7e25aed6021dd3c297035d83428eb7fb2ecfd349) |
| 2026-09-04 12:30:15 | 50867834 | sell_base | $143,597.94 | 27.882 | $400.38 | [0x1a2915...6dbaf7](https://basescan.org/tx/0x1a2915ed3f1751449ff524e8af233cbf21670865fbeb125382dbc2ec886dbaf7) |
| 2026-09-04 12:32:21 | 50867897 | sell_base | $125,839.75 | 24.603 | $309.60 | [0x0f981b...f46b2d](https://basescan.org/tx/0x0f981b9e842c19087175637bee22bc110dd87c34d8bd54bfc9768486b1f46b2d) |
| 2026-09-04 12:30:07 | 50867830 | sell_base | $115,620.91 | 22.443 | $259.48 | [0x6a24af...71c19d](https://basescan.org/tx/0x6a24af3fd4d5dabb439908866b65e6736494930a7c4aab61ace7dba5d271c19d) |
| 2026-09-04 12:30:03 | 50867828 | sell_base | $104,138.71 | 21.736 | $226.35 | [0x03653f...e18a65](https://basescan.org/tx/0x03653fdd5bb189a9d325bc5a3e79ce02ce73f43c351f633b059858708de18a65) |
| 2026-09-04 12:30:21 | 50867837 | sell_base | $104,409.09 | 20.313 | $212.09 | [0x848969...f6e5ed](https://basescan.org/tx/0x8489699171e047c9cfbc23d99fda19f6805ed3d39bf35aea311f715d62f6e5ed) |
| 2026-09-04 12:32:23 | 50867898 | sell_base | $100,607.26 | 19.648 | $197.67 | [0x1446dd...58bf48](https://basescan.org/tx/0x1446dd11e2f72e2ecf7e4964e36337049ac24935ff233b4846e458c1ca58bf48) |
| 2026-09-04 12:30:17 | 50867835 | buy_base | $93,944.04 | 18.247 | $171.42 | [0x27573a...0ed72d](https://basescan.org/tx/0x27573ac300d3540d282c61e05b4ed075f2e4200f56dd616d01c7551a530ed72d) |

## Same-Tx Round Trips In The Target Pool

These are stronger candidates than simple five-minute reversals because the same transaction touches the target pool in both directions. They still need receipt/trace review to determine whether the transaction was arbitrage, routing, liquidation, or another bundled action.

| UTC time | Block | Logs | Gross target-pool volume | Buy vol | Sell vol | Net buy | Extra cost | Tx |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-09-04 12:30:21 | 50867837 | 2 | $110,962.52 | $90,505.16 | $20,457.35 | $70,047.81 | $167.35 | [0xc09983...31a369](https://basescan.org/tx/0xc09983726af386ae9bb7e090d6671a66093bfb968737692c50367c01a231a369) |
| 2026-09-04 12:30:17 | 50867835 | 2 | $95,447.09 | $93,944.04 | $1,503.05 | $92,441.00 | $171.46 | [0x27573a...0ed72d](https://basescan.org/tx/0x27573ac300d3540d282c61e05b4ed075f2e4200f56dd616d01c7551a530ed72d) |
| 2026-09-04 12:30:19 | 50867836 | 2 | $77,176.89 | $73,804.20 | $3,372.69 | $70,431.51 | $105.98 | [0x9b4f80...ea5461](https://basescan.org/tx/0x9b4f80aba312ed53e55d22a02e10b686572acb9cba0aaa06755893f62eea5461) |
| 2026-09-04 12:30:17 | 50867835 | 2 | $45,882.30 | $36,749.98 | $9,132.31 | $27,617.67 | $27.80 | [0x34f864...066fcf](https://basescan.org/tx/0x34f864d42a5f5906dd2092ce0e86d43ed0f3f7c9b3130bdea4b3e32793066fcf) |
| 2026-09-04 12:30:21 | 50867837 | 2 | $27,203.01 | $19,632.49 | $7,570.51 | $12,061.98 | $8.59 | [0xa5effc...7de495](https://basescan.org/tx/0xa5effc15d19ecf0c0068e5f9ddf6a8e85fd4dc535fe6df26aeaa0e85fd7de495) |
| 2026-09-04 12:30:15 | 50867834 | 2 | $3,091.95 | $265.42 | $2,826.53 | $-2,561.11 | $0.15625011 | [0xa558fb...0f2045](https://basescan.org/tx/0xa558fb22a19fc743d5a5de77e620b4d67771c152ac7518f1c74e85a4650f2045) |

## Backrun-Like Local Candidates

Rule: anchor notional >= $50,000, extra slippage >= 10.000 bps, cumulative opposite-direction target-pool volume >= 25% of anchor notional within 2 blocks, and pool price recovers at least 50% of the anchor pre/post gap.

| Anchor time | Direction | Size | Extra bps | Extra cost | Opposite vol <=2 blocks | Best recovery | Anchor tx |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-09-04 12:30:17 | sell_base | $179,740.86 | 35.040 | $629.82 | $393,885.95 | 98.5% | [0x611bd3...cfd349](https://basescan.org/tx/0x611bd37d94438d25b4b486ab7e25aed6021dd3c297035d83428eb7fb2ecfd349) |
| 2026-09-04 12:30:15 | sell_base | $143,597.94 | 27.882 | $400.38 | $581,323.99 | 60.4% | [0x1a2915...6dbaf7](https://basescan.org/tx/0x1a2915ed3f1751449ff524e8af233cbf21670865fbeb125382dbc2ec886dbaf7) |
| 2026-09-04 12:32:21 | sell_base | $125,839.75 | 24.603 | $309.60 | $214,861.93 | 90.7% | [0x0f981b...f46b2d](https://basescan.org/tx/0x0f981b9e842c19087175637bee22bc110dd87c34d8bd54bfc9768486b1f46b2d) |
| 2026-09-04 12:30:07 | sell_base | $115,620.91 | 22.443 | $259.48 | $148,600.30 | 99.0% | [0x6a24af...71c19d](https://basescan.org/tx/0x6a24af3fd4d5dabb439908866b65e6736494930a7c4aab61ace7dba5d271c19d) |
| 2026-09-04 12:30:03 | sell_base | $104,138.71 | 21.736 | $226.35 | $195,374.56 | 59.1% | [0x03653f...e18a65](https://basescan.org/tx/0x03653fdd5bb189a9d325bc5a3e79ce02ce73f43c351f633b059858708de18a65) |
| 2026-09-04 12:30:21 | sell_base | $104,409.09 | 20.313 | $212.09 | $470,717.22 | 97.3% | [0x848969...f6e5ed](https://basescan.org/tx/0x8489699171e047c9cfbc23d99fda19f6805ed3d39bf35aea311f715d62f6e5ed) |
| 2026-09-04 12:32:23 | sell_base | $100,607.26 | 19.648 | $197.67 | $118,842.35 | 99.7% | [0x1446dd...58bf48](https://basescan.org/tx/0x1446dd11e2f72e2ecf7e4964e36337049ac24935ff233b4846e458c1ca58bf48) |
| 2026-09-04 12:30:17 | buy_base | $93,944.04 | 18.247 | $171.42 | $221,404.84 | 86.6% | [0x27573a...0ed72d](https://basescan.org/tx/0x27573ac300d3540d282c61e05b4ed075f2e4200f56dd616d01c7551a530ed72d) |

## Rules Worth Testing Further

- Execution-risk rule: ignore raw bps below a notional floor; alert when a route would exceed the $10k-$50k region where extra slippage starts to appear in this sample.
- Liquidity-shock rule: alert on one-minute volume above $1M, net directional pressure above $250k, or minute-level pool-price movement above 50 bps.
- Backrun candidate rule: combine large notional, high fee-adjusted slippage, material opposite flow within one or two blocks, and fast price recovery.
- Higher-confidence MEV/arbitrage rule: inspect receipts for transactions that touch the target pool and another WETH/USDC fee tier in opposite directions in the same transaction.
- Negative rule: do not use 'any opposite swap within five minutes' as a signal here; the pool is active enough that this mostly measures background flow.
