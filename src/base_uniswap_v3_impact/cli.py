from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal, getcontext

from dotenv import load_dotenv
from web3 import Web3

from .abis import ERC20_ABI, FACTORY_ABI, POOL_ABI, QUOTER_V2_ABI

getcontext().prec = 80

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEFAULT_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
DEFAULT_QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
BASE_TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "CBETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
}


@dataclass(frozen=True)
class Token:
    address: str
    symbol: str
    decimals: int


def checksum(w3: Web3, value: str) -> str:
    address = BASE_TOKENS.get(value.upper(), value)
    if not w3.is_address(address):
        raise ValueError(f"Invalid token address or known symbol: {value}")
    return w3.to_checksum_address(address)


def load_token(w3: Web3, address: str) -> Token:
    contract = w3.eth.contract(address=address, abi=ERC20_ABI)
    symbol = contract.functions.symbol().call()
    decimals = contract.functions.decimals().call()
    return Token(address=address, symbol=symbol, decimals=decimals)


def parse_units(amount: str, decimals: int) -> int:
    scaled = Decimal(amount) * (Decimal(10) ** decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Amount {amount} has more precision than token decimals {decimals}")
    return int(scaled)


def format_units(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** decimals)


def pool_mid_price(
    sqrt_price_x96: int,
    token_in: Token,
    token_out: Token,
    pool_token0: str,
    reverse: bool,
) -> Decimal:
    raw_token1_per_token0 = (Decimal(sqrt_price_x96) / (Decimal(2) ** 96)) ** 2
    human_token1_per_token0 = raw_token1_per_token0 * (
        Decimal(10) ** (token_in.decimals - token_out.decimals)
        if token_in.address.lower() == pool_token0.lower()
        else Decimal(10) ** (token_out.decimals - token_in.decimals)
    )

    if token_in.address.lower() == pool_token0.lower():
        price = human_token1_per_token0
    else:
        price = Decimal(1) / human_token1_per_token0

    return Decimal(1) / price if reverse else price


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quote a Base Uniswap v3 exact-input swap and estimate price impact."
    )
    parser.add_argument("--rpc-url", default=os.getenv("BASE_RPC_URL"))
    parser.add_argument("--factory", default=os.getenv("UNISWAP_V3_FACTORY", DEFAULT_FACTORY))
    parser.add_argument("--quoter", default=os.getenv("UNISWAP_V3_QUOTER_V2", DEFAULT_QUOTER_V2))
    parser.add_argument("--token-in", required=True, help="Token address, or known symbol like WETH/USDC")
    parser.add_argument("--token-out", required=True, help="Token address, or known symbol like WETH/USDC")
    parser.add_argument("--fee", type=int, required=True, help="Pool fee tier, e.g. 500, 3000, 10000")
    parser.add_argument("--amount-in", required=True, help="Human token amount, e.g. 1.25")
    parser.add_argument("--reverse-price", action="store_true", help="Display price as input/output instead.")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()

    if not args.rpc_url:
        raise SystemExit("BASE_RPC_URL is missing. Create .env from .env.example and fill it in.")
    if not args.factory or not args.quoter:
        raise SystemExit("Uniswap factory/quoter address is missing.")

    w3 = Web3(Web3.HTTPProvider(args.rpc_url))
    if not w3.is_connected():
        raise SystemExit("Could not connect to Base RPC.")

    factory_address = checksum(w3, args.factory)
    quoter_address = checksum(w3, args.quoter)
    token_in_address = checksum(w3, args.token_in)
    token_out_address = checksum(w3, args.token_out)

    token_in = load_token(w3, token_in_address)
    token_out = load_token(w3, token_out_address)
    amount_in_raw = parse_units(args.amount_in, token_in.decimals)

    factory = w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
    pool_address = factory.functions.getPool(token_in.address, token_out.address, args.fee).call()
    if pool_address == ZERO_ADDRESS:
        raise SystemExit("No Uniswap v3 pool found for that token pair and fee tier.")

    pool = w3.eth.contract(address=pool_address, abi=POOL_ABI)
    pool_token0 = pool.functions.token0().call()
    sqrt_price_x96 = pool.functions.slot0().call()[0]
    mid_price = pool_mid_price(sqrt_price_x96, token_in, token_out, pool_token0, False)

    quoter = w3.eth.contract(address=quoter_address, abi=QUOTER_V2_ABI)
    quote = quoter.functions.quoteExactInputSingle(
        (token_in.address, token_out.address, amount_in_raw, args.fee, 0)
    ).call()

    amount_out_raw, sqrt_price_after, ticks_crossed, gas_estimate = quote
    amount_in = format_units(amount_in_raw, token_in.decimals)
    amount_out = format_units(amount_out_raw, token_out.decimals)
    execution_price = amount_out / amount_in
    impact = (Decimal(1) - (execution_price / mid_price)) * Decimal(100)
    display_mid_price = Decimal(1) / mid_price if args.reverse_price else mid_price
    display_execution_price = Decimal(1) / execution_price if args.reverse_price else execution_price
    price_label = (
        f"{token_in.symbol}/{token_out.symbol}"
        if args.reverse_price
        else f"{token_out.symbol}/{token_in.symbol}"
    )

    print(f"Pool: {pool_address}")
    print(f"Input: {amount_in:f} {token_in.symbol}")
    print(f"Quoted output: {amount_out:f} {token_out.symbol}")
    print(f"Mid price: {display_mid_price:f} {price_label}")
    print(f"Execution price: {display_execution_price:f} {price_label}")
    print(f"Price impact: {impact:.6f}%")
    print(f"Initialized ticks crossed: {ticks_crossed}")
    print(f"Quoter gas estimate: {gas_estimate}")
    print(f"sqrtPriceX96 after: {sqrt_price_after}")


if __name__ == "__main__":
    main()

