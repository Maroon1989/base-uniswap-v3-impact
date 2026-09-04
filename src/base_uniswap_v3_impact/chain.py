from __future__ import annotations

from time import sleep
from typing import Any, Callable, Iterable, TypeVar

import requests

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
        self.rpc_url = rpc_url
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

    def block_timestamps(self, block_numbers: Iterable[int]) -> dict[int, int]:
        unique_blocks = sorted(set(int(block_number) for block_number in block_numbers))
        missing = [block_number for block_number in unique_blocks if block_number not in self._block_ts_cache]
        if missing:
            payload = [
                {
                    "jsonrpc": "2.0",
                    "id": block_number,
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block_number), False],
                }
                for block_number in missing
            ]
            try:
                response = requests.post(self.rpc_url, json=payload, timeout=30)
                response.raise_for_status()
                results = response.json()
                by_id = {int(item["id"]): item for item in results}
                for block_number in missing:
                    item = by_id.get(block_number)
                    if not item or item.get("error"):
                        raise RuntimeError(f"Batch block timestamp request failed for block {block_number}: {item}")
                    self._block_ts_cache[block_number] = int(item["result"]["timestamp"], 16)
            except Exception:
                for block_number in missing:
                    self.block_timestamp(block_number)
        return {block_number: self._block_ts_cache[block_number] for block_number in unique_blocks}

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

    def rpc_request(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = requests.post(self.rpc_url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data["result"]

    def logs(self, pool_address: str, topic0: str, from_block: int, to_block: int) -> list[Any]:
        params = {
            "address": self.checksum(pool_address),
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [topic0],
        }
        return list(retry_call(lambda: self.rpc_request("eth_getLogs", [params])))

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
