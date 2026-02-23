"""
Flipp API client for fetching flyer deal data.

Two approaches:
1. Bulk: Get all flyers for target stores, then all items per flyer (primary)
2. Search: Search for specific items across all stores (supplementary)

No API key required. Rate-limited to be respectful.
"""

import requests
import random
import time
import json
import os
import logging
from datetime import datetime, date
from typing import Optional
from src.models import FlyerItem

logger = logging.getLogger(__name__)

# Flipp API endpoints
FLYERS_URL = "https://flyers-ng.flippback.com/api/flipp/data"
FLYER_ITEMS_URL = "https://flyers-ng.flippback.com/api/flipp/flyers/{}/flyer_items"
SEARCH_URL = "https://backflipp.wishabi.com/flipp/items/search"
ITEM_DETAIL_URL = "https://backflipp.wishabi.com/flipp/items/{}"


class FlippClient:
    def __init__(self, postal_code: str, locale: str = "en", cache_dir: str = "data"):
        self.postal_code = postal_code.replace(" ", "")
        self.locale = locale
        self.session_id = ''.join([str(random.randint(0, 9)) for _ in range(16)])
        self.cache_dir = cache_dir
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        self._request_count = 0

    def _rate_limit(self):
        """Pause between requests to be respectful."""
        self._request_count += 1
        if self._request_count > 1:
            time.sleep(0.4)

    def _get_json(self, url: str, params: dict = None) -> Optional[dict]:
        """Make a GET request and return JSON, or None on failure."""
        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Request failed: {url} - {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode failed: {url} - {e}")
            return None

    def get_current_flyers(self) -> list:
        """Fetch all current flyers for the postal code."""
        params = {
            "locale": self.locale,
            "postal_code": self.postal_code,
            "sid": self.session_id,
        }
        data = self._get_json(FLYERS_URL, params)
        if not data:
            logger.error("Failed to fetch flyers list")
            return []

        flyers = []
        today = date.today()

        # The response can be a list or have a 'flyers' key
        flyer_list = data if isinstance(data, list) else data.get("flyers", [])

        for flyer in flyer_list:
            # Only include current/active flyers
            try:
                valid_from = self._parse_date(flyer.get("valid_from", ""))
                valid_to = self._parse_date(flyer.get("valid_to", ""))
                if valid_to and valid_to < today:
                    continue
            except (ValueError, TypeError):
                pass

            flyers.append(flyer)

        logger.info(f"Found {len(flyers)} current flyers")
        return flyers

    def get_store_flyers(self, merchant_names: list, all_flyers: list = None) -> list:
        """Filter flyers to only those from specified merchants."""
        if all_flyers is None:
            all_flyers = self.get_current_flyers()

        matched = []
        merchant_names_lower = [m.lower() for m in merchant_names]

        for flyer in all_flyers:
            flyer_merchant = flyer.get("merchant", "").lower()
            # Use substring matching - Flipp might say "Real Canadian Superstore"
            for target in merchant_names_lower:
                if target in flyer_merchant or flyer_merchant in target:
                    matched.append(flyer)
                    break

        logger.info(f"Matched {len(matched)} flyers for merchants: {merchant_names}")
        return matched

    def get_flyer_items(self, flyer_id) -> list:
        """Get all items from a specific flyer. Returns list of FlyerItem."""
        url = FLYER_ITEMS_URL.format(flyer_id)
        data = self._get_json(url)
        if not data:
            logger.warning(f"Failed to fetch items for flyer {flyer_id}")
            return []

        items = []
        item_list = data if isinstance(data, list) else data.get("items", [])

        for raw in item_list:
            item = self._parse_flyer_item(raw)
            if item:
                items.append(item)

        logger.info(f"Fetched {len(items)} items from flyer {flyer_id}")
        return items

    def search_items(self, query: str) -> list:
        """Search for specific items across all stores. Returns list of FlyerItem."""
        params = {
            "locale": f"{self.locale}-ca",
            "postal_code": self.postal_code,
            "q": query,
        }
        data = self._get_json(SEARCH_URL, params)
        if not data:
            return []

        items = []
        raw_items = data.get("items", [])

        for raw in raw_items:
            item = self._parse_search_item(raw)
            if item:
                items.append(item)

        logger.info(f"Search '{query}' returned {len(items)} items")
        return items

    def get_all_deals(self, stores_config: dict) -> dict:
        """
        Main method: fetch ALL current deals from all configured stores.

        Args:
            stores_config: dict from stores.yaml, keyed by store_key

        Returns:
            dict of store_key -> [FlyerItem]
        """
        logger.info("Fetching all flyers...")
        all_flyers = self.get_current_flyers()

        results = {}
        for store_key, store_conf in stores_config.items():
            merchant_names = store_conf.get("flipp_merchant_names", [])
            if not merchant_names:
                continue

            store_flyers = self.get_store_flyers(merchant_names, all_flyers)
            store_items = []

            for flyer in store_flyers:
                flyer_id = flyer.get("id")
                if flyer_id:
                    items = self.get_flyer_items(flyer_id)
                    # Tag each item with the store's display name
                    for item in items:
                        if not item.merchant:
                            item.merchant = store_conf.get("display_name", store_key)
                    store_items.extend(items)

            results[store_key] = store_items
            logger.info(f"  {store_conf.get('display_name', store_key)}: {len(store_items)} items")

        total = sum(len(v) for v in results.values())
        logger.info(f"Total: {total} items from {len(results)} stores")

        # Cache results
        self._cache_results(results)

        return results

    def _parse_flyer_item(self, raw: dict) -> Optional[FlyerItem]:
        """Parse a raw flyer item dict into a FlyerItem."""
        name = raw.get("name", "").strip()
        if not name:
            name = raw.get("description", "").strip()
        if not name:
            return None

        # Price can be in various fields
        price_text = ""
        price = None
        unit = "each"

        # Try direct "price" field first (most common in flyer_items API)
        if raw.get("price") is not None:
            try:
                price = float(raw["price"])
                price_text = f"${price:.2f}"
            except (ValueError, TypeError):
                pass

        # Try "current_price" field
        if price is None and raw.get("current_price") is not None:
            try:
                price = float(raw["current_price"])
                price_text = f"${price:.2f}"
            except (ValueError, TypeError):
                pass

        # Try "sale_price" field
        if price is None and raw.get("sale_price") is not None:
            try:
                price = float(raw["sale_price"])
                price_text = f"${price:.2f}"
            except (ValueError, TypeError):
                pass

        # Build a composite price text from available fields
        pre = raw.get("pre_price_text", "").strip()
        main_price = raw.get("price_text", "").strip()
        post = raw.get("post_price_text", "").strip()
        if main_price:
            price_text = f"{pre} {main_price} {post}".strip()

        # If we still don't have a price, try parsing from text fields
        if price is None and price_text:
            from src.utils import parse_price
            price, unit, _ = parse_price(price_text)

        return FlyerItem(
            name=name,
            price=price,
            price_text=price_text,
            unit=unit,
            merchant=raw.get("merchant", ""),
            flyer_id=str(raw.get("flyer_id", "")),
            valid_from=self._parse_date(raw.get("valid_from")),
            valid_to=self._parse_date(raw.get("valid_to")),
            category=raw.get("category", ""),
            raw_data=raw,
        )

    def _parse_search_item(self, raw: dict) -> Optional[FlyerItem]:
        """Parse a search result item into a FlyerItem."""
        # Search results have a slightly different structure
        name = raw.get("name", "").strip() or raw.get("description", "").strip()
        if not name:
            return None

        price_text = raw.get("price_text", "") or raw.get("sale_story", "") or ""
        price = None
        unit = "each"

        # Try multiple price fields
        for field in ("price", "current_price", "sale_price"):
            if raw.get(field) is not None:
                try:
                    price = float(raw[field])
                    if not price_text:
                        price_text = f"${price:.2f}"
                    break
                except (ValueError, TypeError):
                    pass

        if price is None and price_text:
            from src.utils import parse_price
            price, unit, _ = parse_price(price_text)

        merchant = raw.get("merchant", "") or raw.get("merchant_name", "") or ""

        return FlyerItem(
            name=name,
            price=price,
            price_text=price_text,
            unit=unit,
            merchant=merchant,
            flyer_id=str(raw.get("flyer_id", "")),
            valid_from=self._parse_date(raw.get("valid_from")),
            valid_to=self._parse_date(raw.get("valid_to")),
            category=raw.get("category", ""),
            raw_data=raw,
        )

    def _parse_date(self, date_str) -> Optional[date]:
        """Parse various date formats from Flipp."""
        if not date_str:
            return None
        if isinstance(date_str, date):
            return date_str

        date_str = str(date_str).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                     "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(date_str[:19], fmt[:min(len(fmt), 19)]).date()
            except ValueError:
                continue
        # Try just the date part
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    def _cache_results(self, results: dict):
        """Save raw results to cache file for debugging."""
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_path = os.path.join(self.cache_dir, "last_run.json")
        try:
            serializable = {}
            for store_key, items in results.items():
                serializable[store_key] = [
                    {
                        "name": item.name,
                        "price": item.price,
                        "price_text": item.price_text,
                        "unit": item.unit,
                        "merchant": item.merchant,
                    }
                    for item in items
                ]
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")
