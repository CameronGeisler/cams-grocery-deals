"""
Item matcher: matches flyer items against weekly staples and tier lists.

Two match passes:
1. STAPLES: Items you buy every week -> find cheapest across stores
2. TIER LISTS: Ranked food categories (meat, carbs, vegetables, fruit)
"""

import logging
from datetime import date
from src.models import FlyerItem, RankedItem, PipelineResults
from src.utils import clean_item_name, keyword_match, negative_keyword_match, fuzzy_match, compute_unit_price

logger = logging.getLogger(__name__)


class ItemMatcher:
    def __init__(self, preferences: dict, tier_lists: dict,
                 matching_mode: str = "auto", ollama_settings: dict = None):
        self.staples = preferences.get("staples", [])
        self.tier_lists = tier_lists
        self.matching_mode = matching_mode  # "auto", "llm", "keyword"
        self.ollama_settings = ollama_settings or {}

        # Pre-build tier index: (category, tier_num) -> list of item entries
        self.tier_index = {}
        for category in ("meat", "carbs", "vegetables", "fruit"):
            tiers = tier_lists.get(category, [])
            for tier_group in tiers:
                tier_num = tier_group.get("tier", 1)
                self.tier_index[(category, tier_num)] = tier_group.get("items", [])

    def match_all(self, all_store_items: dict) -> PipelineResults:
        """
        Run matching against all store items. Uses LLM or keyword mode.

        Args:
            all_store_items: dict of store_key -> [FlyerItem]

        Returns:
            PipelineResults with staples and tier_results populated
        """
        use_llm = False

        if self.matching_mode in ("llm", "auto"):
            from src.llm_classifier import OllamaClassifier
            llm_staples = [s for s in self.staples if "meal_vegetables" not in s]
            classifier = OllamaClassifier(
                staples=llm_staples,
                tier_lists=self.tier_lists,
                ollama_url=self.ollama_settings.get("url", "http://localhost:11434"),
                model=self.ollama_settings.get("model", "qwen2.5:14b"),
                batch_size=self.ollama_settings.get("batch_size", 100),
            )
            if classifier.is_available():
                use_llm = True
                logger.info(f"Using Ollama LLM matching (model: {classifier.model})")
            elif self.matching_mode == "llm":
                logger.error("Ollama not available but matching_mode='llm'. Falling back to keywords.")
            else:
                logger.info("Ollama not available. Using keyword matching.")

        if use_llm:
            results = classifier.classify_all(all_store_items)
        else:
            results = self._keyword_match_all(all_store_items)

        self._derive_meal_vegetables(results)

        # Log summary
        staple_count = sum(len(v) for v in results.staples.values())
        tier_count = sum(len(v) for v in results.tier_results.values())
        mode_label = "LLM" if use_llm else "keyword"
        logger.info(f"Matched ({mode_label}): {staple_count} staple hits, {tier_count} tier items")

        return results

    def _keyword_match_all(self, all_store_items: dict) -> PipelineResults:
        """Original keyword-based matching logic."""
        # Flatten all items
        all_items = []
        for store_key, items in all_store_items.items():
            all_items.extend(items)

        # Pre-compute unit prices once per item
        unit_prices = {}
        for item in all_items:
            unit_prices[id(item)] = compute_unit_price(item)

        staples_dict = self._match_staples(all_items, unit_prices)
        tier_dict = self._match_tiers(all_items, unit_prices, staples_dict)

        return PipelineResults(
            staples=staples_dict,
            tier_results=tier_dict,
            run_date=date.today(),
        )

    def _match_staples(self, items: list, unit_prices: dict) -> dict:
        """
        For each staple, find all matching flyer items.
        Returns dict of staple_name -> [RankedItem] sorted by unit price ascending.
        """
        results = {}

        for staple in self.staples:
            name = staple["name"]
            keywords = staple.get("keywords", [name.lower()])
            avoid = staple.get("avoid", [])
            category = staple.get("category", "other")
            matches = []
            seen = set()

            for item in items:
                item_lower = item.name.lower()
                cleaned = clean_item_name(item.name)

                # Check avoid keywords first
                if avoid and negative_keyword_match(avoid, item.name):
                    continue

                # Keyword substring match
                matched = keyword_match(keywords, item_lower) or keyword_match(keywords, cleaned)

                # Fuzzy fallback
                if not matched:
                    for kw in keywords:
                        if fuzzy_match(kw, cleaned, threshold=0.82) > 0:
                            matched = kw
                            break

                if matched:
                    # Deduplicate by (item name, store)
                    dedup_key = (item.name, item.merchant)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    up = unit_prices[id(item)]
                    matches.append(RankedItem(
                        item=item,
                        category=category,
                        unit_price=up,
                        matched_staple=name,
                    ))

            # Sort by unit price ascending (cheapest first, None-price last)
            matches.sort(key=lambda r: r.sort_key)
            results[name] = matches

        return results

    def _match_tiers(self, items: list, unit_prices: dict, staples_dict: dict) -> dict:
        """
        For each food category, find matching items ranked by tier then unit price.
        Returns dict of category -> [RankedItem] sorted by (tier, unit_price).
        """
        # Build a set of staple item names for tagging
        staple_item_names = set()
        for staple_name, ranked_items in staples_dict.items():
            for ri in ranked_items:
                staple_item_names.add((ri.item.name, ri.item.merchant, staple_name))

        results = {}

        for category in ("meat", "carbs", "vegetables", "fruit"):
            matches = []
            seen = set()

            for item in items:
                item_lower = item.name.lower()
                cleaned = clean_item_name(item.name)

                # Try tiers in order: 1 first, then 2, then 3
                matched_tier = None
                matched_entry_name = None

                for tier_num in (1, 2, 3, 4):
                    tier_items = self.tier_index.get((category, tier_num), [])
                    for entry in tier_items:
                        entry_keywords = entry.get("keywords", [])
                        entry_avoid = entry.get("avoid", [])

                        # Check avoid first
                        if entry_avoid and negative_keyword_match(entry_avoid, item.name):
                            continue

                        # Keyword match
                        hit = keyword_match(entry_keywords, item_lower) or keyword_match(entry_keywords, cleaned)

                        # Fuzzy fallback
                        if not hit:
                            for kw in entry_keywords:
                                if fuzzy_match(kw, cleaned, threshold=0.82) > 0:
                                    hit = kw
                                    break

                        if hit:
                            matched_tier = tier_num
                            matched_entry_name = entry["name"]
                            break

                    if matched_tier is not None:
                        break

                if matched_tier is not None:
                    # Deduplicate by (item name, store)
                    dedup_key = (item.name, item.merchant)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    up = unit_prices[id(item)]

                    # Check if this item is also a staple
                    staple_name = None
                    for (sname, smerchant, sstaple) in staple_item_names:
                        if sname == item.name and smerchant == item.merchant:
                            staple_name = sstaple
                            break

                    matches.append(RankedItem(
                        item=item,
                        category=category,
                        unit_price=up,
                        matched_tier_item=matched_entry_name,
                        tier=matched_tier,
                        matched_staple=staple_name,
                    ))

            # Sort by tier then unit price
            matches.sort(key=lambda r: r.sort_key)
            results[category] = matches

        return results

    def _derive_meal_vegetables(self, results: PipelineResults) -> None:
        """Populate 'Vegetables for Meals' staple from the vegetables tier results."""
        meal_staple = next((s for s in self.staples if s.get("name") == "Vegetables for Meals"), None)
        if not meal_staple:
            return
        meal_veg_set = {v.lower() for v in meal_staple.get("meal_vegetables", [])}
        filtered = [
            ri for ri in results.tier_results.get("vegetables", [])
            if ri.matched_tier_item and ri.matched_tier_item.lower() in meal_veg_set
        ]
        results.staples["Vegetables for Meals"] = filtered
