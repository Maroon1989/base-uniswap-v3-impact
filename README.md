# Base WETH/USDC Execution Study

This repo is my answer to the Lindenshore blockchain data discovery assessment. I narrowed the scope to one concrete market: the Base Uniswap v3 WETH/USDC 0.05% pool. The goal is not to claim that a single pool proves MEV or arbitrage. The goal is to show how raw Swap logs can be turned into a useful execution-risk and candidate-screening dataset.

Repository: https://github.com/Maroon1989/base-uniswap-v3-impact

## What I Studied

Formal run:

- Chain: Base mainnet
- Protocol: Uniswap v3
- Pool: `0xd0b53D9277642d899DF5C87A3966A349A798F224`
- Pair: WETH/USDC
- Fee tier: `500`, which means 0.05%, or about 5 bps per swap
- Block range: `50861527` to `50868726`
- UTC window: `2026-09-04 09:00:00` to `2026-09-04 12:59:59`
- Beijing window: `2026-09-04 17:00:00` to `2026-09-04 20:59:59`
- Stored locally in SQLite at `data/swaps.db` (ignored by git)

The sample contains 4,677 decoded Swap events. The code records block time, tx hash, log index, signed token deltas, after-swap `sqrtPriceX96`, liquidity, and tick.

## Why This Dataset Is Worth Studying

WETH/USDC is the basic ETH-dollar venue on Base. A pool like this is useful because every Swap event gives three things in the same record: what the trader exchanged, where the pool price ended, and what in-range liquidity looked like at execution time. That makes it possible to study not just volume, but execution quality.

The interesting question became narrower as I looked at the data:

> When does this 0.05% pool stop behaving like a near-frictionless retail venue and start showing economically meaningful execution cost?

That framing is better than simply ranking trades by raw price impact, because raw impact is easy to misread.

## How Data Is Collected

`base-v3-fetch-swaps` calls `eth_getLogs` against the target pool and decodes the Uniswap v3 `Swap` event:

```text
Swap(sender, recipient, amount0, amount1, sqrtPriceX96, liquidity, tick)
```

The fetcher uses chunked requests, retry/backoff, resume progress, timestamp caching, and a SQLite primary key on `tx_hash + log_index`. Alchemy's free Base endpoint limited address-filtered log ranges during this run, so the formal fetch used 10-block chunks with a small worker pool.

## What I Mean By Slippage

Here, "slippage" does not mean a wallet's slippage tolerance setting. I use it as realized execution deviation from the pre-swap pool price.

For every swap:

```text
execution_price = abs(USDC_delta / WETH_delta)
raw_impact_bps = (execution_price - pre_swap_pool_price) / pre_swap_pool_price * 10,000
```

Uniswap v3 emits the after-swap price, not the before-swap price. I approximate `pre_swap_pool_price` with the previous Swap event's after-swap price from the same pool. That is good enough for a compact event-log study, but it is still an approximation.

The key correction is the pool fee. In a 0.05% pool, roughly 5 bps of execution cost is expected even if the trade barely moves the curve. So I define a fee-only reference price first:

```text
fee_rate = 500 / 1,000,000 = 0.0005

buy WETH:  fee_only_price = pre_price / (1 - fee_rate)
sell WETH: fee_only_price = pre_price * (1 - fee_rate)
```

Then I estimate extra slippage in USDC:

```text
buy WETH:  extra_cost = actual_USDC_paid - WETH_received * fee_only_price
sell WETH: extra_cost = WETH_sold * fee_only_price - actual_USDC_received
```

Values below zero are clipped to zero. `extra_slippage_bps` is `extra_cost / actual_quote_notional * 10,000`. This is the metric I trust more than raw impact.

## Main Finding

The pool was very efficient for normal swaps, but execution risk was concentrated in a small number of large trades.

The median raw absolute impact was 5.099 bps. That sounds like price movement until you remember the pool fee is 5 bps. After removing the fee-only baseline, the median extra slippage was only 0.098 bps and the 95th percentile was 1.628 bps.

Size changed the story:

| Size bucket | Swaps | Volume | Median extra bps | P95 extra bps |
| --- | ---: | ---: | ---: | ---: |
| <1k | 3,297 | $728,424.52 | 0.031 | 0.229 |
| 1k-10k | 1,235 | $3,285,589.92 | 0.461 | 1.522 |
| 10k-50k | 113 | $2,411,792.37 | 3.762 | 8.446 |
| 50k-100k | 24 | $1,818,633.84 | 15.557 | 18.223 |
| 100k-250k | 7 | $873,954.52 | 22.443 | 32.893 |

So the practical threshold in this sample is not "any trade creates impact". It is closer to: below $10k, this pool is mostly fee-dominated; from $10k-$50k onward, curve impact becomes visible; above $50k, the extra cost becomes material.

## Concentration Is The Economic Point

Averages hide the useful part. The top 10% of swaps by size produced 74.3% of volume and 98.7% of extra slippage cost. The top 1% alone produced 36.7% of volume and 84.0% of extra slippage cost.

That suggests a practical monitoring idea: do not alert on raw bps alone. Alert on high notional plus fee-adjusted slippage. A 600 bps move on dust is less useful than a 20 bps move on a six-figure swap.

This mattered in the data. The largest raw impact was 625 bps, but it came from a $0.000017 swap. After applying a $1,000 notional floor, the largest economic outliers were clustered around 12:30 UTC and mostly involved large WETH sells.

## The 12:30 UTC Case

The four-hour pool price moved -293.369 bps. Most of that did not happen evenly. It came from a short burst around 12:30 UTC.

The busiest minute was `2026-09-04 12:30 UTC`:

- 528 swaps
- $4.50M target-pool volume
- net sell-WETH pressure of about $488k
- -201.957 bps pool-price move
- $5,062.15 estimated extra slippage cost

The busiest blocks were also packed into that minute:

| Block | Time UTC | Swaps | Volume | Net buy-WETH | Price move bps |
| ---: | --- | ---: | ---: | ---: | ---: |
| 50867834 | 12:30:15 | 60 | $785,464.86 | -$80,560.32 | -31.229 |
| 50867835 | 12:30:17 | 56 | $546,887.11 | -$29,775.50 | -11.593 |
| 50867828 | 12:30:03 | 42 | $421,351.07 | -$174,298.44 | -77.301 |

Two anchor swaps explain the shape well:

- `0x1a2915...6dbaf7`: sold 57.7418 WETH for $143,597.94 in the target pool; estimated extra slippage was 27.882 bps, or about $400.38.
- `0x611bd3...cfd349`: sold 72.6023 WETH for $179,740.86; estimated extra slippage was 35.040 bps, or about $629.82.

The second trade pushed the target pool from about 2485.61 USDC/WETH before the swap to 2468.27 after it. In the same block, later buy-WETH flow of $90k and $94k pulled the price back close to the pre-swap level. That is exactly the kind of sequence an execution-risk or backrun monitor should flag for review.

## MEV And Arbitrage Signals

A simple rule like "large swap followed by opposite swap within five minutes" is not useful here. The pool is too active. Opposite-direction flow happens almost all the time for both large and small trades.

The better signals are stricter:

- Ignore candidates below a notional floor such as $1,000 or $10,000.
- Require high fee-adjusted slippage, not high raw bps.
- Require material opposite flow within one or two blocks, not five minutes.
- Require price recovery toward the anchor's pre-swap price.
- For higher confidence, inspect the transaction receipt and look for cross-pool execution in the same transaction.

The receipt checks produced two useful examples:

- `0x27573a...0ed72d` sold WETH in a WETH/USDC 0.30% pool, bought WETH in the target 0.05% pool, then touched the target pool again in the opposite direction. That looks like a cross-pool route or arbitrage candidate, not a plain user swap.
- `0xc09983...31a369` touched eight v3 pools in one transaction. It sold WETH in a 0.30% WETH/USDC pool, bought WETH from the target 0.05% pool, later sold WETH back into the target pool, and also routed through SOL/cbBTC, JitoSOL/cbBTC, WETH/cbBTC, USDC/cbBTC, and another WETH/USDC fee tier.

Those are not proof of profitable MEV. But they are much better candidates than a generic reversal rule because the receipt shows same-transaction cross-pool behavior.

## Risk And Trading Ideas To Test

This project should be treated as a research and monitoring framework, not as a trading recommendation.

The most actionable risk idea is pre-trade routing protection. If a WETH/USDC route on Base is above $10k, start estimating fee-adjusted curve cost instead of assuming the 0.05% pool is always cheap. If it is above $50k, compare against split routing or other fee tiers before execution.

The most actionable monitoring idea is a liquidity-shock alert: flag one-minute windows with more than $1M volume, net directional pressure above $250k, or pool-price movement above 50 bps. In this sample that would have captured the 12:30 event rather than generating noise all afternoon.

The most actionable MEV research idea is a two-stage filter. First, find large target-pool swaps with high fee-adjusted slippage and fast price recovery within one or two blocks. Second, inspect receipts for transactions that use the target pool and another WETH/USDC fee tier in opposite directions. That second step is where the candidate starts to look like cross-pool arbitrage instead of normal flow.

## Outputs

Tracked outputs:

- `output/summary.md`: hand-written research summary
- `output/case_receipts.md`: hand-written case notes from selected receipts
- `output/advanced_metrics.json`: structured fee-adjusted metrics, peak minute/block stats, and candidate lists
- `output/case_receipts.json`: structured receipt-level spot checks for selected case transactions
- `output/charts/price_timeseries.png`
- `output/charts/hourly_volume.png`
- `output/charts/size_vs_impact.png`
- `output/charts/impact_by_size_bucket.png`
- `output/charts/liquidity_vs_impact.png`

The markdown files are not generated by the analysis scripts; scripts emit CSV, charts, and JSON evidence only.

Local outputs ignored by git:

- `data/swaps.db`
- `output/swaps_enriched.csv`
- `.env`

## How To Run

Set your Base RPC URL:

```bash
cp .env.example .env
# edit BASE_RPC_URL in .env
```

Install:

```bash
conda activate shared_env
cd /home/leo/base-uniswap-v3-impact
pip install -e .
```

Discover WETH/USDC fee-tier pools:

```bash
base-v3-discover-pool --recent-blocks 43200
```

Fetch the formal four-hour window used here:

```bash
base-v3-fetch-swaps --from-block 50861527 --to-block 50868726 --fee 500 --chunk-size 10 --workers 4 --progress-every 50 --db data/swaps.db --no-resume
```

Run checks and analysis:

```bash
base-v3-quality-check --db data/swaps.db
base-v3-analyze --db data/swaps.db
base-v3-advanced-insights --db data/swaps.db --output output/advanced_metrics.json
```

Inspect receipt-level case transactions:

```bash
base-v3-inspect-tx --output output/case_receipts.json \
  0x611bd37d94438d25b4b486ab7e25aed6021dd3c297035d83428eb7fb2ecfd349 \
  0x1a2915ed3f1751449ff524e8af233cbf21670865fbeb125382dbc2ec886dbaf7 \
  0x27573ac300d3540d282c61e05b4ed075f2e4200f56dd616d01c7551a530ed72d \
  0xc09983726af386ae9bb7e090d6671a66093bfb968737692c50367c01a231a369
```

## Limitations

The pre-swap price is approximated from the previous Swap event, so Mint/Burn activity or quiet-period state changes are not fully captured. Raw Uniswap v3 liquidity is treated as a relative signal, not converted into dollar depth across ticks. The MEV/arbitrage discussion is candidate screening only; proving profit would require transaction traces, gas costs, token balances, and cross-pool state before and after execution.

## Sources

- Uniswap Base v3 deployments: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments
- Uniswap v3 Swap event fields: https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol
- Ethereum JSON-RPC log querying: https://ethereum.org/developers/docs/apis/json-rpc/
