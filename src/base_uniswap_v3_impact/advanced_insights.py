from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .analyze import enrich_swaps, load_swap_rows, percentile, pool_tokens_from_row
from .config import DEFAULT_DB_PATH
from .db import connect, load_pool_row

getcontext().prec = 80

BPS = Decimal("10000")
ZERO = Decimal(0)
SIZE_BUCKETS = ["<1k", "1k-10k", "10k-50k", "50k-100k", "100k-250k", "250k-500k", "500k-1m", ">=1m"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write structured fee-adjusted metrics and case candidates.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pool")
    parser.add_argument("--base-symbol", default="WETH")
    parser.add_argument("--quote-symbol", default="USDC")
    parser.add_argument("--output", default="output/advanced_metrics.json")
    parser.add_argument("--economic-min-size-usd", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--large-min-size-usd", type=Decimal, default=Decimal("50000"))
    parser.add_argument("--large-min-extra-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--backrun-blocks", type=int, default=2)
    return parser


def dec(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def iso_from_ts(block_timestamp: object) -> str:
    return datetime.fromtimestamp(int(block_timestamp), tz=timezone.utc).isoformat()


def short_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "datetime_utc": iso_from_ts(row["block_timestamp"]),
        "block_number": int(row["block_number"]),
        "tx_hash": row["tx_hash"],
        "log_index": int(row["log_index"]),
        "direction": row["direction"],
        "size_usd": dec(row["size_usd"]),
        "base_amount": dec(row["base_amount"]),
        "pre_price_usdc_per_weth": dec(row["pre_price_usdc_per_weth"]),
        "execution_price_usdc_per_weth": dec(row["execution_price_usdc_per_weth"]),
        "post_price_usdc_per_weth": dec(row["post_price_usdc_per_weth"]),
        "raw_abs_impact_bps": dec(row["raw_abs_impact_bps"]),
        "extra_slippage_bps": dec(row["extra_slippage_bps"]),
        "extra_slippage_usd": dec(row["extra_slippage_usd"]),
        "post_price_change_bps": row["post_price_change_bps"],
    }


def add_fee_adjusted_metrics(rows: list[dict[str, object]], pool_fee: int) -> list[dict[str, object]]:
    fee_rate = Decimal(pool_fee) / Decimal(1_000_000)
    out: list[dict[str, object]] = []
    for row in rows:
        if row["pre_price_usdc_per_weth"] is None:
            continue
        pre_price = dec(row["pre_price_usdc_per_weth"])
        execution_price = dec(row["execution_price_usdc_per_weth"])
        base_amount = dec(row["base_amount"])
        quote_amount = dec(row["quote_amount"])
        raw_signed_bps = (execution_price - pre_price) / pre_price * BPS
        if row["direction"] == "buy_base":
            fee_only_price = pre_price / (Decimal(1) - fee_rate)
            fee_only_quote = base_amount * fee_only_price
            extra_cost = max(quote_amount - fee_only_quote, ZERO)
        else:
            fee_only_price = pre_price * (Decimal(1) - fee_rate)
            fee_only_quote = base_amount * fee_only_price
            extra_cost = max(fee_only_quote - quote_amount, ZERO)

        enriched = dict(row)
        enriched.update(
            {
                "raw_signed_impact_bps": raw_signed_bps,
                "raw_abs_impact_bps": abs(raw_signed_bps),
                "fee_only_execution_price": fee_only_price,
                "fee_floor_bps": abs((fee_only_price - pre_price) / pre_price * BPS),
                "fee_floor_cost_usd": abs(fee_only_quote - base_amount * pre_price),
                "extra_slippage_usd": extra_cost,
                "extra_slippage_bps": extra_cost / quote_amount * BPS if quote_amount else ZERO,
                "post_price_change_bps": dec(row["post_price_change_pct"]) * Decimal(100)
                if row["post_price_change_pct"] is not None
                else None,
            }
        )
        out.append(enriched)
    return out


def total(rows: Iterable[dict[str, object]], key: str) -> Decimal:
    return sum((dec(row[key]) for row in rows), ZERO)


def top_pct(rows: list[dict[str, object]], pct_value: int) -> list[dict[str, object]]:
    count = max(1, math.ceil(len(rows) * pct_value / 100))
    return sorted(rows, key=lambda row: dec(row["size_usd"]), reverse=True)[:count]


def summarize_by_size(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    volume = total(rows, "size_usd")
    out = []
    for bucket in SIZE_BUCKETS:
        subset = [row for row in rows if row["size_bucket"] == bucket]
        if not subset:
            continue
        raw = [dec(row["raw_abs_impact_bps"]) for row in subset]
        extra = [dec(row["extra_slippage_bps"]) for row in subset]
        out.append(
            {
                "size_bucket": bucket,
                "swaps": len(subset),
                "volume_usd": total(subset, "size_usd"),
                "volume_share_pct": total(subset, "size_usd") / volume * Decimal(100),
                "median_raw_abs_impact_bps": median(raw),
                "median_extra_slippage_bps": median(extra),
                "p95_extra_slippage_bps": percentile(extra, Decimal(95)),
            }
        )
    return out


def concentration(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    volume = total(rows, "size_usd")
    cost = total(rows, "extra_slippage_usd")
    out = []
    for pct_value in (1, 5, 10):
        subset = top_pct(rows, pct_value)
        out.append(
            {
                "segment": f"top_{pct_value}_pct_by_size",
                "swaps": len(subset),
                "volume_usd": total(subset, "size_usd"),
                "volume_share_pct": total(subset, "size_usd") / volume * Decimal(100),
                "extra_slippage_usd": total(subset, "extra_slippage_usd"),
                "extra_slippage_cost_share_pct": total(subset, "extra_slippage_usd") / cost * Decimal(100) if cost else None,
            }
        )
    return out


def period_stats(rows: list[dict[str, object]], seconds: int) -> list[dict[str, object]]:
    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[int(row["block_timestamp"]) // seconds * seconds].append(row)
    stats = []
    for start_ts, subset in groups.items():
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        start_price = dec(subset[0]["pre_price_usdc_per_weth"] or subset[0]["post_price_usdc_per_weth"])
        end_price = dec(subset[-1]["post_price_usdc_per_weth"])
        stats.append(
            {
                "start_utc": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
                "swaps": len(subset),
                "volume_usd": buy + sell,
                "buy_volume_usd": buy,
                "sell_volume_usd": sell,
                "net_buy_weth_quote_volume_usd": buy - sell,
                "price_move_bps": (end_price - start_price) / start_price * BPS,
                "extra_slippage_usd": total(subset, "extra_slippage_usd"),
            }
        )
    return sorted(stats, key=lambda item: dec(item["volume_usd"]), reverse=True)


def block_stats(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_block: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_block[int(row["block_number"])].append(row)
    stats = []
    for block_number, subset in by_block.items():
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        start_price = dec(subset[0]["pre_price_usdc_per_weth"] or subset[0]["post_price_usdc_per_weth"])
        end_price = dec(subset[-1]["post_price_usdc_per_weth"])
        stats.append(
            {
                "block_number": block_number,
                "datetime_utc": iso_from_ts(subset[0]["block_timestamp"]),
                "swaps": len(subset),
                "volume_usd": buy + sell,
                "buy_volume_usd": buy,
                "sell_volume_usd": sell,
                "net_buy_weth_quote_volume_usd": buy - sell,
                "price_move_bps": (end_price - start_price) / start_price * BPS,
                "extra_slippage_usd": total(subset, "extra_slippage_usd"),
            }
        )
    return sorted(stats, key=lambda item: dec(item["volume_usd"]), reverse=True)


def same_tx_round_trips(rows: list[dict[str, object]], min_volume_usd: Decimal = Decimal("1000")) -> list[dict[str, object]]:
    by_tx: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_tx[str(row["tx_hash"])].append(row)
    candidates = []
    for tx_hash, subset in by_tx.items():
        if len(subset) < 2 or len({row["direction"] for row in subset}) == 1:
            continue
        buy = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "buy_base"), ZERO)
        sell = sum((dec(row["size_usd"]) for row in subset if row["direction"] == "sell_base"), ZERO)
        gross = buy + sell
        if gross < min_volume_usd:
            continue
        candidates.append(
            {
                "tx_hash": tx_hash,
                "datetime_utc": iso_from_ts(subset[0]["block_timestamp"]),
                "block_number": int(subset[0]["block_number"]),
                "target_pool_swap_logs": len(subset),
                "gross_target_pool_volume_usd": gross,
                "buy_volume_usd": buy,
                "sell_volume_usd": sell,
                "net_buy_weth_quote_volume_usd": buy - sell,
                "extra_slippage_usd": total(subset, "extra_slippage_usd"),
                "directions": [row["direction"] for row in subset],
            }
        )
    return sorted(candidates, key=lambda row: dec(row["gross_target_pool_volume_usd"]), reverse=True)


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
                    "anchor": short_row(row),
                    "opposite_volume_usd_within_window": opposite_volume,
                    "best_recovery_pct": best_recovery * Decimal(100),
                    "best_recovery_swap": short_row(best),
                }
            )
    return sorted(candidates, key=lambda item: dec(item["anchor"]["extra_slippage_usd"]), reverse=True)


def build_metrics(pool, rows: list[dict[str, object]], args: argparse.Namespace) -> dict[str, object]:
    volume = total(rows, "size_usd")
    fee_cost = total(rows, "fee_floor_cost_usd")
    extra_cost = total(rows, "extra_slippage_usd")
    raw_bps = [dec(row["raw_abs_impact_bps"]) for row in rows]
    extra_bps = [dec(row["extra_slippage_bps"]) for row in rows]
    max_raw = max(rows, key=lambda row: dec(row["raw_abs_impact_bps"]))
    first_price = dec(rows[0]["pre_price_usdc_per_weth"] or rows[0]["post_price_usdc_per_weth"])
    last_price = dec(rows[-1]["post_price_usdc_per_weth"])
    top10 = top_pct(rows, 10)
    round_trips = same_tx_round_trips(rows)
    backruns = backrun_candidates(rows, args.large_min_size_usd, args.large_min_extra_bps, args.backrun_blocks)
    return {
        "dataset": {
            "pool_address": pool.pool_address,
            "pair": f"{pool.token0.symbol}/{pool.token1.symbol}",
            "fee_tier": pool.fee,
            "fee_rate": Decimal(pool.fee) / Decimal(1_000_000),
            "start_utc": iso_from_ts(rows[0]["block_timestamp"]),
            "end_utc": iso_from_ts(rows[-1]["block_timestamp"]),
            "swaps_with_pre_price": len(rows),
        },
        "metric_definition": {
            "execution_price": "abs(USDC_delta / WETH_delta)",
            "pre_swap_price": "previous target-pool Swap event's post-swap price",
            "raw_impact_bps": "(execution_price - pre_swap_pool_price) / pre_swap_pool_price * 10000",
            "buy_fee_only_price": "pre_price / (1 - fee_rate)",
            "sell_fee_only_price": "pre_price * (1 - fee_rate)",
            "buy_extra_slippage_usd": "actual_USDC_paid - WETH_received * fee_only_price, clipped at zero",
            "sell_extra_slippage_usd": "WETH_sold * fee_only_price - actual_USDC_received, clipped at zero",
        },
        "headline_metrics": {
            "quote_side_volume_usd": volume,
            "median_raw_abs_impact_bps": median(raw_bps),
            "median_extra_slippage_bps": median(extra_bps),
            "p95_extra_slippage_bps": percentile(extra_bps, Decimal(95)),
            "estimated_fee_floor_cost_usd": fee_cost,
            "estimated_extra_slippage_cost_usd": extra_cost,
            "full_window_price_move_bps": (last_price - first_price) / first_price * BPS,
            "top_10_pct_volume_share_pct": total(top10, "size_usd") / volume * Decimal(100),
            "top_10_pct_extra_slippage_cost_share_pct": total(top10, "extra_slippage_usd") / extra_cost * Decimal(100) if extra_cost else None,
            "same_tx_opposite_direction_candidates": len(round_trips),
            "backrun_like_local_candidates": len(backruns),
            "largest_raw_impact_swap": short_row(max_raw),
        },
        "by_size_bucket": summarize_by_size(rows),
        "concentration_by_trade_size": concentration(rows),
        "top_minutes_by_volume": period_stats(rows, 60)[:12],
        "top_blocks_by_volume": block_stats(rows)[:12],
        "economic_outliers_by_extra_slippage_cost": [
            short_row(row)
            for row in sorted(
                [row for row in rows if dec(row["size_usd"]) >= args.economic_min_size_usd],
                key=lambda row: dec(row["extra_slippage_usd"]),
                reverse=True,
            )[:12]
        ],
        "same_tx_round_trip_candidates": round_trips[:12],
        "backrun_like_local_candidates": backruns[:12],
        "candidate_rules": {
            "economic_outlier_min_size_usd": args.economic_min_size_usd,
            "backrun_min_size_usd": args.large_min_size_usd,
            "backrun_min_extra_slippage_bps": args.large_min_extra_bps,
            "backrun_max_blocks": args.backrun_blocks,
            "backrun_requires_opposite_volume_ratio": Decimal("0.25"),
            "backrun_requires_best_recovery_pct": Decimal("50"),
        },
    }


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main() -> None:
    args = build_parser().parse_args()
    conn = connect(args.db)
    pool = pool_tokens_from_row(load_pool_row(conn, args.pool))
    raw = load_swap_rows(conn, pool.pool_address)
    enriched = enrich_swaps(raw, pool, args.base_symbol, args.quote_symbol)
    rows = add_fee_adjusted_metrics(enriched, pool.fee)
    if not rows:
        raise SystemExit("No rows with pre-swap prices. Fetch a larger range first.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_metrics(pool, rows, args), indent=2, default=json_default) + "\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
