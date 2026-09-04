from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from statistics import mean, median

from .models import Token
from .config import DEFAULT_CHART_DIR, DEFAULT_DB_PATH
from .db import connect, load_pool_row
from .uniswap_v3 import decimal_amount, price_quote_per_base

getcontext().prec = 80


@dataclass(frozen=True)
class PoolTokens:
    pool_address: str
    token0: Token
    token1: Token
    fee: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze collected Base Uniswap v3 swaps and write charts/findings.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pool")
    parser.add_argument("--base-symbol", default="WETH")
    parser.add_argument("--quote-symbol", default="USDC")
    parser.add_argument("--charts-dir", default=str(DEFAULT_CHART_DIR))
    parser.add_argument("--csv", default="output/swaps_enriched.csv")
    parser.add_argument("--summary", default="output/summary.md")
    return parser


def pool_tokens_from_row(row: sqlite3.Row) -> PoolTokens:
    return PoolTokens(
        pool_address=row["pool_address"],
        token0=Token(row["token0_address"], row["token0_symbol"], int(row["token0_decimals"])),
        token1=Token(row["token1_address"], row["token1_symbol"], int(row["token1_decimals"])),
        fee=int(row["fee"]),
    )


def load_swap_rows(conn: sqlite3.Connection, pool_address: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM swaps
        WHERE lower(pool_address)=lower(?)
        ORDER BY block_number, tx_index, log_index
        """,
        (pool_address,),
    ).fetchall()


def size_bucket(size_usd: Decimal) -> str:
    bounds = [
        (Decimal("1000"), "<1k"),
        (Decimal("10000"), "1k-10k"),
        (Decimal("50000"), "10k-50k"),
        (Decimal("100000"), "50k-100k"),
        (Decimal("250000"), "100k-250k"),
        (Decimal("500000"), "250k-500k"),
        (Decimal("1000000"), "500k-1m"),
    ]
    for limit, label in bounds:
        if size_usd < limit:
            return label
    return ">=1m"


def fmt_decimal(value: Decimal | None, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def to_float(value: Decimal | int | str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def percentile(values: list[Decimal], pct: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (Decimal(len(ordered) - 1) * pct) / Decimal(100)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (Decimal(1) - frac) + ordered[high] * frac


def enrich_swaps(rows: list[sqlite3.Row], pool: PoolTokens, base_symbol: str, quote_symbol: str) -> list[dict[str, object]]:
    token0_is_base = pool.token0.symbol.upper() == base_symbol.upper()
    token1_is_base = pool.token1.symbol.upper() == base_symbol.upper()
    token0_is_quote = pool.token0.symbol.upper() == quote_symbol.upper()
    token1_is_quote = pool.token1.symbol.upper() == quote_symbol.upper()
    if not ((token0_is_base and token1_is_quote) or (token1_is_base and token0_is_quote)):
        raise SystemExit(
            f"Pool is {pool.token0.symbol}/{pool.token1.symbol}; pass matching --base-symbol/--quote-symbol."
        )

    enriched: list[dict[str, object]] = []
    previous_post_price: Decimal | None = None
    for row in rows:
        amount0 = decimal_amount(row["amount0_raw"], pool.token0.decimals)
        amount1 = decimal_amount(row["amount1_raw"], pool.token1.decimals)
        base_delta = amount0 if token0_is_base else amount1
        quote_delta = amount0 if token0_is_quote else amount1
        base_amount = abs(base_delta)
        quote_amount = abs(quote_delta)
        if base_amount == 0 or quote_amount == 0:
            continue

        direction = "sell_base" if base_delta > 0 else "buy_base"
        execution_price = quote_amount / base_amount
        post_price = price_quote_per_base(row["sqrt_price_x96"], pool.token0, pool.token1, base_symbol, quote_symbol)
        pre_price = previous_post_price
        signed_impact_pct = None
        abs_impact_pct = None
        post_price_change_pct = None
        if pre_price is not None and pre_price != 0:
            signed_impact_pct = (execution_price - pre_price) / pre_price * Decimal(100)
            abs_impact_pct = abs(signed_impact_pct)
            post_price_change_pct = (post_price - pre_price) / pre_price * Decimal(100)

        enriched.append(
            {
                "block_number": int(row["block_number"]),
                "block_timestamp": int(row["block_timestamp"]),
                "datetime_utc": datetime.fromtimestamp(int(row["block_timestamp"]), tz=timezone.utc).isoformat(),
                "tx_hash": row["tx_hash"],
                "tx_index": int(row["tx_index"]),
                "log_index": int(row["log_index"]),
                "sender": row["sender"],
                "recipient": row["recipient"],
                "direction": direction,
                "amount0": amount0,
                "amount1": amount1,
                "base_amount": base_amount,
                "quote_amount": quote_amount,
                "size_usd": quote_amount,
                "size_bucket": size_bucket(quote_amount),
                "pre_price_usdc_per_weth": pre_price,
                "execution_price_usdc_per_weth": execution_price,
                "post_price_usdc_per_weth": post_price,
                "price_impact_pct": signed_impact_pct,
                "abs_price_impact_pct": abs_impact_pct,
                "post_price_change_pct": post_price_change_pct,
                "liquidity": Decimal(row["liquidity"]),
                "tick": int(row["tick"]),
            }
        )
        previous_post_price = post_price
    return enriched


def write_csv(path: str | Path, rows: list[dict[str, object]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()})


def write_charts(charts_dir: str | Path, rows: list[dict[str, object]]) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(charts_dir)
    out.mkdir(parents=True, exist_ok=True)
    valid = [r for r in rows if r["abs_price_impact_pct"] is not None]
    written: list[Path] = []
    if not valid:
        return written

    times = [datetime.fromtimestamp(int(r["block_timestamp"]), tz=timezone.utc) for r in rows]
    prices = [to_float(r["post_price_usdc_per_weth"]) for r in rows]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(times, prices, linewidth=1)
    ax.set_title("Pool price over time")
    ax.set_ylabel("USDC per WETH")
    ax.set_xlabel("UTC time")
    fig.autofmt_xdate()
    fig.tight_layout()
    path = out / "price_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    written.append(path)

    hourly: dict[datetime, Decimal] = defaultdict(Decimal)
    for r in rows:
        dt = datetime.fromtimestamp(int(r["block_timestamp"]), tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        hourly[dt] += r["size_usd"]  # type: ignore[operator]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(sorted(hourly), [float(hourly[t]) for t in sorted(hourly)], width=0.03)
    ax.set_title("Hourly swap volume")
    ax.set_ylabel("Approx. USD volume")
    ax.set_xlabel("UTC hour")
    fig.autofmt_xdate()
    fig.tight_layout()
    path = out / "hourly_volume.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    written.append(path)

    fig, ax = plt.subplots(figsize=(8, 5))
    for direction, color in (("buy_base", "tab:blue"), ("sell_base", "tab:orange")):
        subset = [r for r in valid if r["direction"] == direction]
        ax.scatter(
            [float(r["size_usd"]) for r in subset],
            [float(r["abs_price_impact_pct"]) * 100 for r in subset],
            s=12,
            alpha=0.55,
            label=direction,
            color=color,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("Trade size vs. absolute price impact")
    ax.set_xlabel("Trade size, approx. USD (log)")
    ax.set_ylabel("Absolute price impact, bps (log)")
    ax.legend()
    fig.tight_layout()
    path = out / "size_vs_impact.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    written.append(path)

    bucket_order = ["<1k", "1k-10k", "10k-50k", "50k-100k", "100k-250k", "250k-500k", "500k-1m", ">=1m"]
    grouped = [[float(r["abs_price_impact_pct"]) * 100 for r in valid if r["size_bucket"] == bucket] for bucket in bucket_order]
    non_empty = [(bucket, values) for bucket, values in zip(bucket_order, grouped) if values]
    if non_empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.boxplot([values for _, values in non_empty], labels=[bucket for bucket, _ in non_empty], showfliers=False)
        ax.set_title("Price impact by trade-size bucket")
        ax.set_xlabel("Trade size bucket")
        ax.set_ylabel("Absolute price impact, bps")
        fig.tight_layout()
        path = out / "impact_by_size_bucket.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        written.append(path)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(
        [math.log10(float(r["liquidity"])) if float(r["liquidity"]) > 0 else 0 for r in valid],
        [float(r["abs_price_impact_pct"]) * 100 for r in valid],
        s=12,
        alpha=0.55,
    )
    ax.set_title("Liquidity vs. absolute price impact")
    ax.set_xlabel("log10(raw in-range liquidity)")
    ax.set_ylabel("Absolute price impact, bps")
    fig.tight_layout()
    path = out / "liquidity_vs_impact.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    written.append(path)
    return written


def write_summary(path: str | Path, pool: PoolTokens, rows: list[dict[str, object]], chart_paths: list[Path]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    valid = [r for r in rows if r["abs_price_impact_pct"] is not None]
    sizes = [r["size_usd"] for r in rows]  # type: ignore[list-item]
    impacts = [r["abs_price_impact_pct"] for r in valid]  # type: ignore[list-item]
    impact_bps = [impact * Decimal(100) for impact in impacts]
    total_volume = sum(sizes, Decimal(0))
    buys = [r for r in rows if r["direction"] == "buy_base"]
    sells = [r for r in rows if r["direction"] == "sell_base"]

    bucket_order = ["<1k", "1k-10k", "10k-50k", "50k-100k", "100k-250k", "250k-500k", "500k-1m", ">=1m"]
    bucket_lines = []
    noticeable_bucket = None
    for bucket in bucket_order:
        bucket_impacts = [r["abs_price_impact_pct"] * Decimal(100) for r in valid if r["size_bucket"] == bucket]  # type: ignore[operator]
        if not bucket_impacts:
            continue
        med = median(bucket_impacts)
        bucket_lines.append(f"| {bucket} | {len(bucket_impacts)} | {fmt_decimal(med, 3)} |")
        if noticeable_bucket is None and med >= Decimal("5"):
            noticeable_bucket = bucket

    liquidity_note = "Not enough observations to compare liquidity regimes."
    if len(valid) >= 10:
        median_size = median(sizes)
        large_enough = [r for r in valid if r["size_usd"] >= median_size]
        liquidities = sorted(r["liquidity"] for r in large_enough)  # type: ignore[type-var]
        if len(liquidities) >= 4:
            q25 = percentile(liquidities, Decimal(25))
            q75 = percentile(liquidities, Decimal(75))
            low = [r["abs_price_impact_pct"] * Decimal(100) for r in large_enough if r["liquidity"] <= q25]  # type: ignore[operator]
            high = [r["abs_price_impact_pct"] * Decimal(100) for r in large_enough if r["liquidity"] >= q75]  # type: ignore[operator]
            if low and high:
                ratio = median(low) / median(high) if median(high) else None
                liquidity_note = (
                    f"For trades above the median size, low-liquidity periods had median impact "
                    f"{fmt_decimal(median(low), 3)} bps versus {fmt_decimal(median(high), 3)} bps "
                    f"in high-liquidity periods"
                    + (f" ({fmt_decimal(ratio, 2)}x)." if ratio else ".")
                )

    reversal_note = "Not enough swaps to evaluate short-horizon reversals."
    if len(valid) >= 10:
        p90_size = percentile(sizes, Decimal(90))
        large = [r for r in rows if p90_size is not None and r["size_usd"] >= p90_size]
        reversals = 0
        for idx, row in enumerate(rows):
            if row not in large:
                continue
            row_ts = int(row["block_timestamp"])
            row_dir = row["direction"]
            for nxt in rows[idx + 1 :]:
                dt = int(nxt["block_timestamp"]) - row_ts
                if dt > 300:
                    break
                if nxt["direction"] != row_dir:
                    reversals += 1
                    break
        reversal_note = (
            f"Among top-decile size swaps, {reversals}/{len(large)} were followed by an opposite-direction "
            "swap within five minutes. This is a signal only, not proof of arbitrage or MEV."
        )

    start_dt = datetime.fromtimestamp(int(rows[0]["block_timestamp"]), tz=timezone.utc).isoformat() if rows else "n/a"
    end_dt = datetime.fromtimestamp(int(rows[-1]["block_timestamp"]), tz=timezone.utc).isoformat() if rows else "n/a"
    lines = [
        "# Findings Summary",
        "",
        "## Dataset",
        "",
        f"- Network/protocol: Base / Uniswap v3",
        f"- Pool: `{pool.pool_address}`",
        f"- Pair: {pool.token0.symbol}/{pool.token1.symbol}, fee tier {pool.fee} ({pool.fee / 10000:.2f}%)",
        f"- Time range: {start_dt} to {end_dt}",
        f"- Swaps analyzed: {len(rows):,} ({len(valid):,} with pre-swap price impact)",
        "",
        "## Why This Dataset Is Interesting",
        "",
        "This pool is a high-frequency venue for ETH-dollar flow on Base. Swap events expose signed token deltas, after-swap price, liquidity and tick, which makes the dataset useful for studying execution cost, liquidity conditions, and short-horizon reversal patterns that can hint at arbitrage or MEV behavior.",
        "",
        "## What The Data Shows",
        "",
        f"- Total approximate volume: ${fmt_decimal(total_volume, 2)}",
        f"- Median trade size: ${fmt_decimal(median(sizes), 2) if sizes else 'n/a'}",
        f"- Mean absolute price impact: {fmt_decimal(Decimal(mean(impact_bps)), 3) if impact_bps else 'n/a'} bps",
        f"- Median absolute price impact: {fmt_decimal(median(impact_bps), 3) if impact_bps else 'n/a'} bps",
        f"- 95th percentile absolute price impact: {fmt_decimal(percentile(impact_bps, Decimal(95)), 3)} bps",
        f"- Max absolute price impact: {fmt_decimal(max(impact_bps), 3) if impact_bps else 'n/a'} bps",
        f"- Buy-WETH swaps: {len(buys):,}; sell-WETH swaps: {len(sells):,}",
        f"- Impact starts to look meaningfully elevated around size bucket: {noticeable_bucket or 'not clear in this sample'}",
        f"- Liquidity relationship: {liquidity_note}",
        f"- Short-horizon reversal signal: {reversal_note}",
        "",
        "## Price Impact By Size Bucket",
        "",
        "| Size bucket | Swaps | Median abs impact (bps) |",
        "| --- | ---: | ---: |",
        *(bucket_lines or ["| n/a | 0 | n/a |"]),
        "",
        "## Potential Applications",
        "",
        "- Execution risk: estimate where trade size begins to create non-trivial slippage on Base WETH/USDC.",
        "- Alerting: flag unusually large swaps or low-liquidity windows before routing large orders.",
        "- Arbitrage/MEV research: identify large impacts followed by rapid opposite-direction flow for manual investigation.",
        "- Liquidity monitoring: track when raw in-range liquidity falls and execution quality worsens.",
        "",
        "## Limitations",
        "",
        "The pre-swap price is approximated with the previous Swap event's after-swap price, so quiet periods with Mint/Burn activity or external price moves can add noise. A single pool also cannot prove arbitrage or MEV; it can only surface candidate signals for deeper transaction-level review.",
        "",
        "## Charts",
        "",
        *[f"- `{chart}`" for chart in chart_paths],
        "",
    ]
    output.write_text("\n".join(lines))


def main() -> None:
    args = build_parser().parse_args()
    conn = connect(args.db)
    pool = pool_tokens_from_row(load_pool_row(conn, args.pool))
    rows = load_swap_rows(conn, pool.pool_address)
    if len(rows) < 2:
        raise SystemExit("Need at least two swaps to estimate pre-swap price impact. Run fetch for a larger range.")

    enriched = enrich_swaps(rows, pool, args.base_symbol, args.quote_symbol)
    if len(enriched) < 2:
        raise SystemExit("No analyzable swaps after normalization. Check token direction and decimals.")

    write_csv(args.csv, enriched)
    chart_paths = write_charts(args.charts_dir, enriched)
    write_summary(args.summary, pool, enriched, chart_paths)
    print(f"Wrote {args.csv}")
    print(f"Wrote {args.summary}")
    for chart in chart_paths:
        print(f"Wrote {chart}")


if __name__ == "__main__":
    main()
