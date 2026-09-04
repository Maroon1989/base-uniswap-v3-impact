from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .models import PoolInfo
from .uniswap_v3 import DecodedSwap

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS pools (
  pool_address TEXT PRIMARY KEY,
  chain TEXT NOT NULL,
  protocol TEXT NOT NULL,
  token0_address TEXT NOT NULL,
  token0_symbol TEXT NOT NULL,
  token0_decimals INTEGER NOT NULL,
  token1_address TEXT NOT NULL,
  token1_symbol TEXT NOT NULL,
  token1_decimals INTEGER NOT NULL,
  fee INTEGER NOT NULL,
  initial_liquidity TEXT NOT NULL,
  initial_sqrt_price_x96 TEXT NOT NULL,
  initial_tick INTEGER NOT NULL,
  selected_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS block_timestamps (
  block_number INTEGER PRIMARY KEY,
  block_timestamp INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS swaps (
  pool_address TEXT NOT NULL,
  block_number INTEGER NOT NULL,
  block_timestamp INTEGER NOT NULL,
  tx_hash TEXT NOT NULL,
  tx_index INTEGER NOT NULL,
  log_index INTEGER NOT NULL,
  sender TEXT NOT NULL,
  recipient TEXT NOT NULL,
  amount0_raw TEXT NOT NULL,
  amount1_raw TEXT NOT NULL,
  sqrt_price_x96 TEXT NOT NULL,
  liquidity TEXT NOT NULL,
  tick INTEGER NOT NULL,
  PRIMARY KEY (tx_hash, log_index),
  FOREIGN KEY (pool_address) REFERENCES pools(pool_address)
);

CREATE INDEX IF NOT EXISTS idx_swaps_pool_block_log ON swaps(pool_address, block_number, tx_index, log_index);
CREATE INDEX IF NOT EXISTS idx_swaps_block_timestamp ON swaps(block_timestamp);

CREATE TABLE IF NOT EXISTS fetch_progress (
  progress_id TEXT PRIMARY KEY,
  pool_address TEXT NOT NULL,
  from_block INTEGER NOT NULL,
  to_block INTEGER NOT NULL,
  next_block INTEGER NOT NULL,
  chunk_size INTEGER NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_pool(conn: sqlite3.Connection, pool: PoolInfo, selected_reason: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pools (
          pool_address, chain, protocol,
          token0_address, token0_symbol, token0_decimals,
          token1_address, token1_symbol, token1_decimals,
          fee, initial_liquidity, initial_sqrt_price_x96, initial_tick, selected_reason
        ) VALUES (?, 'Base', 'Uniswap v3', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pool_address) DO UPDATE SET
          token0_address=excluded.token0_address,
          token0_symbol=excluded.token0_symbol,
          token0_decimals=excluded.token0_decimals,
          token1_address=excluded.token1_address,
          token1_symbol=excluded.token1_symbol,
          token1_decimals=excluded.token1_decimals,
          fee=excluded.fee,
          initial_liquidity=excluded.initial_liquidity,
          initial_sqrt_price_x96=excluded.initial_sqrt_price_x96,
          initial_tick=excluded.initial_tick,
          selected_reason=excluded.selected_reason
        """,
        (
            pool.address,
            pool.token0.address,
            pool.token0.symbol,
            pool.token0.decimals,
            pool.token1.address,
            pool.token1.symbol,
            pool.token1.decimals,
            pool.fee,
            str(pool.liquidity),
            str(pool.sqrt_price_x96),
            pool.tick,
            selected_reason,
        ),
    )
    conn.commit()


def insert_block_timestamp(conn: sqlite3.Connection, block_number: int, block_timestamp: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO block_timestamps(block_number, block_timestamp) VALUES (?, ?)",
        (block_number, block_timestamp),
    )


def insert_swaps(conn: sqlite3.Connection, swaps: Iterable[DecodedSwap], timestamps: dict[int, int]) -> int:
    inserted = 0
    for swap in swaps:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO swaps (
              pool_address, block_number, block_timestamp, tx_hash, tx_index, log_index,
              sender, recipient, amount0_raw, amount1_raw, sqrt_price_x96, liquidity, tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                swap.pool_address,
                swap.block_number,
                timestamps[swap.block_number],
                swap.transaction_hash,
                swap.transaction_index,
                swap.log_index,
                swap.sender,
                swap.recipient,
                str(swap.amount0),
                str(swap.amount1),
                str(swap.sqrt_price_x96),
                str(swap.liquidity),
                swap.tick,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def progress_id(pool_address: str, from_block: int, to_block: int) -> str:
    return f"{pool_address.lower()}:{from_block}:{to_block}"


def get_progress(conn: sqlite3.Connection, pid: str) -> int | None:
    row = conn.execute("SELECT next_block FROM fetch_progress WHERE progress_id = ?", (pid,)).fetchone()
    return int(row["next_block"]) if row else None


def save_progress(
    conn: sqlite3.Connection,
    pid: str,
    pool_address: str,
    from_block: int,
    to_block: int,
    next_block: int,
    chunk_size: int,
) -> None:
    conn.execute(
        """
        INSERT INTO fetch_progress(progress_id, pool_address, from_block, to_block, next_block, chunk_size, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(progress_id) DO UPDATE SET
          next_block=excluded.next_block,
          chunk_size=excluded.chunk_size,
          updated_at=CURRENT_TIMESTAMP
        """,
        (pid, pool_address, from_block, to_block, next_block, chunk_size),
    )
    conn.commit()


def load_pool_row(conn: sqlite3.Connection, pool_address: str | None = None) -> sqlite3.Row:
    if pool_address:
        row = conn.execute("SELECT * FROM pools WHERE lower(pool_address)=lower(?)", (pool_address,)).fetchone()
        if not row:
            raise SystemExit(f"Pool {pool_address} is not in the database. Run fetch first.")
        return row
    rows = conn.execute("SELECT * FROM pools ORDER BY created_at DESC").fetchall()
    if not rows:
        raise SystemExit("No pool metadata found. Run base-v3-fetch-swaps first.")
    if len(rows) > 1:
        raise SystemExit("Multiple pools found. Pass --pool to base-v3-analyze.")
    return rows[0]
