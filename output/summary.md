# Generated Metrics Snapshot

## Dataset

- Network/protocol: Base / Uniswap v3
- Pool: `0xd0b53D9277642d899DF5C87A3966A349A798F224`
- Pair: WETH/USDC, fee tier 500 (0.05%)
- Time range: 2026-09-04T09:00:01+00:00 to 2026-09-04T12:59:53+00:00
- Swaps analyzed: 4,677 (4,676 with pre-swap price impact)

## Why This Dataset Is Interesting

This pool is a high-frequency venue for ETH-dollar flow on Base. Swap events expose signed token deltas, after-swap price, liquidity and tick, which makes the dataset useful for studying execution cost, liquidity conditions, and short-horizon reversal patterns that can hint at arbitrage or MEV behavior.

## What The Data Shows

- Total approximate volume: $9,118,397.54
- Median trade size: $321.56
- Pool fee floor: 5.000 bps
- Mean absolute price impact: 5.803 bps
- Median absolute price impact: 5.099 bps
- Approx. median fee-adjusted extra slippage: 0.099 bps
- Approx. 95th percentile fee-adjusted extra slippage: 1.630 bps
- Max raw absolute price impact: 625.000 bps; raw maxima can be dust artifacts, so use a notional floor for outlier review
- Buy-WETH swaps: 2,457; sell-WETH swaps: 2,220
- Approx. fee-adjusted impact starts to look meaningfully elevated around size bucket: 10k-50k
- Liquidity relationship: For trades above the median size, low-liquidity periods had median extra slippage 0.292 bps versus 0.440 bps in high-liquidity periods (0.66x).
- Short-horizon reversal note: Simple any-opposite-swap checks are too noisy in this high-frequency pool. Run base-v3-advanced-insights for material opposite-flow, recovery, and notional-filtered outlier metrics.

## Price Impact By Size Bucket

| Size bucket | Swaps | Median abs impact (bps) | Median extra bps |
| --- | ---: | ---: | ---: |
| <1k | 3297 | 5.032 | 0.032 |
| 1k-10k | 1235 | 5.462 | 0.462 |
| 10k-50k | 113 | 8.767 | 3.767 |
| 50k-100k | 24 | 20.559 | 15.559 |
| 100k-250k | 7 | 27.381 | 22.381 |

## Potential Applications

- Execution risk: estimate where trade size begins to create non-trivial slippage on Base WETH/USDC.
- Alerting: flag unusually large swaps or low-liquidity windows before routing large orders.
- Arbitrage/MEV research: identify large impacts followed by rapid opposite-direction flow for manual investigation.
- Liquidity monitoring: track when raw in-range liquidity falls and execution quality worsens.

## Limitations

The pre-swap price is approximated with the previous Swap event's after-swap price, so quiet periods with Mint/Burn activity or external price moves can add noise. A single pool also cannot prove arbitrage or MEV; it can only surface candidate signals for deeper transaction-level review.

## Charts

- `output/charts/price_timeseries.png`
- `output/charts/hourly_volume.png`
- `output/charts/size_vs_impact.png`
- `output/charts/impact_by_size_bucket.png`
- `output/charts/liquidity_vs_impact.png`
