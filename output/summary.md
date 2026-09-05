# Research Summary

This study looks at one liquid Base venue: the Uniswap v3 WETH/USDC 0.05% pool at `0xd0b53D9277642d899DF5C87A3966A349A798F224`. The formal sample covers `2026-09-04 09:00:00` to `2026-09-04 12:59:59` UTC, blocks `50861527` to `50868726`, with 4,677 decoded Swap events.

The useful question is not whether the pool has price impact in the abstract. The useful question is when execution stops being dominated by the 0.05% fee and starts being dominated by curve movement, flow bursts, and possible arbitrage response.

## Slippage Definition

I use realized execution deviation, not wallet slippage tolerance. For each swap, average execution price is `abs(USDC_delta / WETH_delta)`. Raw impact compares that average execution price with the estimated pre-swap pool price. Since Uniswap v3 emits the after-swap price, the pre-swap price is approximated with the previous target-pool Swap event's after-swap price.

Because this is a 0.05% pool, the first roughly 5 bps of cost is expected. I therefore subtract a fee-only reference before calling anything extra slippage:

- Buy WETH: compare actual USDC paid with `WETH_received * pre_price / (1 - fee_rate)`.
- Sell WETH: compare actual USDC received with `WETH_sold * pre_price * (1 - fee_rate)`.

The result is measured both in bps and in USDC. This matters because a huge bps move on dust is not economically meaningful.

## Main Results

The pool was extremely efficient for ordinary trade sizes. Median raw absolute impact was 5.099 bps, but after removing the 5 bps fee floor, median extra slippage was only 0.098 bps. The p95 extra slippage was 1.628 bps.

The curve starts to matter around the $10k-$50k bucket. Median extra slippage was 0.031 bps below $1k, 0.461 bps for $1k-$10k, 3.762 bps for $10k-$50k, 15.557 bps for $50k-$100k, and 22.443 bps for $100k-$250k.

The economics were concentrated in the tail. The top 10% of swaps by size accounted for 74.3% of volume and 98.7% of extra slippage cost. The top 1% alone accounted for 84.0% of extra slippage cost. That suggests an alerting system should watch notional and fee-adjusted cost together, instead of ranking by raw bps.

The biggest raw-impact observation was not useful: 625 bps on a $0.000017 swap. This is exactly why a notional floor is needed before discussing outliers.

## The 12:30 UTC Event

Most of the four-hour price move came from a short burst around `2026-09-04 12:30 UTC`. That minute had 528 target-pool swaps, about $4.50M of volume, net sell-WETH pressure of roughly $488k, and a -201.957 bps target-pool price move.

Two large sells anchor the case. `0x1a2915...6dbaf7` sold 57.7418 WETH for $143,597.94, with estimated extra slippage of 27.882 bps, or about $400.38. `0x611bd3...cfd349` sold 72.6023 WETH for $179,740.86, with estimated extra slippage of 35.040 bps, or about $629.82.

The second anchor pushed the target pool from about 2485.61 USDC/WETH before the swap to 2468.27 after it. Later swaps in the same block pulled the price back close to the pre-swap level. This is a better candidate for manual review than a generic reversal signal because it combines large notional, high fee-adjusted cost, and fast local recovery.

## Candidate Rules

A simple "opposite swap within five minutes" rule is too noisy for this pool. Opposite flow is common because Base WETH/USDC is highly active.

A more useful screening rule is stricter:

- ignore swaps below a notional floor such as $1,000 or $10,000;
- require high fee-adjusted slippage, not just high raw impact;
- require material opposite flow within one or two blocks;
- require price recovery toward the anchor's pre-swap price;
- inspect the full receipt for same-transaction cross-pool behavior, especially across WETH/USDC fee tiers.

This does not prove profit or MEV. It produces a short list of transactions worth tracing with balances, gas, and cross-pool state.

## Practical Use

For execution risk, this sample suggests that small WETH/USDC swaps on Base are mostly fee-dominated, while $10k+ swaps deserve explicit curve-cost estimation and $50k+ swaps should be compared against split routing or alternative fee tiers.

For monitoring, a useful alert would focus on minute-level flow bursts: volume above $1M, net directional pressure above $250k, or pool-price movement above 50 bps. That would have captured the 12:30 UTC event without alerting on routine traffic.

For arbitrage research, the next step is transaction-level tracing of the short candidate list, not broader Swap-event statistics alone.
