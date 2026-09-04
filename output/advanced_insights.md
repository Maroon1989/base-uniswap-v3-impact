# Advanced Findings

## Dataset

- Pool: `0xd0b53D9277642d899DF5C87A3966A349A798F224` (WETH/USDC, fee tier 500)
- Window: 2026-09-04T09:00:01+00:00 to 2026-09-04T12:59:53+00:00
- Swaps with fee-adjusted impact: 4,676
- Total quote-side volume: $9,118,395.18

## Executive Findings

- The headline median absolute impact of 5.099 bps is mostly the 5.000 bps pool fee. After subtracting that fee floor, median extra slippage is 0.099 bps and p95 extra slippage is 1.630 bps.
- The first size bucket where fee-adjusted impact becomes clearly visible is `10k-50k`. Below that level, most swaps are paying the pool fee rather than moving the curve very much.
- Flow is concentrated: the largest 10% of swaps contributed 74.3% of volume and 98.7% of estimated extra slippage cost.
- Tail economics matter more than tail percentages. Estimated extra slippage beyond the fee floor was $6,650.90, higher than the estimated pool-fee cost of $4,559.20, even though the median extra slippage was close to zero.
- The pool price moved -293.369 bps over the four-hour sample, while median extra single-swap slippage was 0.099 bps. For most trades, market drift was a larger risk than immediate curve impact.
- The strongest hourly regime was 2026-09-04 12:00 UTC (-280.989 bps price move, $6,947,379.81 volume), representing 76.2% of the sample volume.
- A simple opposite-flow rule is not discriminative in this pool: 97.9% of top-decile swaps had opposite-direction volume of at least 50% within 5 minutes, but the lower 90% was also 99.6%. That means reversal counts should be treated as background activity unless combined with a notional floor and recovery behavior.
- The largest raw extra-impact observation was 620.000 bps on a $0.00001700 swap. This is a dust/rounding artifact, so economic outlier review below applies a $1,000 notional floor.

## Fee-Adjusted Impact By Size

| Size bucket | Swaps | Volume | Volume share | Median abs impact (bps) | Median extra bps | P75 extra bps | P95 extra bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| <1k | 3,297 | $728,424.52 | 8.0% | 5.032 | 0.032 | 0.115 | 0.230 |
| 1k-10k | 1,235 | $3,285,589.92 | 36.0% | 5.462 | 0.462 | 0.734 | 1.521 |
| 10k-50k | 113 | $2,411,792.37 | 26.4% | 8.767 | 3.767 | 5.686 | 8.435 |
| 50k-100k | 24 | $1,818,633.84 | 19.9% | 20.559 | 15.559 | 17.229 | 18.255 |
| 100k-250k | 7 | $873,954.52 | 9.6% | 27.381 | 22.381 | 26.160 | 32.767 |

## Volume Concentration

Estimated pool-fee cost is approximately $4,559.20. Estimated extra slippage cost beyond the fee floor is approximately $6,650.90.

| Segment by trade size | Swaps | Volume | Volume share | Extra slippage cost | Extra cost share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top 1% | 47 | $3,344,660.31 | 36.7% | $5,587.51 | 84.0% |
| Top 5% | 234 | $5,787,963.56 | 63.5% | $6,468.62 | 97.3% |
| Top 10% | 468 | $6,777,432.57 | 74.3% | $6,567.10 | 98.7% |

## Direction Asymmetry

Net buy-WETH quote volume was $-729,501.99 (buy volume minus sell volume).

| Direction | Swaps | Volume | Volume share | Median size | Median extra bps | P95 extra bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| buy_base | 2,456 | $4,194,446.60 | 46.0% | $319.90 | 0.107 | 1.751 |
| sell_base | 2,220 | $4,923,948.58 | 54.0% | $322.95 | 0.093 | 1.488 |

## Hourly Regimes

The strongest one-hour pool-price move was 2026-09-04 12:00 UTC (-280.989 bps price move, $6,947,379.81 volume).

| UTC hour | Swaps | Volume | Net buy-WETH volume | Price move (bps) | Median extra bps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-09-04 09:00 | 1,170 | $1,455,800.30 | $-35,011.97 | -16.673 | 0.139 |
| 2026-09-04 10:00 | 645 | $407,944.85 | $31,666.05 | 15.831 | 0.069 |
| 2026-09-04 11:00 | 654 | $307,270.22 | $-24,185.52 | -11.875 | 0.039 |
| 2026-09-04 12:00 | 2,207 | $6,947,379.81 | $-701,970.54 | -280.989 | 0.106 |

## Large-Swap Follow-Through

Top-decile swap threshold: $3,201.44. Window: 300 seconds. Opposite-flow ratios compare cumulative opposite-direction volume after the anchor swap with the anchor swap size.

| Segment | Anchors | Any opposite flow | Opposite >=25% | Opposite >=50% | Opposite >=100% | Median opposite/anchor | Median first opposite seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Top-decile size | 468 | 100.0% | 99.4% | 97.9% | 95.5% | 23.11x | 2 |
| Lower 90% size | 4,208 | 99.9% | 99.8% | 99.6% | 99.2% | 463.72x | 6 |

## Price Recovery After Top-Decile Swaps

Within 600 seconds, 329/468 top-decile swaps saw the pool price return to within 25% of the anchor swap's pre/post price gap (70.3%). Median recovery time: 14 seconds.

## Largest Fee-Adjusted Impact Transactions

These rows apply a $1,000 minimum notional filter. Economic rows in scope: 1,379.

| UTC time | Direction | Size | Extra bps | Abs impact bps | Post-price move bps | Tx |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-09-04 12:30:17 | sell_base | $179,740.86 | 34.900 | 39.900 | -69.739 | [0x611bd3...cfd349](https://basescan.org/tx/0x611bd37d94438d25b4b486ab7e25aed6021dd3c297035d83428eb7fb2ecfd349) |
| 2026-09-04 12:30:15 | sell_base | $143,597.94 | 27.790 | 32.790 | -55.532 | [0x1a2915...6dbaf7](https://basescan.org/tx/0x1a2915ed3f1751449ff524e8af233cbf21670865fbeb125382dbc2ec886dbaf7) |
| 2026-09-04 12:32:21 | sell_base | $125,839.75 | 24.530 | 29.530 | -49.557 | [0x0f981b...f46b2d](https://basescan.org/tx/0x0f981b9e842c19087175637bee22bc110dd87c34d8bd54bfc9768486b1f46b2d) |
| 2026-09-04 12:30:07 | sell_base | $115,620.91 | 22.381 | 27.381 | -44.700 | [0x6a24af...71c19d](https://basescan.org/tx/0x6a24af3fd4d5dabb439908866b65e6736494930a7c4aab61ace7dba5d271c19d) |
| 2026-09-04 12:30:03 | sell_base | $104,138.71 | 21.678 | 26.678 | -42.267 | [0x03653f...e18a65](https://basescan.org/tx/0x03653fdd5bb189a9d325bc5a3e79ce02ce73f43c351f633b059858708de18a65) |
| 2026-09-04 09:16:37 | sell_base | $77,086.15 | 20.358 | 25.358 | -40.600 | [0xbcc440...c857bd](https://basescan.org/tx/0xbcc4405e5b8aa64bd92ce26ea1ec445b8957fd82625b2b34d9c9983b3cc857bd) |
| 2026-09-04 12:30:21 | sell_base | $104,409.09 | 20.262 | 25.262 | -40.542 | [0x848969...f6e5ed](https://basescan.org/tx/0x8489699171e047c9cfbc23d99fda19f6805ed3d39bf35aea311f715d62f6e5ed) |
| 2026-09-04 12:32:23 | sell_base | $100,607.26 | 19.600 | 24.600 | -39.632 | [0x1446dd...58bf48](https://basescan.org/tx/0x1446dd11e2f72e2ecf7e4964e36337049ac24935ff233b4846e458c1ca58bf48) |

## Largest Extra-Slippage Dollar Contributors

| UTC time | Direction | Size | Extra bps | Estimated extra cost | Tx |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-09-04 12:30:17 | sell_base | $179,740.86 | 34.900 | $627.30 | [0x611bd3...cfd349](https://basescan.org/tx/0x611bd37d94438d25b4b486ab7e25aed6021dd3c297035d83428eb7fb2ecfd349) |
| 2026-09-04 12:30:15 | sell_base | $143,597.94 | 27.790 | $399.06 | [0x1a2915...6dbaf7](https://basescan.org/tx/0x1a2915ed3f1751449ff524e8af233cbf21670865fbeb125382dbc2ec886dbaf7) |
| 2026-09-04 12:32:21 | sell_base | $125,839.75 | 24.530 | $308.69 | [0x0f981b...f46b2d](https://basescan.org/tx/0x0f981b9e842c19087175637bee22bc110dd87c34d8bd54bfc9768486b1f46b2d) |
| 2026-09-04 12:30:07 | sell_base | $115,620.91 | 22.381 | $258.77 | [0x6a24af...71c19d](https://basescan.org/tx/0x6a24af3fd4d5dabb439908866b65e6736494930a7c4aab61ace7dba5d271c19d) |
| 2026-09-04 12:30:03 | sell_base | $104,138.71 | 21.678 | $225.75 | [0x03653f...e18a65](https://basescan.org/tx/0x03653fdd5bb189a9d325bc5a3e79ce02ce73f43c351f633b059858708de18a65) |
| 2026-09-04 12:30:21 | sell_base | $104,409.09 | 20.262 | $211.55 | [0x848969...f6e5ed](https://basescan.org/tx/0x8489699171e047c9cfbc23d99fda19f6805ed3d39bf35aea311f715d62f6e5ed) |
| 2026-09-04 12:32:23 | sell_base | $100,607.26 | 19.600 | $197.19 | [0x1446dd...58bf48](https://basescan.org/tx/0x1446dd11e2f72e2ecf7e4964e36337049ac24935ff233b4846e458c1ca58bf48) |
| 2026-09-04 12:30:17 | buy_base | $93,944.04 | 18.292 | $171.84 | [0x27573a...0ed72d](https://basescan.org/tx/0x27573ac300d3540d282c61e05b4ed075f2e4200f56dd616d01c7551a530ed72d) |

## Interpretation

- Treat the 5 bps pool fee as the execution-cost floor. The research value is in the residual above that floor.
- Size is the clearer near-term driver than raw in-range liquidity in this short sample.
- Raw max-impact rankings must apply a notional floor; otherwise dust swaps dominate the outlier list.
- Simple reversal counts are too noisy for this high-frequency pool. Stronger candidates combine large notional, high extra slippage, material opposite flow, and rapid price recovery.
- The follow-through and recovery metrics identify candidates for manual transaction-level review; they do not prove arbitrage or MEV by themselves.
