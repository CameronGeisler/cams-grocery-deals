"""
SQLite-based historical price tracking.

Records every price seen each week. Over time this becomes the system's
secret weapon: it knows the REAL regular prices and seasonal patterns.
"""

import sqlite3
import os
import logging
from datetime import date, timedelta
from typing import Optional
from src.utils import clean_item_name

logger = logging.getLogger(__name__)


class PriceTracker:
    def __init__(self, db_path: str = "data/prices.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    item_name_normalized TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    price REAL NOT NULL,
                    unit TEXT DEFAULT 'each',
                    date_seen DATE NOT NULL,
                    flyer_valid_from DATE,
                    flyer_valid_to DATE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_normalized_name
                ON price_history (item_name_normalized)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_date_seen
                ON price_history (date_seen)
            """)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def record_prices(self, all_store_items: dict):
        """
        Record current week's prices into the database.

        Args:
            all_store_items: dict of store_key -> [FlyerItem]
        """
        today = date.today()
        count = 0

        with self._connect() as conn:
            for store_key, items in all_store_items.items():
                for item in items:
                    if item.price is None:
                        continue

                    normalized = clean_item_name(item.name)
                    if not normalized:
                        continue

                    # Avoid duplicate entries for same item/store/date
                    existing = conn.execute(
                        """SELECT id FROM price_history
                           WHERE item_name_normalized = ? AND merchant = ? AND date_seen = ?""",
                        (normalized, item.merchant, today.isoformat())
                    ).fetchone()

                    if existing:
                        continue

                    conn.execute(
                        """INSERT INTO price_history
                           (item_name, item_name_normalized, merchant, price, unit,
                            date_seen, flyer_valid_from, flyer_valid_to)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.name,
                            normalized,
                            item.merchant,
                            item.price,
                            item.unit,
                            today.isoformat(),
                            item.valid_from.isoformat() if item.valid_from else None,
                            item.valid_to.isoformat() if item.valid_to else None,
                        )
                    )
                    count += 1

        logger.info(f"Recorded {count} prices to history database")

    def get_lowest_price(self, item_name_normalized: str,
                         months: int = 3) -> Optional[float]:
        """Get the lowest price seen in the last N months."""
        cutoff = (date.today() - timedelta(days=months * 30)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT MIN(price) FROM price_history
                   WHERE item_name_normalized = ? AND date_seen >= ?""",
                (item_name_normalized, cutoff)
            ).fetchone()
            return row[0] if row and row[0] is not None else None

    def get_average_price(self, item_name_normalized: str,
                          months: int = 3) -> Optional[float]:
        """Get the average price seen in the last N months."""
        cutoff = (date.today() - timedelta(days=months * 30)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT AVG(price) FROM price_history
                   WHERE item_name_normalized = ? AND date_seen >= ?""",
                (item_name_normalized, cutoff)
            ).fetchone()
            return round(row[0], 2) if row and row[0] is not None else None

    def is_historical_low(self, item_name_normalized: str, price: float) -> bool:
        """Is this price at or below the all-time lowest we've recorded?"""
        lowest = self.get_lowest_price(item_name_normalized, months=12)
        if lowest is None:
            return False
        return price <= lowest

    def get_price_history(self, item_name_normalized: str,
                          months: int = 6) -> list:
        """
        Get full price history for an item.
        Returns list of (date_seen, merchant, price) tuples.
        """
        cutoff = (date.today() - timedelta(days=months * 30)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date_seen, merchant, price FROM price_history
                   WHERE item_name_normalized = ? AND date_seen >= ?
                   ORDER BY date_seen DESC""",
                (item_name_normalized, cutoff)
            ).fetchall()
            return rows

    def get_stats(self) -> dict:
        """Get summary stats about the price database."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
            unique_items = conn.execute(
                "SELECT COUNT(DISTINCT item_name_normalized) FROM price_history"
            ).fetchone()[0]
            date_range = conn.execute(
                "SELECT MIN(date_seen), MAX(date_seen) FROM price_history"
            ).fetchone()

            return {
                "total_records": total,
                "unique_items": unique_items,
                "earliest_date": date_range[0] if date_range else None,
                "latest_date": date_range[1] if date_range else None,
            }
