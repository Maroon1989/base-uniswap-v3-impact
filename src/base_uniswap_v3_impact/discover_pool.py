from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from .chain import ChainClient
from .config import DEFAULT_FEE_TIERS, load_runtime_config, require_rpc_url
from .uniswap_v3 import SWAP_EVENT_TOPIC, price_quote_per_base


@dataclass(frozen=True)
class PoolCandidate:
    fee: int
    pool_address: str | None
    token0: str | None
    token1: str | None
    current_liquidity: str | None
    current_price_usdc_per_weth: str | None
    recent_swap_count: int


def parse_fees(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    cfg = load_runtime_config()
    parser = argparse.ArgumentParser(description="Compare Base Uniswap v3 WETH/USDC fee-tier pools.")
    parser.add_argument("--rpc-url", default=cfg.rpc_url)
    parser.add_argument("--factory", default=cfg.factory)
    parser.add_argument("--token-a", default=cfg.token_a)
    parser.add_argument("--token-b", default=cfg.token_b)
    parser.add_argument("--fees", default=",".join(str(fee) for fee in DEFAULT_FEE_TIERS))
    parser.add_argument("--recent-blocks", type=int, default=43_200, help="Roughly one day on Base at 2s blocks.")
    parser.add_argument("--chunk-size", type=int, default=cfg.log_chunk_size)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a table.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    client = ChainClient(require_rpc_url(args.rpc_url))
    latest = client.latest_block_number()
    from_block = max(0, latest - args.recent_blocks + 1)
    candidates: list[PoolCandidate] = []

    for fee in parse_fees(args.fees):
        pool_address = client.get_pool_for_pair(args.factory, args.token_a, args.token_b, fee)
        if not pool_address:
            candidates.append(PoolCandidate(fee, None, None, None, None, None, 0))
            continue
        pool = client.get_pool_info(pool_address)
        try:
            price = price_quote_per_base(pool.sqrt_price_x96, pool.token0, pool.token1)
            price_text = f"{price:.8f}"
        except Exception:
            price_text = None
        count = client.count_logs(pool.address, SWAP_EVENT_TOPIC, from_block, latest, args.chunk_size)
        candidates.append(
            PoolCandidate(
                fee=fee,
                pool_address=pool.address,
                token0=f"{pool.token0.symbol} ({pool.token0.address})",
                token1=f"{pool.token1.symbol} ({pool.token1.address})",
                current_liquidity=str(pool.liquidity),
                current_price_usdc_per_weth=price_text,
                recent_swap_count=count,
            )
        )

    candidates.sort(key=lambda item: item.recent_swap_count, reverse=True)
    if args.json:
        print(json.dumps([asdict(candidate) for candidate in candidates], indent=2))
        return

    print(f"Compared pools from block {from_block} to {latest}")
    print("fee	swaps	pool	token0	token1	price_usdc_per_weth	liquidity")
    for c in candidates:
        print(
            f"{c.fee}	{c.recent_swap_count}	{c.pool_address or '-'}	"
            f"{c.token0 or '-'}	{c.token1 or '-'}	{c.current_price_usdc_per_weth or '-'}	{c.current_liquidity or '-'}"
        )


if __name__ == "__main__":
    main()
