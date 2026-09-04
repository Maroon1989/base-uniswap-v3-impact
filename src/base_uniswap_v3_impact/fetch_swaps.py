from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .chain import ChainClient
from .config import DEFAULT_DB_PATH, load_runtime_config, require_rpc_url
from .db import connect, get_progress, insert_block_timestamp, insert_swaps, progress_id, save_progress, upsert_pool
from .uniswap_v3 import SWAP_EVENT_TOPIC, decode_swap_log


def build_parser() -> argparse.ArgumentParser:
    cfg = load_runtime_config()
    parser = argparse.ArgumentParser(description="Fetch Base Uniswap v3 Swap logs into SQLite.")
    parser.add_argument("--rpc-url", default=cfg.rpc_url)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--factory", default=cfg.factory)
    parser.add_argument("--pool", help="Pool address. If omitted, getPool(token-a, token-b, fee) is used.")
    parser.add_argument("--token-a", default=cfg.token_a)
    parser.add_argument("--token-b", default=cfg.token_b)
    parser.add_argument("--fee", type=int, default=cfg.pool_fee)
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    parser.add_argument("--days", type=int, default=cfg.lookback_days)
    parser.add_argument("--chunk-size", type=int, default=cfg.log_chunk_size)
    parser.add_argument("--min-chunk-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4, help="Parallel eth_getLogs requests. Keep modest on free RPC tiers.")
    parser.add_argument("--progress-every", type=int, default=1, help="Print one progress line every N chunks.")
    parser.add_argument("--max-swaps", type=int, help="Stop after reading this many logs from the selected range.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore saved fetch progress for this pool/range.")
    return parser


def resolve_range(client: ChainClient, from_block: int | None, to_block: int | None, days: int) -> tuple[int, int]:
    latest = client.latest_block_number()
    end = to_block if to_block is not None else latest
    if from_block is not None:
        return from_block, end
    end_ts = client.block_timestamp(end)
    target_ts = end_ts - days * 24 * 60 * 60
    start = client.find_block_at_or_after_timestamp(target_ts, high=end)
    return start, end


def main() -> None:
    args = build_parser().parse_args()
    client = ChainClient(require_rpc_url(args.rpc_url))

    pool_address = args.pool or client.get_pool_for_pair(args.factory, args.token_a, args.token_b, args.fee)
    if not pool_address:
        raise SystemExit("No Uniswap v3 pool found for that pair and fee tier.")
    pool = client.get_pool_info(pool_address)

    from_block, to_block = resolve_range(client, args.from_block, args.to_block, args.days)
    if from_block > to_block:
        raise SystemExit("from-block must be <= to-block")

    conn = connect(args.db)
    reason = f"{args.token_a}/{args.token_b} fee {pool.fee}, selected for Base Uniswap v3 swap impact analysis"
    upsert_pool(conn, pool, reason)

    pid = progress_id(pool.address, from_block, to_block)
    next_block = from_block
    if not args.no_resume:
        saved = get_progress(conn, pid)
        if saved and from_block <= saved <= to_block + 1:
            next_block = saved

    print(f"Pool: {pool.address}")
    print(f"Pair: {pool.token0.symbol}/{pool.token1.symbol}, fee={pool.fee}")
    print(f"Range: {from_block} -> {to_block}")
    print(f"Database: {args.db}")

    chunk_size = args.chunk_size
    workers = max(1, args.workers)
    total_seen = 0
    total_inserted = 0
    chunks_completed = 0
    start = next_block
    while start <= to_block:
        wave_start = start
        ranges: list[tuple[int, int]] = []
        for _ in range(workers):
            if start > to_block:
                break
            end = min(start + chunk_size - 1, to_block)
            ranges.append((start, end))
            start = end + 1

        try:
            if workers == 1:
                raw_by_range = {ranges[0]: client.logs(pool.address, SWAP_EVENT_TOPIC, ranges[0][0], ranges[0][1])}
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(client.logs, pool.address, SWAP_EVENT_TOPIC, begin, end): (begin, end)
                        for begin, end in ranges
                    }
                    raw_by_range = {futures[future]: future.result() for future in as_completed(futures)}
        except Exception as exc:
            start = wave_start
            if chunk_size > args.min_chunk_size:
                chunk_size = max(args.min_chunk_size, chunk_size // 2)
                print(f"RPC rejected/failed chunk near {wave_start}; reducing chunk size to {chunk_size}. Error: {exc}")
                continue
            if workers > 1:
                workers = max(1, workers // 2)
                print(f"RPC rejected/failed parallel wave near {wave_start}; reducing workers to {workers}. Error: {exc}")
                continue
            raise

        decoded_by_range = {range_: [decode_swap_log(log) for log in raw_by_range[range_]] for range_ in ranges}
        all_decoded = [swap for range_ in ranges for swap in decoded_by_range[range_]]
        timestamps = client.block_timestamps(swap.block_number for swap in all_decoded)
        for block_number, ts in timestamps.items():
            insert_block_timestamp(conn, block_number, ts)

        for begin, end in ranges:
            decoded = decoded_by_range[(begin, end)]
            inserted = insert_swaps(conn, decoded, timestamps)
            total_seen += len(decoded)
            total_inserted += inserted
            save_progress(conn, pid, pool.address, from_block, to_block, end + 1, chunk_size)

            chunks_completed += 1
            should_print = chunks_completed % max(1, args.progress_every) == 0 or end >= to_block
            if should_print:
                if decoded:
                    chunk_timestamps = [timestamps[swap.block_number] for swap in decoded]
                    first_ts = datetime.fromtimestamp(min(chunk_timestamps), tz=timezone.utc).isoformat()
                    last_ts = datetime.fromtimestamp(max(chunk_timestamps), tz=timezone.utc).isoformat()
                    ts_text = f", {first_ts} to {last_ts}"
                else:
                    ts_text = ""
                print(
                    f"{begin}-{end}: logs={len(decoded)}, inserted={inserted}, "
                    f"total_seen={total_seen}, total_inserted={total_inserted}{ts_text}"
                )

            if args.max_swaps and total_seen >= args.max_swaps:
                print(f"Reached --max-swaps={args.max_swaps}; stopping early.")
                print(f"Done. logs_seen={total_seen}, newly_inserted={total_inserted}")
                return

    print(f"Done. logs_seen={total_seen}, newly_inserted={total_inserted}")


if __name__ == "__main__":
    main()
