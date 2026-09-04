from __future__ import annotations

from time import sleep
from typing import Any, Callable, TypeVar

from web3 import Web3

from .abis import ERC20_ABI, FACTORY_ABI, POOL_ABI
from .config import KNOWN_TOKENS, ZERO_ADDRESS
from .models import PoolInfo, Token

T = TypeVar("T")


def _safe_error_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "unknown")
        text = getattr(response, "text", "")
        text = " ".join(str(text).split())[:500]
        return f"{type(exc).__name__}: HTTP {status}. {text}"
    return f"{type(exc).__name__}: {exc}"


def retry_call(fn: Callable[[], T], attempts: int = 4, base_delay: float = 0.75) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # web3 providers expose several backend-specific errors.
            last_error = exc
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) == 400:
                break
            if attempt == attempts - 1:
                break
            sleep(base_delay * (2**attempt))
    assert last_error is not None
    raise RuntimeError(_safe_error_message(last_error)) from None


class ChainClient:
    def __init__(self, rpc_url: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        if not self.w3.is_connected():
            raise SystemExit("Could not connect to Base RPC.")
        self._token_cache: dict[str, Token] = {}
        self._block_ts_cache: dict[int, int] = {}

    def checksum(self, value: str) -> str:
        address = KNOWN_TOKENS.get(value.upper(), value)
        if not self.w3.is_address(address):
            raise ValueError(f"Invalid address or known token symbol: {value}")
        return self.w3.to_checksum_address(address)

    def load_token(self, address_or_symbol: str) -> Token:
        address = self.checksum(address_or_symbol)
        key = address.lower()
        if key in self._token_cache:
            return self._token_cache[key]
        contract = self.w3.eth.contract(address=address, abi=ERC20_ABI)
        symbol = retry_call(lambda: contract.functions.symbol().call())
        decimals = retry_call(lambda: contract.functions.decimals().call())
        token = Token(address=address, symbol=str(symbol), decimals=int(decimals))
        self._token_cache[key] = token
        return token

    def get_pool_for_pair(self, factory: str, token_a: str, token_b: str, fee: int) -> str | None:
        factory_address = self.checksum(factory)
        token_a_address = self.checksum(token_a)
        token_b_address = self.checksum(token_b)
        contract = self.w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
        pool = retry_call(lambda: contract.functions.getPool(token_a_address, token_b_address, fee).call())
        if pool == ZERO_ADDRESS:
            return None
        return self.w3.to_checksum_address(pool)

    def get_pool_info(self, pool_address: str) -> PoolInfo:
        address = self.checksum(pool_address)
        contract = self.w3.eth.contract(address=address, abi=POOL_ABI)
        token0_address = retry_call(lambda: contract.functions.token0().call())
        token1_address = retry_call(lambda: contract.functions.token1().call())
        fee = int(retry_call(lambda: contract.functions.fee().call()))
        liquidity = int(retry_call(lambda: contract.functions.liquidity().call()))
        slot0 = retry_call(lambda: contract.functions.slot0().call())
        return PoolInfo(
            address=address,
            token0=self.load_token(token0_address),
            token1=self.load_token(token1_address),
            fee=fee,
            liquidity=liquidity,
            sqrt_price_x96=int(slot0[0]),
            tick=int(slot0[1]),
        )

    def latest_block_number(self) -> int:
        return int(retry_call(lambda: self.w3.eth.block_number))

    def block_timestamp(self, block_number: int) -> int:
        if block_number in self._block_ts_cache:
            return self._block_ts_cache[block_number]
        block = retry_call(lambda: self.w3.eth.get_block(block_number))
        timestamp = int(block["timestamp"])
        self._block_ts_cache[block_number] = timestamp
        return timestamp

    def find_block_at_or_after_timestamp(self, target_timestamp: int, low: int = 0, high: int | None = None) -> int:
        if high is None:
            high = self.latest_block_number()
        while low < high:
            mid = (low + high) // 2
            if self.block_timestamp(mid) < target_timestamp:
                low = mid + 1
            else:
                high = mid
        return low

    def logs(self, pool_address: str, topic0: str, from_block: int, to_block: int) -> list[Any]:
        params = {
            "address": self.checksum(pool_address),
            "fromBlock": from_block,
            "toBlock": to_block,
            "topics": [topic0],
        }
        return list(retry_call(lambda: self.w3.eth.get_logs(params)))

    def count_logs(
        self,
        pool_address: str,
        topic0: str,
        from_block: int,
        to_block: int,
        chunk_size: int,
        min_chunk_size: int = 10,
    ) -> int:
        count = 0
        start = from_block
        current_chunk_size = chunk_size
        while start <= to_block:
            end = min(start + current_chunk_size - 1, to_block)
            try:
                count += len(self.logs(pool_address, topic0, start, end))
                start = end + 1
            except Exception:
                if current_chunk_size <= min_chunk_size:
                    raise
                current_chunk_size = max(min_chunk_size, current_chunk_size // 2)
        return count
