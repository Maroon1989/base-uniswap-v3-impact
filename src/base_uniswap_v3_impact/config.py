from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_CHAIN_ID = 8453
BASE_CHAIN_NAME = "Base"
DEFAULT_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
DEFAULT_FEE_TIERS = (100, 500, 3000, 10000)
DEFAULT_DB_PATH = Path("data/swaps.db")
DEFAULT_CHART_DIR = Path("output/charts")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

KNOWN_TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "CBETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
}


@dataclass(frozen=True)
class RuntimeConfig:
    rpc_url: str
    factory: str
    token_a: str
    token_b: str
    pool_fee: int
    lookback_days: int
    log_chunk_size: int


def load_runtime_config() -> RuntimeConfig:
    load_dotenv()
    rpc_url = os.getenv("BASE_RPC_URL", "").strip()
    return RuntimeConfig(
        rpc_url=rpc_url,
        factory=os.getenv("UNISWAP_V3_FACTORY", DEFAULT_FACTORY).strip(),
        token_a=os.getenv("TOKEN_A", "WETH").strip(),
        token_b=os.getenv("TOKEN_B", "USDC").strip(),
        pool_fee=int(os.getenv("POOL_FEE", "500")),
        lookback_days=int(os.getenv("LOOKBACK_DAYS", "7")),
        log_chunk_size=int(os.getenv("LOG_CHUNK_SIZE", "1000")),
    )


def require_rpc_url(value: str | None) -> str:
    if value:
        return value
    raise SystemExit("BASE_RPC_URL is missing. Fill it in .env or pass --rpc-url.")
