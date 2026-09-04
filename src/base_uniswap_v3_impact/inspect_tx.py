from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

from web3 import Web3

from .abis import ERC20_ABI, POOL_ABI
from .config import load_runtime_config, require_rpc_url
from .uniswap_v3 import SWAP_EVENT_TOPIC, decimal_amount, decode_swap_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Uniswap v3 Swap logs inside one or more Base transactions.")
    parser.add_argument("tx", nargs="*", help="Transaction hash to inspect. Can be passed multiple times.")
    parser.add_argument("--output", help="Optional markdown output path.")
    return parser


def topic_hex(topic: object) -> str:
    value = topic.hex() if hasattr(topic, "hex") else str(topic)
    return "0x" + value.removeprefix("0x")


def short(tx_hash: str) -> str:
    return f"{tx_hash[:10]}...{tx_hash[-8:]}"


def row(cells: list[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def main() -> None:
    args = build_parser().parse_args()
    if not args.tx:
        raise SystemExit("Pass at least one transaction hash.")

    config = load_runtime_config()
    rpc_url = require_rpc_url(config.rpc_url)
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise SystemExit("Could not connect to Base RPC.")

    @lru_cache(maxsize=None)
    def token_meta(address: str) -> tuple[str, int]:
        contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)
        try:
            symbol = contract.functions.symbol().call()
        except Exception:
            symbol = "?"
        try:
            decimals = int(contract.functions.decimals().call())
        except Exception:
            decimals = 18
        return symbol, decimals

    @lru_cache(maxsize=None)
    def pool_meta(address: str) -> tuple[str, int, str, int, int]:
        contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=POOL_ABI)
        token0 = contract.functions.token0().call()
        token1 = contract.functions.token1().call()
        fee = int(contract.functions.fee().call())
        symbol0, decimals0 = token_meta(token0)
        symbol1, decimals1 = token_meta(token1)
        return symbol0, decimals0, symbol1, decimals1, fee

    lines = ["# Transaction Receipt Swap Inspection", ""]
    for tx_hash in args.tx:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        lines.extend(
            [
                f"## {short(tx_hash)}",
                "",
                f"- Block: {receipt.blockNumber}",
                f"- Status: {receipt.status}",
                f"- Gas used: {receipt.gasUsed:,}",
                "",
                row(["Log", "Pool", "Pair", "Fee", "Direction hint", "Amount0", "Amount1"]),
                row(["---:", "---", "---", "---:", "---", "---:", "---:"]),
            ]
        )
        swap_count = 0
        for log in receipt.logs:
            if not log["topics"] or topic_hex(log["topics"][0]).lower() != SWAP_EVENT_TOPIC.lower():
                continue
            try:
                swap = decode_swap_log(log)
                symbol0, decimals0, symbol1, decimals1, fee = pool_meta(log["address"])
            except Exception as exc:
                lines.append(row([log.get("logIndex", "?"), log["address"], "decode failed", "", str(exc), "", ""]))
                continue
            amount0 = decimal_amount(swap.amount0, decimals0)
            amount1 = decimal_amount(swap.amount1, decimals1)
            direction = ""
            if symbol0 == "WETH" and symbol1 == "USDC":
                direction = "sell_WETH" if amount0 > 0 else "buy_WETH"
            elif symbol1 == "WETH" and symbol0 == "USDC":
                direction = "sell_WETH" if amount1 > 0 else "buy_WETH"
            swap_count += 1
            lines.append(
                row(
                    [
                        swap.log_index,
                        log["address"],
                        f"{symbol0}/{symbol1}",
                        fee,
                        direction,
                        f"{amount0:,.8f}",
                        f"{amount1:,.8f}",
                    ]
                )
            )
        if swap_count == 0:
            lines.append(row(["n/a", "n/a", "No v3 Swap logs found", "", "", "", ""]))
        lines.append("")

    text = "\n".join(lines)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        print(f"Wrote {output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
