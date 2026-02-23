"""
Price match optimizer: find the best items to price-match at your primary store.

Strategy:
1. Look at all deals from competitor stores
2. For items also available at primary store (or on your list anyway)
3. Calculate savings from price-matching each item
4. Pick the top N (default 4) items by savings amount
"""

import logging
from typing import Optional
from src.models import ScoredDeal, DealRating

logger = logging.getLogger(__name__)


class PriceMatchOptimizer:
    def __init__(self, stores_config: dict, primary_store: str = "superstore",
                 match_limit: int = 4):
        self.stores = stores_config
        self.primary = primary_store
        self.match_limit = match_limit

        # Build set of stores that support price matching at primary
        primary_conf = stores_config.get(primary_store, {})
        self.primary_supports_match = primary_conf.get("supports_price_match", False)

    def optimize(self, scored_deals_by_store: dict) -> list:
        """
        Find the top N items to price-match at the primary store.

        Args:
            scored_deals_by_store: dict of store_key -> [ScoredDeal]

        Returns:
            List of (ScoredDeal, savings_amount, original_store_name) for top N items
        """
        if not self.primary_supports_match:
            logger.info("Primary store doesn't support price matching")
            return []

        # Collect all deals from non-primary stores that are good deals
        candidates = []

        for store_key, deals in scored_deals_by_store.items():
            if store_key == self.primary:
                continue

            store_conf = self.stores.get(store_key, {})
            store_name = store_conf.get("display_name", store_key)

            for deal in deals:
                if deal.price is None:
                    continue
                if deal.rating in (DealRating.NOT_A_DEAL, DealRating.OKAY):
                    continue  # Only price-match genuinely good deals

                # Estimate savings: compare to reference price (what you'd pay at primary)
                savings = self._estimate_savings(deal)
                if savings > 0:
                    candidates.append((deal, savings, store_name))

        # Sort by savings descending
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Take top N
        picks = candidates[:self.match_limit]

        if picks:
            total_savings = sum(s for _, s, _ in picks)
            logger.info(
                f"Price match picks: {len(picks)} items, "
                f"~${total_savings:.2f} estimated savings"
            )
            for deal, savings, store in picks:
                logger.info(f"  {deal.name}: ${deal.price:.2f} from {store} (save ~${savings:.2f})")

        return picks

    def _estimate_savings(self, deal: ScoredDeal) -> float:
        """
        Estimate how much you'd save by price-matching this item.
        Uses reference price as proxy for what you'd pay at primary store.
        """
        if deal.price is None:
            return 0.0

        if deal.reference_price and deal.reference_price > deal.price:
            return round(deal.reference_price - deal.price, 2)

        # If no reference price, use discount percentage estimate
        if deal.discount_percent and deal.discount_percent > 0:
            estimated_regular = deal.price / (1 - deal.discount_percent / 100)
            return round(estimated_regular - deal.price, 2)

        return 0.0
