from __future__ import annotations

import argparse
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from statistics import median
from typing import Iterable

from .analyze import (
    PoolTokens,
    enrich_swaps,
    load_swap_rows,
    percentile,
    pool_tokens_from_row,
)
from .config import DEFAULT_DB_PATH
from .db import connect, load_pool_row

getcontext().prec = 80

BPS_PER_PERCENT = Decimal("100")
BPS_PER_UNIT = Decimal("10000")
ZERO = Decimal(0)

BUCKET_ORDER = [
    "<1k",
    "1k-10k",
    "10k-50k",
    "50k-100k",
    "100k-250k",
    "250k-500k",
    "500k-1m",
    ">=1m",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate fee-adjusted and flow-based insights from collected Base Uniswap v3 swaps."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pool")
    parser.add_argument("--base-symbol", default="WETH")
    parser.add_argument("--quote-symbol", default="USDC")
    parser.add_argument("--output", default="output/advanced_insights.md")
    parser.add_argument("--opposite-window-seconds", type=int, default=300)
    parser.add_argument("--recovery-window-seconds", type=int, default=600)
    parser.add_argument("--economic-min-size-usd", type=Decimal, default=Decimal("1000"))
    return parser


def d(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def pct(part: Decimal, total: Decimal, digits: int = 1) -> str:
    if total == 0:
        return "n/a"
    return f"{(part / total * Decimal(100)):.{digits}f}%"


def bps(value: Decimal | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def usd(value: Decimal | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"${value:,.{digits}f}"


def usd_precise(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) < Decimal("1"):
        return f"${value:,.8f}"
    return usd(value)


def short_tx(tx_hash: str) -> str:
    return f"{tx_hash[:8]}...{tx_hash[-6:]}"


def row_key(row: dict[str, object]) -> tuple[str, int]:
    return str(row["tx_hash"]), int(row["log_index"])


def pool_fee_bps(pool: PoolTokens) -> Decimal:
    return Decimal(pool.fee) / Decimal(100)


def valid_impact_rows(rows: Iterable[dict[str, object]], pool: PoolTokens) -> list[dict[str, object]]:
    fee = pool_fee_bps(pool)
    valid: list[dict[str, object]] = []
    for row in rows:
        if row["abs_price_impact_pct"] is None:
            continue
        abs_impact_bps = d(row["abs_price_impact_pct"]) * BPS_PER_PERCENT
        extra_impact_bps = max(abs_impact_bps - fee, ZERO)
        size_usd = d(row["size_usd"])
        enriched = dict(row)
        enriched["abs_impact_bps"] = abs_impact_bps
        enriched["extra_impact_bps"] = extra_impact_bps
        enriched["fee_cost_usd"] = size_usd * fee / BPS_PER_UNIT
        enriched["extra_slippage_cost_usd"] = size_usd * extra_impact_bps / BPS_PER_UNIT
        if row["post_price_change_pct"] is not None:
            enriched["post_price_change_bps"] = d(row["post_price_change_pct"]) * BPS_PER_PERCENT
        else:
            enriched["post_price_change_bps"] = None
        valid.append(enriched)
    return valid


def sum_decimal(rows: Iterable[dict[str, object]], key: str) -> Decimal:
    total = ZERO
    for row in rows:
        total += d(row[key])
    return total


def first_threshold_bucket(rows: list[dict[str, object]]) -> str:
    for bucket in BUCKET_ORDER:
        subset = [d(row["extra_impact_bps"]) for row in rows if row["size_bucket"] == bucket]
        if not subset:
            continue
        med = median(subset)
        p75 = percentile(subset, Decimal(75))
        if med >= Decimal("1") or (p75 is not None and p75 >= Decimal("2")):
            return bucket
    return "not visible in this sample"


def top_share(rows: list[dict[str, object]], pct_value: Decimal) -> dict[str, Decimal | int]:
    count = max(1, math.ceil(len(rows) * float(pct_value) / 100))
    top = sorted(rows, key=lambda row: d(row["size_usd"]), reverse=True)[:count]
    return {
        "count": count,
        "volume": sum_decimal(top, "size_usd"),
        "fee_cost": sum_decimal(top, "fee_cost_usd"),
        "extra_cost": sum_decimal(top, "extra_slippage_cost_usd"),
    }


def direction_lines(rows: list[dict[str, object]], total_volume: Decimal) -> list[str]:
    lines = []
    for direction in ("buy_base", "sell_base"):
        subset = [row for row in rows if row["direction"] == direction]
        if not subset:
            continue
        sizes = [d(row["size_usd"]) for row in subset]
        extra = [d(row["extra_impact_bps"]) for row in subset]
        p95 = percentile(extra, Decimal(95))
        lines.append(
            "| "
            + " | ".join(
                [
                    direction,
                    f"{len(subset):,}",
                    usd(sum(sizes, ZERO)),
                    pct(sum(sizes, ZERO), total_volume),
                    usd(median(sizes)),
                    bps(median(extra)),
                    bps(p95),
                ]
            )
            + " |"
        )
    return lines


def bucket_lines(rows: list[dict[str, object]], total_volume: Decimal) -> list[str]:
    lines = []
    for bucket in BUCKET_ORDER:
        subset = [row for row in rows if row["size_bucket"] == bucket]
        if not subset:
            continue
        abs_impacts = [d(row["abs_impact_bps"]) for row in subset]
        extra = [d(row["extra_impact_bps"]) for row in subset]
        volume = sum_decimal(subset, "size_usd")
        p75 = percentile(extra, Decimal(75))
        p95 = percentile(extra, Decimal(95))
        lines.append(
            "| "
            + " | ".join(
                [
                    bucket,
                    f"{len(subset):,}",
                    usd(volume),
                    pct(volume, total_volume),
                    bps(median(abs_impacts)),
                    bps(median(extra)),
                    bps(p75),
                    bps(p95),
                ]
            )
            + " |"
        )
    return lines


def hourly_lines(rows: list[dict[str, object]]) -> tuple[list[str], dict[str, object] | None]:
    grouped: dict[datetime, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        hour = datetime.fromtimestamp(int(row["block_timestamp"]), tz=timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        grouped[hour].append(row)

    lines = []
    strongest: dict[str, object] | None = None
    for hour in sorted(grouped):
        subset = grouped[hour]
        volume = sum_decimal(subset, "size_usd")
        buy_volume = sum_decimal((row for row in subset if row["direction"] == "buy_base"), "size_usd")
        sell_volume = sum_decimal((row for row in subset if row["direction"] == "sell_base"), "size_usd")
        net_buy_volume = buy_volume - sell_volume
        start_price = d(subset[0]["post_price_usdc_per_weth"])
        end_price = d(subset[-1]["post_price_usdc_per_weth"])
        price_change_bps = (end_price - start_price) / start_price * BPS_PER_UNIT if start_price else ZERO
        extra = [d(row["extra_impact_bps"]) for row in subset]
        row_info = {
            "hour": hour,
            "swaps": len(subset),
            "volume": volume,
            "net_buy_volume": net_buy_volume,
            "price_change_bps": price_change_bps,
            "median_extra": median(extra),
        }
        if strongest is None or abs(price_change_bps) > abs(d(str(strongest["price_change_bps"]))):
            strongest = row_info
        lines.append(
            "| "
            + " | ".join(
                [
                    hour.strftime("%Y-%m-%d %H:00"),
                    f"{len(subset):,}",
                    usd(volume),
                    usd(net_buy_volume),
                    bps(price_change_bps),
                    bps(median(extra)),
                ]
            )
            + " |"
        )
    return lines, strongest


def flow_follow_through(
    rows: list[dict[str, object]], anchor_rows: list[dict[str, object]], window_seconds: int
) -> dict[str, object]:
    anchor_keys = {row_key(row) for row in anchor_rows}
    ratios: list[Decimal] = []
    first_opposite_seconds: list[int] = []
    material_25 = 0
    material_50 = 0
    material_100 = 0
    any_opposite = 0

    for idx, row in enumerate(rows):
        if row_key(row) not in anchor_keys:
            continue
        anchor_ts = int(row["block_timestamp"])
        anchor_direction = row["direction"]
        anchor_size = d(row["size_usd"])
        opposite_volume = ZERO
        first_opposite: int | None = None
        for nxt in rows[idx + 1 :]:
            elapsed = int(nxt["block_timestamp"]) - anchor_ts
            if elapsed > window_seconds:
                break
            if nxt["direction"] != anchor_direction:
                opposite_volume += d(nxt["size_usd"])
                if first_opposite is None:
                    first_opposite = elapsed
        ratio = opposite_volume / anchor_size if anchor_size else ZERO
        ratios.append(ratio)
        if first_opposite is not None:
            any_opposite += 1
            first_opposite_seconds.append(first_opposite)
        if ratio >= Decimal("0.25"):
            material_25 += 1
        if ratio >= Decimal("0.50"):
            material_50 += 1
        if ratio >= Decimal("1.00"):
            material_100 += 1

    total = len(anchor_rows)
    return {
        "anchors": total,
        "any_opposite": any_opposite,
        "material_25": material_25,
        "material_50": material_50,
        "material_100": material_100,
        "median_ratio": median(ratios) if ratios else None,
        "median_first_opposite_seconds": median(first_opposite_seconds) if first_opposite_seconds else None,
    }


def recovery_stats(
    rows: list[dict[str, object]], anchor_rows: list[dict[str, object]], window_seconds: int
) -> dict[str, object]:
    anchor_keys = {row_key(row) for row in anchor_rows}
    recovered_seconds: list[int] = []
    evaluated = 0
    for idx, row in enumerate(rows):
        if row_key(row) not in anchor_keys:
            continue
        if row["pre_price_usdc_per_weth"] is None:
            continue
        pre_price = d(row["pre_price_usdc_per_weth"])
        post_price = d(row["post_price_usdc_per_weth"])
        initial_gap = abs(post_price - pre_price)
        if initial_gap == 0:
            continue
        evaluated += 1
        target_gap = initial_gap * Decimal("0.25")
        anchor_ts = int(row["block_timestamp"])
        for nxt in rows[idx + 1 :]:
            elapsed = int(nxt["block_timestamp"]) - anchor_ts
            if elapsed > window_seconds:
                break
            future_gap = abs(d(nxt["post_price_usdc_per_weth"]) - pre_price)
            if future_gap <= target_gap:
                recovered_seconds.append(elapsed)
                break
    return {
        "evaluated": evaluated,
        "recovered": len(recovered_seconds),
        "median_seconds": median(recovered_seconds) if recovered_seconds else None,
    }


def concentration_lines(rows: list[dict[str, object]], total_volume: Decimal, total_extra_cost: Decimal) -> list[str]:
    lines = []
    for pct_value in (Decimal(1), Decimal(5), Decimal(10)):
        stats = top_share(rows, pct_value)
        volume = d(stats["volume"])
        extra_cost = d(stats["extra_cost"])
        lines.append(
            "| "
            + " | ".join(
                [
                    f"Top {pct_value:.0f}%",
                    f"{int(stats['count']):,}",
                    usd(volume),
                    pct(volume, total_volume),
                    usd(extra_cost),
                    pct(extra_cost, total_extra_cost),
                ]
            )
            + " |"
        )
    return lines


def outlier_lines(rows: list[dict[str, object]], min_size_usd: Decimal, limit: int = 8) -> list[str]:
    candidates = [row for row in rows if d(row["size_usd"]) >= min_size_usd]
    top_rows = sorted(candidates, key=lambda row: (d(row["extra_impact_bps"]), d(row["size_usd"])), reverse=True)[:limit]
    lines = []
    for row in top_rows:
        time_label = datetime.fromtimestamp(int(row["block_timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        tx_hash = str(row["tx_hash"])
        post_move = row["post_price_change_bps"]
        lines.append(
            "| "
            + " | ".join(
                [
                    time_label,
                    str(row["direction"]),
                    usd(d(row["size_usd"])),
                    bps(d(row["extra_impact_bps"])),
                    bps(d(row["abs_impact_bps"])),
                    bps(d(post_move) if post_move is not None else None),
                    f"[{short_tx(tx_hash)}](https://basescan.org/tx/{tx_hash})",
                ]
            )
            + " |"
        )
    return lines


def cost_outlier_lines(rows: list[dict[str, object]], min_size_usd: Decimal, limit: int = 8) -> list[str]:
    candidates = [row for row in rows if d(row["size_usd"]) >= min_size_usd]
    top_rows = sorted(candidates, key=lambda row: d(row["extra_slippage_cost_usd"]), reverse=True)[:limit]
    lines = []
    for row in top_rows:
        time_label = datetime.fromtimestamp(int(row["block_timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        tx_hash = str(row["tx_hash"])
        lines.append(
            "| "
            + " | ".join(
                [
                    time_label,
                    str(row["direction"]),
                    usd(d(row["size_usd"])),
                    bps(d(row["extra_impact_bps"])),
                    usd(d(row["extra_slippage_cost_usd"])),
                    f"[{short_tx(tx_hash)}](https://basescan.org/tx/{tx_hash})",
                ]
            )
            + " |"
        )
    return lines


def flow_line(label: str, stats: dict[str, object]) -> str:
    anchors = Decimal(int(stats["anchors"]))
    median_ratio = stats["median_ratio"]
    median_seconds = stats["median_first_opposite_seconds"]
    return (
        "| "
        + " | ".join(
            [
                label,
                f"{int(stats['anchors']):,}",
                pct(Decimal(int(stats["any_opposite"])), anchors),
                pct(Decimal(int(stats["material_25"])), anchors),
                pct(Decimal(int(stats["material_50"])), anchors),
                pct(Decimal(int(stats["material_100"])), anchors),
                f"{median_ratio:.2f}x" if isinstance(median_ratio, Decimal) else "n/a",
                f"{median_seconds:.0f}" if isinstance(median_seconds, (int, float)) else "n/a",
            ]
        )
        + " |"
    )


def write_advanced_insights(
    path: str | Path,
    pool: PoolTokens,
    rows: list[dict[str, object]],
    impact_rows: list[dict[str, object]],
    opposite_window_seconds: int,
    recovery_window_seconds: int,
    economic_min_size_usd: Decimal,
) -> None:
    if not rows or not impact_rows:
        raise SystemExit("Need analyzable swaps with pre-swap impact to write advanced insights.")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fee = pool_fee_bps(pool)
    total_volume = sum_decimal(impact_rows, "size_usd")
    total_fee_cost = sum_decimal(impact_rows, "fee_cost_usd")
    total_extra_cost = sum_decimal(impact_rows, "extra_slippage_cost_usd")
    sizes = [d(row["size_usd"]) for row in impact_rows]
    extra = [d(row["extra_impact_bps"]) for row in impact_rows]
    abs_impacts = [d(row["abs_impact_bps"]) for row in impact_rows]
    threshold_bucket = first_threshold_bucket(impact_rows)
    economic_rows = [row for row in impact_rows if d(row["size_usd"]) >= economic_min_size_usd]
    max_raw_impact = max(impact_rows, key=lambda row: d(row["extra_impact_bps"]))
    p90_size = percentile(sizes, Decimal(90))
    top_decile = [row for row in impact_rows if p90_size is not None and d(row["size_usd"]) >= p90_size]
    lower_90 = [row for row in impact_rows if p90_size is not None and d(row["size_usd"]) < p90_size]
    top_flow = flow_follow_through(impact_rows, top_decile, opposite_window_seconds)
    lower_flow = flow_follow_through(impact_rows, lower_90, opposite_window_seconds)
    top_recovery = recovery_stats(impact_rows, top_decile, recovery_window_seconds)
    hourly, strongest_hour = hourly_lines(impact_rows)
    start_dt = datetime.fromtimestamp(int(rows[0]["block_timestamp"]), tz=timezone.utc)
    end_dt = datetime.fromtimestamp(int(rows[-1]["block_timestamp"]), tz=timezone.utc)
    start_price = d(rows[0]["post_price_usdc_per_weth"])
    end_price = d(rows[-1]["post_price_usdc_per_weth"])
    price_drift_bps = (end_price - start_price) / start_price * BPS_PER_UNIT if start_price else ZERO
    buy_volume = sum_decimal((row for row in impact_rows if row["direction"] == "buy_base"), "size_usd")
    sell_volume = sum_decimal((row for row in impact_rows if row["direction"] == "sell_base"), "size_usd")
    net_buy_volume = buy_volume - sell_volume
    extra_cost_top10 = top_share(impact_rows, Decimal(10))
    p95_extra = percentile(extra, Decimal(95))

    material_top = Decimal(int(top_flow["material_50"]))
    material_lower = Decimal(int(lower_flow["material_50"]))
    top_anchors = Decimal(int(top_flow["anchors"]))
    lower_anchors = Decimal(int(lower_flow["anchors"]))
    top_material_pct = pct(material_top, top_anchors)
    lower_material_pct = pct(material_lower, lower_anchors)
    recovery_rate = pct(Decimal(int(top_recovery["recovered"])), Decimal(int(top_recovery["evaluated"])))

    strongest_hour_text = "n/a"
    strongest_hour_volume_share = "n/a"
    if strongest_hour is not None:
        strongest_hour_volume_share = pct(d(str(strongest_hour["volume"])), total_volume)
        strongest_hour_text = (
            f"{strongest_hour['hour'].strftime('%Y-%m-%d %H:00 UTC')} "
            f"({bps(d(str(strongest_hour['price_change_bps'])))} bps price move, "
            f"{usd(d(str(strongest_hour['volume'])))} volume)"
        )

    if material_top <= material_lower:
        opposite_interpretation = (
            f"- A simple opposite-flow rule is not discriminative in this pool: {top_material_pct} of top-decile "
            f"swaps had opposite-direction volume of at least 50% within {opposite_window_seconds // 60} minutes, "
            f"but the lower 90% was also {lower_material_pct}. That means reversal counts should be treated as "
            "background activity unless combined with a notional floor and recovery behavior."
        )
    else:
        opposite_interpretation = (
            f"- Material opposite flow is elevated for large swaps: {top_material_pct} of top-decile swaps had "
            f"opposite-direction volume of at least 50% within {opposite_window_seconds // 60} minutes, versus "
            f"{lower_material_pct} for the rest."
        )

    lines = [
        "# Advanced Findings",
        "",
        "## Dataset",
        "",
        f"- Pool: `{pool.pool_address}` ({pool.token0.symbol}/{pool.token1.symbol}, fee tier {pool.fee})",
        f"- Window: {start_dt.isoformat()} to {end_dt.isoformat()}",
        f"- Swaps with fee-adjusted impact: {len(impact_rows):,}",
        f"- Total quote-side volume: {usd(total_volume)}",
        "",
        "## Executive Findings",
        "",
        (
            f"- The headline median absolute impact of {bps(median(abs_impacts))} bps is mostly the "
            f"{bps(fee)} bps pool fee. After subtracting that fee floor, median extra slippage is "
            f"{bps(median(extra))} bps and p95 extra slippage is {bps(p95_extra)} bps."
        ),
        (
            f"- The first size bucket where fee-adjusted impact becomes clearly visible is `{threshold_bucket}`. "
            "Below that level, most swaps are paying the pool fee rather than moving the curve very much."
        ),
        (
            f"- Flow is concentrated: the largest 10% of swaps contributed "
            f"{pct(d(extra_cost_top10['volume']), total_volume)} of volume and "
            f"{pct(d(extra_cost_top10['extra_cost']), total_extra_cost)} of estimated extra slippage cost."
        ),
        (
            f"- Tail economics matter more than tail percentages. Estimated extra slippage beyond the fee floor "
            f"was {usd(total_extra_cost)}, higher than the estimated pool-fee cost of {usd(total_fee_cost)}, "
            "even though the median extra slippage was close to zero."
        ),
        (
            f"- The pool price moved {bps(price_drift_bps)} bps over the four-hour sample, while median "
            f"extra single-swap slippage was {bps(median(extra))} bps. For most trades, market drift was "
            "a larger risk than immediate curve impact."
        ),
        (
            f"- The strongest hourly regime was {strongest_hour_text}, representing {strongest_hour_volume_share} "
            "of the sample volume."
        ),
        opposite_interpretation,
        (
            f"- The largest raw extra-impact observation was {bps(d(max_raw_impact['extra_impact_bps']))} bps on a "
            f"{usd_precise(d(max_raw_impact['size_usd']))} swap. This is a dust/rounding artifact, so economic "
            f"outlier review below applies a {usd(economic_min_size_usd, 0)} notional floor."
        ),
        "",
        "## Fee-Adjusted Impact By Size",
        "",
        "| Size bucket | Swaps | Volume | Volume share | Median abs impact (bps) | Median extra bps | P75 extra bps | P95 extra bps |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *bucket_lines(impact_rows, total_volume),
        "",
        "## Volume Concentration",
        "",
        f"Estimated pool-fee cost is approximately {usd(total_fee_cost)}. Estimated extra slippage cost beyond the fee floor is approximately {usd(total_extra_cost)}.",
        "",
        "| Segment by trade size | Swaps | Volume | Volume share | Extra slippage cost | Extra cost share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *concentration_lines(impact_rows, total_volume, total_extra_cost),
        "",
        "## Direction Asymmetry",
        "",
        f"Net buy-WETH quote volume was {usd(net_buy_volume)} (buy volume minus sell volume).",
        "",
        "| Direction | Swaps | Volume | Volume share | Median size | Median extra bps | P95 extra bps |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *direction_lines(impact_rows, total_volume),
        "",
        "## Hourly Regimes",
        "",
        f"The strongest one-hour pool-price move was {strongest_hour_text}.",
        "",
        "| UTC hour | Swaps | Volume | Net buy-WETH volume | Price move (bps) | Median extra bps |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *hourly,
        "",
        "## Large-Swap Follow-Through",
        "",
        (
            f"Top-decile swap threshold: {usd(p90_size)}. Window: {opposite_window_seconds} seconds. "
            "Opposite-flow ratios compare cumulative opposite-direction volume after the anchor swap with the anchor swap size."
        ),
        "",
        "| Segment | Anchors | Any opposite flow | Opposite >=25% | Opposite >=50% | Opposite >=100% | Median opposite/anchor | Median first opposite seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        flow_line("Top-decile size", top_flow),
        flow_line("Lower 90% size", lower_flow),
        "",
        "## Price Recovery After Top-Decile Swaps",
        "",
        (
            f"Within {recovery_window_seconds} seconds, {top_recovery['recovered']:,}/{top_recovery['evaluated']:,} "
            f"top-decile swaps saw the pool price return to within 25% of the anchor swap's pre/post price gap "
            f"({recovery_rate}). Median recovery time: {top_recovery['median_seconds'] or 'n/a'} seconds."
        ),
        "",
        "## Largest Fee-Adjusted Impact Transactions",
        "",
        f"These rows apply a {usd(economic_min_size_usd, 0)} minimum notional filter. Economic rows in scope: {len(economic_rows):,}.",
        "",
        "| UTC time | Direction | Size | Extra bps | Abs impact bps | Post-price move bps | Tx |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        *outlier_lines(impact_rows, economic_min_size_usd),
        "",
        "## Largest Extra-Slippage Dollar Contributors",
        "",
        "| UTC time | Direction | Size | Extra bps | Estimated extra cost | Tx |",
        "| --- | --- | ---: | ---: | ---: | --- |",
        *cost_outlier_lines(impact_rows, economic_min_size_usd),
        "",
        "## Interpretation",
        "",
        "- Treat the 5 bps pool fee as the execution-cost floor. The research value is in the residual above that floor.",
        "- Size is the clearer near-term driver than raw in-range liquidity in this short sample.",
        "- Raw max-impact rankings must apply a notional floor; otherwise dust swaps dominate the outlier list.",
        "- Simple reversal counts are too noisy for this high-frequency pool. Stronger candidates combine large notional, high extra slippage, material opposite flow, and rapid price recovery.",
        "- The follow-through and recovery metrics identify candidates for manual transaction-level review; they do not prove arbitrage or MEV by themselves.",
        "",
    ]
    output.write_text("\n".join(lines))


def main() -> None:
    args = build_parser().parse_args()
    conn = connect(args.db)
    pool = pool_tokens_from_row(load_pool_row(conn, args.pool))
    raw_rows = load_swap_rows(conn, pool.pool_address)
    if len(raw_rows) < 2:
        raise SystemExit("Need at least two swaps. Run base-v3-fetch-swaps first.")
    enriched = enrich_swaps(raw_rows, pool, args.base_symbol, args.quote_symbol)
    impact_rows = valid_impact_rows(enriched, pool)
    write_advanced_insights(
        args.output,
        pool,
        enriched,
        impact_rows,
        args.opposite_window_seconds,
        args.recovery_window_seconds,
        args.economic_min_size_usd,
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
