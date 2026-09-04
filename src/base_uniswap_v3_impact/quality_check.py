from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal

from .analyze import enrich_swaps, load_swap_rows, pool_tokens_from_row
from .config import DEFAULT_DB_PATH
from .db import connect, load_pool_row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run quality checks on collected Base Uniswap v3 swaps.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pool")
    parser.add_argument("--base-symbol", default="WETH")
    parser.add_argument("--quote-symbol", default="USDC")
    parser.add_argument("--sample", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    conn = connect(args.db)
    pool = pool_tokens_from_row(load_pool_row(conn, args.pool))
    rows = load_swap_rows(conn, pool.pool_address)
    if not rows:
        raise SystemExit("No swaps found. Run base-v3-fetch-swaps first.")

    enriched = enrich_swaps(rows, pool, args.base_symbol, args.quote_symbol)
    sign_errors = []
    zero_amounts = []
    missing_timestamps = 0
    for row in rows:
        amount0 = Decimal(row["amount0_raw"])
        amount1 = Decimal(row["amount1_raw"])
        if row["block_timestamp"] is None:
            missing_timestamps += 1
        if amount0 == 0 or amount1 == 0:
            zero_amounts.append(row)
        if (amount0 > 0 and amount1 > 0) or (amount0 < 0 and amount1 < 0):
            sign_errors.append(row)

    duplicate_rows = conn.execute(
        """
        SELECT tx_hash, log_index, COUNT(*) AS c
        FROM swaps
        WHERE lower(pool_address)=lower(?)
        GROUP BY tx_hash, log_index
        HAVING c > 1
        """,
        (pool.pool_address,),
    ).fetchall()

    timestamps = [int(row["block_timestamp"]) for row in rows if row["block_timestamp"] is not None]
    prices = [row["post_price_usdc_per_weth"] for row in enriched]
    valid_impacts = [row for row in enriched if row["abs_price_impact_pct"] is not None]
    buys = [row for row in enriched if row["direction"] == "buy_base"]
    sells = [row for row in enriched if row["direction"] == "sell_base"]

    print(f"Pool: {pool.pool_address}")
    print(f"Pair: {pool.token0.symbol}/{pool.token1.symbol}, fee={pool.fee}")
    if timestamps:
        start = datetime.fromtimestamp(min(timestamps), tz=timezone.utc).isoformat()
        end = datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat()
        print(f"Time range: {start} -> {end}")
    print(f"Raw swaps: {len(rows):,}")
    print(f"Analyzable swaps: {len(enriched):,}")
    print(f"Swaps with impact: {len(valid_impacts):,}")
    print(f"Duplicate tx_hash+log_index rows: {len(duplicate_rows):,}")
    print(f"Missing timestamps: {missing_timestamps:,}")
    print(f"Zero amount rows: {len(zero_amounts):,}")
    print(f"Same-sign amount rows: {len(sign_errors):,}")
    print(f"Direction counts: buy_base={len(buys):,}, sell_base={len(sells):,}")
    if prices:
        print(f"Post price range ({args.quote_symbol}/{args.base_symbol}): {min(prices):.6f} -> {max(prices):.6f}")

    print("Sample transactions for manual Basescan checks:")
    for row in rows[: args.sample]:
        print(f"- https://basescan.org/tx/{row['tx_hash']}#eventlog")


if __name__ == "__main__":
    main()
