from __future__ import annotations

import argparse
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from statistics import median
from typing import Iterable

from .analyze import enrich_swaps, load_swap_rows, percentile, pool_tokens_from_row
from .config import DEFAULT_DB_PATH
from .db import connect, load_pool_row

getcontext().prec = 80

BPS = Decimal("10000")
ZERO = Decimal(0)
SIZE_BUCKETS = ["<1k", "1k-10k", "10k-50k", "50k-100k", "100k-250k", "250k-500k", "500k-1m", ">=1m"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write deeper fee-adjusted metrics and case candidates.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pool")
    parser.add_argument("--base-symbol", default="WETH")
    parser.add_argument("--quote-symbol", default="USDC")
    parser.add_argument("--output", default="output/advanced_insights.md")
    parser.add_argument("--economic-min-size-usd", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--large-min-size-usd", type=Decimal, default=Decimal("50000"))
    parser.add_argument("--large-min-extra-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--backrun-blocks", type=int, default=2)
    return parser


def dec(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value: Decimal | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if abs(value) < Decimal("1"):
        return f"${value:,.8f}"
    return f"${value:,.{digits}f}"


def num(value: Decimal | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def pct(part: Decimal, total: Decimal, digits: int = 1) -> str:
    return "n/a" if total == 0 else f"{part / total * Decimal(100):.{digits}f}%"


def md_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def tx_link(tx_hash: str) -> str:
    short = f"{tx_hash[:8]}...{tx_hash[-6:]}"
    return f"[{short}](https://basescan.org/tx/{tx_hash})"


def ts(row: dict[str, object]) -> str:
    return datetime.fromtimestamp(int(row["block_timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add_fee_adjusted_metrics(rows: list[dict[str, object]], pool_fee: int) -> list[dict[str, object]]:
    fee_rate = Decimal(pool_fee) / Decimal(1_000_000)
    out: list[dict[str, object]] = []
    for row in rows:
        if row["pre_price_usdc_per_weth"] is None:
            continue
        pre = dec(row["pre_price_usdc_per_weth"])
        execution = dec(row["execution_price_usdc_per_weth"])
        base_amount = dec(row["base_amount"])
        quote_amount = dec(row["quote_amount"])
        raw_signed_bps = (execution - pre) / pre * BPS
        if row["direction"] == "buy_base":
            fee_only_price = pre / (Decimal(1) - fee_rate)
            fee_only_quote = base_amount * fee_only_price
            extra_cost = max(quote_amount - fee_only_quote, ZERO)
        else:
            fee_only_price = pre * (Decimal(1) - fee_rate)
            fee_only_quote = base_amount * fee_only_price
            extra_cost = max(fee_only_quote - quote_amount, ZERO)

        enriched = dict(row)
        enriched["raw_signed_impact_bps"] = raw_signed_bps
        enriched["raw_abs_impact_bps"] = abs(raw_signed_bps)
        enriched["fee_only_execution_price"] = fee_only_price
        enriched["fee_floor_bps"] = abs((fee_only_price - pre) / pre * BPS)
        enriched["extra_slippage_usd"] = extra_cost
        enriched["extra_slippage_bps"] = extra_cost / quote_amount * BPS if quote_amount else ZERO
        enriched["fee_floor_cost_usd"] = abs(fee_only_quote - base_amount * pre)
        if row["post_price_change_pct"] is not None:
            enriched["post_price_change_bps"] = dec(row["post_price_change_pct"]) * Decimal(100)
        else:
            enriched["post_price_change_bps"] = None
        out.append(enriched)
    return out


def total(rows: Iterable[dict[str, object]], key: str) -> Decimal:
    return sum((dec(row[key]) for row in rows), ZERO)


def top_pct(rows: list[dict[str, object]], pct_value: int) -> list[dict[str, object]]:
    count = max(1, math.ceil(len(rows) * pct_value / 100))
    return sorted(rows, key=lambda row: dec(row["size_usd"]), reverse=True)[:count]


def size_bucket_table(rows: list[dict[str, object]]) -> list[str]:
    volume = total(rows, "size_usd")
    lines = [
        md_row(["Size bucket", "Swaps", "Volume", "Volume share", "Median raw bps", "Median extra bps", "P95 extra bps"]),
        md_row(["---", "---:", "---:", "---:", "---:", "---:", "---:"]),
    ]
    for bucket in SIZE_BUCKETS:
        subset = [row for row in rows if row["size_bucket"] == bucket]
        if not subset:
            continue
        extra = [dec(row["extra_slippage_bps"]) for row in subset]
        raw = [dec(row["raw_abs_impact_bps"]) for row in subset]
        lines.append(
            md_row(
                [
                    bucket,
                    f"{len(subset):,}",
                    money(total(subset, "size_usd")),
                    pct(total(subset, "size_usd"), volume),
                    num(median(raw)),
                    num(median(extra)),
                    num(percentile(extra, Decimal(95))),
                ]
            )
        )
    return lines


def concentration_table(rows: list[dict[str, object]]) -> list[str]:
    volume = total(rows, "size_usd")
    cost = total(rows, "extra_slippage_usd")
    lines = [
        md_row(["Segment", "Swaps", "Volume share", "Extra-slippage cost share", "Extra-slippage cost"]),
        md_row(["---", "---:", "---:", "---:", "---:"]),
    ]
    for p in (1, 5, 10):
        subset = top_pct(rows, p)
        lines.append(md_row([f"Top {p}%", f"{len(subset):,}", pct(total(subset, "size_usd"), volume), pct(total(subset, "extra_slippage_usd"), cost), money(total(subset, "extra_slippage_usd"))]))
    return lines


def period_stats(rows: list[dict[str, object]], seconds: int) -> list[dict[str, object]]:
    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        bucket = int(row["block_timestamp"]) // seconds * seconds
        groups[bucket].append(row)
    stats = []
    for bucket, subset in groups.items():
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        start_price = dec(subset[0]["pre_price_usdc_per_weth"] or subset[0]["post_price_usdc_per_weth"])
        end_price = dec(subset[-1]["post_price_usdc_per_weth"])
        stats.append(
            {
                "start": bucket,
                "swaps": len(subset),
                "volume": buy + sell,
                "buy_volume": buy,
                "sell_volume": sell,
                "net_buy": buy - sell,
                "price_move_bps": (end_price - start_price) / start_price * BPS,
                "extra_cost": total(subset, "extra_slippage_usd"),
            }
        )
    return stats


def minute_table(rows: list[dict[str, object]], limit: int = 8) -> list[str]:
    lines = [
        md_row(["UTC minute", "Swaps", "Volume", "Net buy-WETH", "Price move bps", "Extra cost"]),
        md_row(["---", "---:", "---:", "---:", "---:", "---:"]),
    ]
    for stat in sorted(period_stats(rows, 60), key=lambda item: dec(item["volume"]), reverse=True)[:limit]:
        dt = datetime.fromtimestamp(int(stat["start"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(md_row([dt, f"{stat['swaps']:,}", money(dec(stat["volume"])), money(dec(stat["net_buy"])), num(dec(stat["price_move_bps"])), money(dec(stat["extra_cost"]))]))
    return lines


def block_table(rows: list[dict[str, object]], limit: int = 10) -> list[str]:
    by_block: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_block[int(row["block_number"])].append(row)
    stats = []
    for block, subset in by_block.items():
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        start_price = dec(subset[0]["pre_price_usdc_per_weth"] or subset[0]["post_price_usdc_per_weth"])
        end_price = dec(subset[-1]["post_price_usdc_per_weth"])
        stats.append((buy + sell, block, subset, buy, sell, (end_price - start_price) / start_price * BPS))
    lines = [
        md_row(["Block", "UTC time", "Swaps", "Volume", "Net buy-WETH", "Price move bps"]),
        md_row(["---:", "---", "---:", "---:", "---:", "---:"]),
    ]
    for volume, block, subset, buy, sell, move in sorted(stats, reverse=True)[:limit]:
        lines.append(md_row([block, ts(subset[0]), f"{len(subset):,}", money(volume), money(buy - sell), num(move)]))
    return lines


def economic_outlier_table(rows: list[dict[str, object]], min_size: Decimal, limit: int = 8) -> list[str]:
    candidates = [row for row in rows if dec(row["size_usd"]) >= min_size]
    top = sorted(candidates, key=lambda row: dec(row["extra_slippage_usd"]), reverse=True)[:limit]
    lines = [
        md_row(["UTC time", "Block", "Direction", "Size", "Extra bps", "Extra cost", "Tx"]),
        md_row(["---", "---:", "---", "---:", "---:", "---:", "---"]),
    ]
    for row in top:
        lines.append(md_row([ts(row), row["block_number"], row["direction"], money(dec(row["size_usd"])), num(dec(row["extra_slippage_bps"])), money(dec(row["extra_slippage_usd"])), tx_link(str(row["tx_hash"]))]))
    return lines


def same_tx_round_trips(rows: list[dict[str, object]], min_volume: Decimal = Decimal("1000")) -> list[dict[str, object]]:
    by_tx: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_tx[str(row["tx_hash"])].append(row)
    candidates = []
    for tx_hash, subset in by_tx.items():
        if len(subset) < 2 or {row["direction"] for row in subset} == {subset[0]["direction"]}:
            continue
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        gross = buy + sell
        if gross < min_volume:
            continue
        candidates.append(
            {
                "tx_hash": tx_hash,
                "time": ts(subset[0]),
                "block": subset[0]["block_number"],
                "logs": len(subset),
                "gross": gross,
                "buy": buy,
                "sell": sell,
                "net_buy": buy - sell,
                "extra_cost": total(subset, "extra_slippage_usd"),
                "directions": ",".join(str(row["direction"]) for row in subset),
            }
        )
    return sorted(candidates, key=lambda row: dec(row["gross"]), reverse=True)


def round_trip_table(rows: list[dict[str, object]], limit: int = 8) -> list[str]:
    lines = [
        md_row(["UTC time", "Block", "Logs", "Gross target-pool volume", "Buy vol", "Sell vol", "Net buy", "Extra cost", "Tx"]),
        md_row(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---"]),
    ]
    for row in same_tx_round_trips(rows)[:limit]:
        lines.append(md_row([row["time"], row["block"], row["logs"], money(dec(row["gross"])), money(dec(row["buy"])), money(dec(row["sell"])), money(dec(row["net_buy"])), money(dec(row["extra_cost"])), tx_link(str(row["tx_hash"]))]))
    return lines


def backrun_candidates(rows: list[dict[str, object]], min_size: Decimal, min_extra_bps: Decimal, max_blocks: int) -> list[dict[str, object]]:
    candidates = []
    for idx, row in enumerate(rows):
        if dec(row["size_usd"]) < min_size or dec(row["extra_slippage_bps"]) < min_extra_bps:
            continue
        pre = dec(row["pre_price_usdc_per_weth"])
        post = dec(row["post_price_usdc_per_weth"])
        gap = abs(post - pre)
        if gap == 0:
            continue
        follow = []
        for nxt in rows[idx + 1 :]:
            if int(nxt["block_number"]) > int(row["block_number"]) + max_blocks:
                break
            if nxt["direction"] != row["direction"]:
                recovery = max(ZERO, (gap - abs(dec(nxt["post_price_usdc_per_weth"]) - pre)) / gap)
                follow.append((nxt, recovery))
        opposite_volume = sum((dec(nxt["size_usd"]) for nxt, _ in follow), ZERO)
        best_recovery = max((recovery for _, recovery in follow), default=ZERO)
        if opposite_volume >= dec(row["size_usd"]) * Decimal("0.25") and best_recovery >= Decimal("0.50"):
            best = max(follow, key=lambda pair: pair[1])[0]
            candidates.append(
                {
                    "anchor": row,
                    "opposite_volume": opposite_volume,
                    "best_recovery": best_recovery,
                    "best": best,
                }
            )
    return sorted(candidates, key=lambda item: dec(item["anchor"]["extra_slippage_usd"]), reverse=True)


def backrun_table(rows: list[dict[str, object]], min_size: Decimal, min_extra_bps: Decimal, max_blocks: int, limit: int = 8) -> list[str]:
    lines = [
        md_row(["Anchor time", "Direction", "Size", "Extra bps", "Extra cost", "Opposite vol <=2 blocks", "Best recovery", "Anchor tx"]),
        md_row(["---", "---", "---:", "---:", "---:", "---:", "---:", "---"]),
    ]
    for item in backrun_candidates(rows, min_size, min_extra_bps, max_blocks)[:limit]:
        anchor = item["anchor"]
        lines.append(md_row([ts(anchor), anchor["direction"], money(dec(anchor["size_usd"])), num(dec(anchor["extra_slippage_bps"])), money(dec(anchor["extra_slippage_usd"])), money(dec(item["opposite_volume"])), pct(dec(item["best_recovery"]), Decimal(1)), tx_link(str(anchor["tx_hash"]))]))
    return lines


def write_report(path: str | Path, pool, rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    volume = total(rows, "size_usd")
    extra_cost = total(rows, "extra_slippage_usd")
    fee_cost = total(rows, "fee_floor_cost_usd")
    extra_bps = [dec(row["extra_slippage_bps"]) for row in rows]
    raw_bps = [dec(row["raw_abs_impact_bps"]) for row in rows]
    max_raw = max(rows, key=lambda row: dec(row["raw_abs_impact_bps"]))
    start = datetime.fromtimestamp(int(rows[0]["block_timestamp"]), tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(int(rows[-1]["block_timestamp"]), tz=timezone.utc).isoformat()
    first_price = dec(rows[0]["pre_price_usdc_per_weth"] or rows[0]["post_price_usdc_per_weth"])
    last_price = dec(rows[-1]["post_price_usdc_per_weth"])
    price_move_bps = (last_price - first_price) / first_price * BPS
    top10 = top_pct(rows, 10)
    round_trips = same_tx_round_trips(rows)
    backruns = backrun_candidates(rows, args.large_min_size_usd, args.large_min_extra_bps, args.backrun_blocks)

    lines = [
        "# Advanced Research Notes",
        "",
        "## Metric Definition",
        "",
        "This report uses realized execution deviation, not wallet UI slippage tolerance. For each Swap, `execution_price = abs(USDC_delta / WETH_delta)`. The pre-swap pool price is approximated with the previous Swap event's post-swap price.",
        "",
        "The 0.05% pool fee is removed before calling a trade expensive. For a buy-WETH swap, the fee-only reference price is `pre_price / (1 - fee_rate)`. For a sell-WETH swap, it is `pre_price * (1 - fee_rate)`. Extra slippage cost is the USDC difference between the realized quote amount and that fee-only reference.",
        "",
        "## Snapshot",
        "",
        f"- Window: {start} to {end}",
        f"- Pool: `{pool.pool_address}` ({pool.token0.symbol}/{pool.token1.symbol}, fee tier {pool.fee}; fee rate {Decimal(pool.fee) / Decimal(10000):.2f}%)",
        f"- Swaps with pre-price: {len(rows):,}",
        f"- Quote-side volume: {money(volume)}",
        f"- Median raw absolute impact: {num(median(raw_bps))} bps",
        f"- Median extra slippage after fee: {num(median(extra_bps))} bps; p95 {num(percentile(extra_bps, Decimal(95)))} bps",
        f"- Estimated fee-floor cost: {money(fee_cost)}; estimated extra slippage cost: {money(extra_cost)}",
        f"- Full-window pool price move: {num(price_move_bps)} bps",
        f"- Top 10% by size: {pct(total(top10, 'size_usd'), volume)} of volume and {pct(total(top10, 'extra_slippage_usd'), extra_cost)} of extra slippage cost",
        f"- Same-tx opposite-direction target-pool candidates: {len(round_trips):,}",
        f"- Backrun-like local candidates: {len(backruns):,}",
        f"- Largest raw impact is {num(dec(max_raw['raw_abs_impact_bps']))} bps on a {money(dec(max_raw['size_usd']))} swap, so raw maxima need a notional floor.",
        "",
        "## Fee-Adjusted Slippage By Size",
        "",
        *size_bucket_table(rows),
        "",
        "## Concentration",
        "",
        *concentration_table(rows),
        "",
        "## Peak Minutes",
        "",
        *minute_table(rows),
        "",
        "## Peak Blocks",
        "",
        *block_table(rows),
        "",
        "## Economic Outliers",
        "",
        f"Minimum notional: {money(args.economic_min_size_usd, 0)}.",
        "",
        *economic_outlier_table(rows, args.economic_min_size_usd),
        "",
        "## Same-Tx Round Trips In The Target Pool",
        "",
        "These are stronger candidates than simple five-minute reversals because the same transaction touches the target pool in both directions. They still need receipt/trace review to determine whether the transaction was arbitrage, routing, liquidation, or another bundled action.",
        "",
        *round_trip_table(rows),
        "",
        "## Backrun-Like Local Candidates",
        "",
        f"Rule: anchor notional >= {money(args.large_min_size_usd, 0)}, extra slippage >= {num(args.large_min_extra_bps)} bps, cumulative opposite-direction target-pool volume >= 25% of anchor notional within {args.backrun_blocks} blocks, and pool price recovers at least 50% of the anchor pre/post gap.",
        "",
        *backrun_table(rows, args.large_min_size_usd, args.large_min_extra_bps, args.backrun_blocks),
        "",
        "## Rules Worth Testing Further",
        "",
        "- Execution-risk rule: ignore raw bps below a notional floor; alert when a route would exceed the $10k-$50k region where extra slippage starts to appear in this sample.",
        "- Liquidity-shock rule: alert on one-minute volume above $1M, net directional pressure above $250k, or minute-level pool-price movement above 50 bps.",
        "- Backrun candidate rule: combine large notional, high fee-adjusted slippage, material opposite flow within one or two blocks, and fast price recovery.",
        "- Higher-confidence MEV/arbitrage rule: inspect receipts for transactions that touch the target pool and another WETH/USDC fee tier in opposite directions in the same transaction.",
        "- Negative rule: do not use 'any opposite swap within five minutes' as a signal here; the pool is active enough that this mostly measures background flow.",
        "",
    ]
    out.write_text("\n".join(lines))


def main() -> None:
    args = build_parser().parse_args()
    conn = connect(args.db)
    pool = pool_tokens_from_row(load_pool_row(conn, args.pool))
    raw = load_swap_rows(conn, pool.pool_address)
    enriched = enrich_swaps(raw, pool, args.base_symbol, args.quote_symbol)
    rows = add_fee_adjusted_metrics(enriched, pool.fee)
    if not rows:
        raise SystemExit("No rows with pre-swap prices. Fetch a larger range first.")
    write_report(args.output, pool, rows, args)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
