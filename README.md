# Base Uniswap V3 Price Impact Discovery

This project answers the Lindenshore blockchain data discovery prompt with a small, reproducible on-chain dataset: recent `Swap` events from a Base Uniswap v3 WETH/USDC pool, stored locally in SQLite and analyzed for trade size, liquidity, price movement, and price impact.

The RPC endpoint is intentionally not committed. Add your own free Base RPC URL to `.env`:

```bash
BASE_RPC_URL=https://your-base-rpc.example
```

## Project Overview

The research question is:

> On Base Uniswap v3 WETH/USDC, how do trade size, direction, and in-range liquidity relate to realized price impact, and can large-impact swaps surface useful execution-risk or arbitrage/MEV signals?

The project is intentionally scoped to one active pool so the methodology is auditable. It can later be extended to multiple fee tiers, pools, or chains.

## Dataset and Pool Selection

Default scope:

- Network: Base mainnet
- Protocol: Uniswap v3
- Pair: WETH/USDC
- Default fee tier: `500` (0.05%)
- Default lookback: recent 7 days
- Storage: SQLite at `data/swaps.db`

Uniswap v3 has separate pools per fee tier, so the project includes a pool discovery command before collection:

```bash
base-v3-discover-pool --recent-blocks 43200
```

This compares the `100`, `500`, `3000`, and `10000` fee tiers by recent Swap count, current liquidity, and current WETH/USDC pool price. Use the most active pool/fee tier for the final dataset.

Official Base Uniswap v3 deployment references:

- Factory: `0x33128a8fC17869897dcE68Ed026d694621f6FDfD`
- Base WETH: `0x4200000000000000000000000000000000000006`

## Data Collection Method

`base-v3-fetch-swaps` reads Swap logs with `eth_getLogs`, decodes the Uniswap v3 event fields, caches block timestamps, and inserts records into SQLite with a `tx_hash + log_index` primary key.

Collected fields:

- pool address
- block number and timestamp
- transaction hash, transaction index, log index
- sender and recipient
- `amount0` and `amount1`
- `sqrtPriceX96`
- in-range `liquidity`
- `tick`

The fetcher supports:

- chunked log requests
- retry with backoff
- automatic chunk-size reduction if RPC rejects a range
- resume progress by pool/range
- SQLite de-duplication

## Price Impact Methodology

Uniswap v3 `Swap` emits the pool price after the swap. The analysis therefore approximates pre-swap price as the previous Swap event's post-swap price for the same pool.

For each swap:

```text
raw_price = (sqrtPriceX96 / 2^96)^2
adjusted_token1_per_token0 = raw_price * 10^(token0_decimals - token1_decimals)
execution_price = abs(quote_amount / base_amount)
price_impact = (execution_price - pre_swap_pool_price) / pre_swap_pool_price
```

For WETH/USDC, the project normalizes prices to:

```text
USDC per WETH
```

Direction is interpreted from pool deltas:

- `sell_base`: pool receives WETH and sends USDC
- `buy_base`: pool sends WETH and receives USDC

## Setup

```bash
cd /home/leo/base-uniswap-v3-impact
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env and fill BASE_RPC_URL
```

Or use the shared conda environment on this machine:

```bash
conda activate shared_env
cd /home/leo/base-uniswap-v3-impact
pip install -e .
# edit .env and fill BASE_RPC_URL
```

You can also install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

## How To Run

1. Compare fee-tier pools:

```bash
base-v3-discover-pool --recent-blocks 43200
```

2. Fetch recent swaps. The default uses WETH/USDC 0.05% for the last 7 days:

```bash
base-v3-fetch-swaps
```

Useful overrides:

```bash
base-v3-fetch-swaps --fee 500 --days 7 --chunk-size 1000
base-v3-fetch-swaps --pool 0xYourPoolAddress --from-block 123 --to-block 456
base-v3-fetch-swaps --max-swaps 20000
```

3. Run quality checks:

```bash
base-v3-quality-check
```

4. Generate analysis outputs:

```bash
base-v3-analyze
```

Outputs:

- `data/swaps.db`
- quality-check console report
- `output/swaps_enriched.csv`
- `output/summary.md`
- `output/charts/price_timeseries.png`
- `output/charts/hourly_volume.png`
- `output/charts/size_vs_impact.png`
- `output/charts/impact_by_size_bucket.png`
- `output/charts/liquidity_vs_impact.png`

## Results and Charts

After running `base-v3-analyze`, read `output/summary.md`. It includes:

- swap count and sampled time range
- total approximate volume
- average, median, 95th percentile, and maximum absolute price impact
- buy-vs-sell counts
- median impact by trade-size bucket
- liquidity-regime comparison
- short-horizon opposite-direction swap signal after top-decile trades

## Findings

The final findings are generated from the local dataset, not hard-coded. This keeps the README reproducible even if the collection window changes. Copy or summarize `output/summary.md` into this section for the final submission after you fetch data with your RPC.

## Potential Applications

This dataset can be applied to:

- execution-risk estimation for large Base WETH/USDC swaps
- monitoring low-liquidity windows
- alerting on unusually large price-impact trades
- finding candidate arbitrage or MEV follow-up cases
- comparing execution quality across Uniswap v3 fee tiers or chains

## Limitations

- The first swap in the sample is skipped for price-impact calculations because it has no previous in-sample price.
- The previous-Swap pre-price approximation can miss price changes caused by Mint/Burn activity or long quiet periods.
- Raw Uniswap v3 liquidity is useful as a relative in-range liquidity signal, not a direct USD liquidity measure.
- Single-pool Swap data can identify suspicious patterns, but cannot by itself prove arbitrage or MEV.

## Optional Quote Tool

The repository still includes the earlier single-swap quote helper as a side utility:

```bash
base-v3-quote --token-in WETH --token-out USDC --fee 500 --amount-in 1
```

The assessment deliverable should rely on historical Swap collection and analysis, not this quote helper.

## Sources

- Uniswap Base v3 deployments: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments
- Uniswap v3 Swap event fields: https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol
- Ethereum JSON-RPC log querying: https://ethereum.org/developers/docs/apis/json-rpc/
