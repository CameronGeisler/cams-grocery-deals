"""
Deal scoring engine: determines if a price is actually GOOD, not just "on sale."

Score 0-100:
  0-30:  Not noteworthy (small discount or no reference price)
  31-60: GOOD deal (worth buying)
  61-80: GREAT deal (definitely buy)
  81-100: EXCEPTIONAL (stock up if possible)

Scoring weights:
  50% - Discount vs reference/threshold price
  20% - Historical price comparison
  15% - Quality keywords (grass-fed, AAA, etc.)
  10% - Loyalty points value
  5%  - Config "max good price" comparison
"""

import logging
from typing import Optional
from src.models import FlyerItem, ScoredDeal, DealRating
from src.utils import (
    parse_price, clean_item_name, keyword_match,
    calculate_discount_percent, format_price,
)

logger = logging.getLogger(__name__)


class DealScorer:
    def __init__(self, price_thresholds: dict, stores_config: dict,
                 price_tracker=None, repeat_list: dict = None):
        self.thresholds = price_thresholds
        self.stores = stores_config
        self.tracker = price_tracker
        self.repeat_list = repeat_list or {}
        self._build_threshold_index()

    def _build_threshold_index(self):
        """Pre-build a lookup from keywords to threshold entries."""
        self._threshold_lookup = {}
        for section in ["meats", "produce"]:
            entries = self.thresholds.get(section, {})
            for key, entry in entries.items():
                for kw in entry.get("keywords", []):
                    self._threshold_lookup[kw.lower()] = entry

    def score_deal(self, flyer_item: FlyerItem, matched_category: str,
                   matched_preference: str) -> ScoredDeal:
        """Score a single deal. Returns a ScoredDeal object."""
        price = flyer_item.price
        unit = flyer_item.unit
        name_lower = flyer_item.name.lower()
        cleaned = clean_item_name(flyer_item.name)

        # Find the best matching threshold entry
        threshold_entry = self._find_threshold(matched_preference, name_lower)

        reference_price = None
        discount_pct = None
        notes_parts = []

        # --- Score Component 1: Discount vs reference price (0-50) ---
        discount_score = 0
        if threshold_entry and price is not None:
            reference_price = threshold_entry.get("regular_price")
            good_price = threshold_entry.get("good_price")
            great_price = threshold_entry.get("great_price")

            if reference_price and price < reference_price:
                discount_pct = calculate_discount_percent(price, reference_price)

                if great_price and price <= great_price:
                    discount_score = 48 + min(5, (great_price - price) * 2)
                    notes_parts.append(f"{discount_pct:.0f}% off regular")
                elif good_price and price <= good_price:
                    # Scale between 30-48 based on how close to great_price
                    range_size = good_price - great_price if great_price else good_price * 0.3
                    if range_size > 0:
                        position = (good_price - price) / range_size
                        discount_score = 30 + position * 18
                    else:
                        discount_score = 35
                    notes_parts.append(f"{discount_pct:.0f}% off")
                else:
                    # Below regular but above "good" threshold
                    discount_score = max(5, min(28, discount_pct * 0.6))
            elif reference_price:
                discount_score = 0  # At or above regular price

        elif price is not None and matched_category == "repeat_list":
            # For repeat list items, check against max_good_price
            max_price = self._get_repeat_max_price(matched_preference)
            if max_price and price <= max_price:
                discount_score = 25
                notes_parts.append(f"At or below target price ${max_price:.2f}")
            elif max_price and price <= max_price * 1.1:
                discount_score = 10
                notes_parts.append(f"Close to target price ${max_price:.2f}")

        # --- Score Component 2: Historical price (0-20) ---
        history_score = 0
        if self.tracker and price is not None:
            history_score = self._score_historical(cleaned, flyer_item.merchant, price)
            if history_score >= 15:
                notes_parts.append("Near historical low!")

        # --- Score Component 3: Quality keywords (0-15) ---
        quality_score = self._score_quality(flyer_item.name)
        if quality_score >= 10:
            notes_parts.append("Premium quality")

        # --- Score Component 4: Loyalty points (0-10) ---
        loyalty_score = self._score_loyalty(flyer_item)
        if loyalty_score >= 5:
            notes_parts.append("PC Optimum points")

        # --- Score Component 5: Config target price (0-5) ---
        target_score = 0
        if matched_category == "repeat_list" and price is not None:
            max_price = self._get_repeat_max_price(matched_preference)
            if max_price and price < max_price * 0.8:
                target_score = 5
            elif max_price and price <= max_price:
                target_score = 3

        # --- Total Score ---
        total_score = min(100, discount_score + history_score + quality_score +
                          loyalty_score + target_score)

        rating = self._assign_rating(total_score)
        notes = " | ".join(notes_parts) if notes_parts else ""

        return ScoredDeal(
            item=flyer_item,
            matched_category=matched_category,
            matched_preference=matched_preference,
            rating=rating,
            discount_percent=discount_pct,
            reference_price=reference_price,
            score=round(total_score, 1),
            notes=notes,
        )

    def _find_threshold(self, matched_preference: str, name_lower: str) -> Optional[dict]:
        """Find the best matching price threshold entry."""
        # Direct lookup by matched preference keyword
        pref_lower = matched_preference.lower()
        if pref_lower in self._threshold_lookup:
            return self._threshold_lookup[pref_lower]

        # Search all threshold keywords against the item name
        for kw, entry in self._threshold_lookup.items():
            if kw in name_lower:
                return entry

        return None

    def _get_repeat_max_price(self, item_name: str) -> Optional[float]:
        """Get the max_good_price for a repeat list item."""
        for category, items in self.repeat_list.items():
            for item in items:
                if item.get("name", "").lower() == item_name.lower():
                    return item.get("max_good_price")
        return None

    def _score_historical(self, item_name: str, merchant: str, price: float) -> float:
        """Score based on historical price data. 0-20 scale."""
        if not self.tracker:
            return 0

        try:
            lowest = self.tracker.get_lowest_price(item_name)
            avg = self.tracker.get_average_price(item_name)
        except Exception:
            return 0

        if lowest is None or avg is None:
            return 0

        score = 0
        # At or below historical low
        if price <= lowest:
            score = 20
        # Below average
        elif price < avg:
            pct_below_avg = (avg - price) / avg
            score = min(15, pct_below_avg * 30)

        return score

    def _score_quality(self, item_name: str) -> float:
        """Bonus points for quality indicators. 0-15 scale."""
        quality_keywords = {
            "grass-fed": 12, "grass fed": 12,
            "angus": 10,
            "AAA": 10, "aaa": 10,
            "prime": 8,
            "organic": 8,
            "free range": 7, "free run": 7,
            "wild caught": 8, "wild-caught": 8,
            "natural": 4,
            "fresh": 3,
        }

        name_lower = item_name.lower()
        max_score = 0
        for kw, points in quality_keywords.items():
            if kw.lower() in name_lower:
                max_score = max(max_score, points)

        return min(15, max_score)

    def _score_loyalty(self, flyer_item: FlyerItem) -> float:
        """Factor in loyalty point value. 0-10 scale."""
        # Check if the store has a loyalty program
        for store_key, store_conf in self.stores.items():
            merchant_names = [m.lower() for m in store_conf.get("flipp_merchant_names", [])]
            if any(m in flyer_item.merchant.lower() for m in merchant_names):
                if store_conf.get("loyalty_program"):
                    earn_rate = store_conf.get("loyalty_earn_rate", 0)
                    # Base loyalty score
                    score = 3 if earn_rate > 0 else 0

                    # Check for bonus points indicators in the item name/text
                    bonus_keywords = ["bonus points", "20x", "extra points",
                                      "points event", "bonus"]
                    item_text = f"{flyer_item.name} {flyer_item.price_text}".lower()
                    if any(kw in item_text for kw in bonus_keywords):
                        score = 10

                    return score
        return 0

    def _assign_rating(self, total_score: float) -> DealRating:
        """Convert numeric score to DealRating."""
        if total_score >= 70:
            return DealRating.EXCEPTIONAL
        if total_score >= 50:
            return DealRating.GREAT
        if total_score >= 30:
            return DealRating.GOOD
        if total_score >= 15:
            return DealRating.OKAY
        return DealRating.NOT_A_DEAL
