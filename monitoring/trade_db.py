"""
Trade Database — SQLite persistence for simulation/paper trades.
Auto-creates data/trades.db on first use.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from loguru import logger

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "trades.db"


def _conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            direction   TEXT    NOT NULL,
            size_usd    REAL    NOT NULL,
            price       REAL    NOT NULL,
            signal_score REAL   NOT NULL,
            signal_confidence REAL NOT NULL,
            outcome     TEXT    NOT NULL DEFAULT 'PENDING',
            market_slug TEXT    DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    logger.debug(f"Trade DB ready at {DB_PATH}")


def save_trade(
    timestamp: datetime,
    direction: str,
    size_usd: float,
    price: float,
    signal_score: float,
    signal_confidence: float,
    outcome: str = "PENDING",
    market_slug: str = "",
):
    conn = _conn()
    conn.execute(
        """INSERT INTO paper_trades
               (timestamp, direction, size_usd, price, signal_score,
                signal_confidence, outcome, market_slug)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            timestamp.isoformat(),
            direction,
            size_usd,
            price,
            signal_score,
            signal_confidence,
            outcome,
            market_slug,
        ),
    )
    conn.commit()
    conn.close()


def get_trades(
    limit: int = 100,
    direction: Optional[str] = None,
    outcome: Optional[str] = None,
) -> list[dict]:
    conn = _conn()
    parts = ["SELECT * FROM paper_trades"]
    params: list = []
    conds: list[str] = []
    if direction:
        conds.append("direction = ?")
        params.append(direction)
    if outcome:
        conds.append("outcome = ?")
        params.append(outcome)
    if conds:
        parts.append(" WHERE " + " AND ".join(conds))
    parts.append(" ORDER BY id DESC LIMIT ?")
    params.append(limit)
    rows = conn.execute("".join(parts), params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = _conn()
    row = conn.execute("""
        SELECT
            COUNT(*)                                           AS total_trades,
            SUM(CASE WHEN outcome = 'WIN'   THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN outcome = 'LOSS'  THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN outcome = 'PENDING' THEN 1 ELSE 0 END) AS pending,
            ROUND(AVG(CASE WHEN outcome = 'WIN' THEN 1.0
                           WHEN outcome = 'LOSS' THEN 0.0
                           ELSE NULL END), 4)                  AS win_rate,
            ROUND(SUM(size_usd), 2)                            AS total_volume,
            ROUND(AVG(price), 4)                                AS avg_price
        FROM paper_trades
    """).fetchone()
    conn.close()
    return dict(row)


init_db()
