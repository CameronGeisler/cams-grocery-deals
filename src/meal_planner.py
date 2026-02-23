"""
Template-based meal planner: suggest meals from what's actually on sale.

No AI costs. Predictable, fast, free.

Algorithm:
1. Sort meats by deal score (best deals first)
2. For each meat, find templates that use it
3. Check if enough veggies for those templates are on sale
4. Score meals by total savings
5. Pick top N meals ensuring protein variety
6. Suggest additional produce for variety
"""

import logging
from typing import Optional
from src.models import ScoredDeal, MealSuggestion, DealRating

logger = logging.getLogger(__name__)


class MealPlanner:
    def __init__(self, meal_templates: list, variety_config: dict = None):
        self.templates = meal_templates
        self.variety_min_fruits = 4
        self.variety_min_vegs = 5
        if variety_config:
            self.variety_min_fruits = variety_config.get("variety_minimum_fruits", 4)
            self.variety_min_vegs = variety_config.get("variety_minimum_vegetables", 5)

    def suggest_meals(self, scored_meats: list, scored_fruits: list,
                      scored_vegs: list, num_meals: int = 5) -> list:
        """
        Generate meal suggestions from sale items.

        Args:
            scored_meats: [ScoredDeal] for meat items
            scored_fruits: [ScoredDeal] for fruit items
            scored_vegs: [ScoredDeal] for vegetable items
            num_meals: how many meals to suggest

        Returns:
            List of MealSuggestion
        """
        # Sort meats by score (best deals first)
        meats_sorted = sorted(scored_meats, key=lambda d: d.score, reverse=True)

        # Build lookup of available produce
        available_vegs = self._build_produce_lookup(scored_vegs)
        available_fruits = self._build_produce_lookup(scored_fruits)

        meal_candidates = []

        for meat_deal in meats_sorted:
            if meat_deal.rating in (DealRating.NOT_A_DEAL,):
                continue

            # Find templates that use this protein
            matching_templates = self._find_matching_templates(
                meat_deal.matched_preference
            )

            for template in matching_templates:
                # Check if enough veggies are available
                matched_vegs = self._match_template_produce(
                    template.get("vegetables", []), available_vegs
                )
                matched_fruits = self._match_template_produce(
                    template.get("fruits", []), available_fruits
                )

                min_veggies = template.get("min_veggies", 2)
                if len(matched_vegs) < min_veggies:
                    continue  # Not enough veggies on sale for this meal

                # Calculate total savings
                total_savings = 0
                if meat_deal.discount_percent and meat_deal.price:
                    total_savings += meat_deal.price * (meat_deal.discount_percent / 100)
                for veg_deal in matched_vegs:
                    if veg_deal.discount_percent and veg_deal.price:
                        total_savings += veg_deal.price * (veg_deal.discount_percent / 100)

                meal = MealSuggestion(
                    name=template["name"],
                    protein=meat_deal,
                    vegetables=matched_vegs,
                    fruits=matched_fruits,
                    total_savings=round(total_savings, 2),
                    cooking_method=template.get("cooking", ""),
                )
                meal_candidates.append(meal)

        # Pick top meals ensuring protein variety
        selected = self._select_varied_meals(meal_candidates, num_meals)

        logger.info(f"Suggested {len(selected)} meals from {len(meal_candidates)} candidates")
        return selected

    def suggest_produce_variety(self, scored_fruits: list, scored_vegs: list,
                                already_used: set = None) -> dict:
        """
        Suggest additional fruits and vegetables for variety/snacking.

        Returns:
            {"fruits": [ScoredDeal], "vegetables": [ScoredDeal]}
        """
        already_used = already_used or set()

        def pick_variety(scored_items, minimum, item_type):
            # Sort by score, pick top unique items not already used
            sorted_items = sorted(scored_items, key=lambda d: d.score, reverse=True)
            selected = []
            seen_names = set()

            for deal in sorted_items:
                name = deal.matched_preference.lower()
                if name in seen_names or name in already_used:
                    continue
                if deal.rating == DealRating.NOT_A_DEAL:
                    continue
                seen_names.add(name)
                selected.append(deal)
                if len(selected) >= minimum:
                    break

            return selected

        return {
            "fruits": pick_variety(scored_fruits, self.variety_min_fruits, "fruit"),
            "vegetables": pick_variety(scored_vegs, self.variety_min_vegs, "vegetable"),
        }

    def _build_produce_lookup(self, scored_items: list) -> dict:
        """Build lookup of produce name -> best ScoredDeal."""
        lookup = {}
        for deal in scored_items:
            key = deal.matched_preference.lower()
            if key not in lookup or deal.score > lookup[key].score:
                lookup[key] = deal
        return lookup

    def _find_matching_templates(self, protein_name: str) -> list:
        """Find all meal templates that use this protein."""
        protein_lower = protein_name.lower()
        matches = []
        for template in self.templates:
            for protein in template.get("proteins", []):
                if protein.lower() in protein_lower or protein_lower in protein.lower():
                    matches.append(template)
                    break
        return matches

    def _match_template_produce(self, template_produce: list,
                                available: dict) -> list:
        """Check which template produce items are available on sale."""
        matched = []
        for prod_name in template_produce:
            prod_lower = prod_name.lower()
            # Direct match
            if prod_lower in available:
                matched.append(available[prod_lower])
                continue
            # Substring match
            for avail_name, deal in available.items():
                if prod_lower in avail_name or avail_name in prod_lower:
                    matched.append(deal)
                    break
        return matched

    def _select_varied_meals(self, candidates: list, num_meals: int) -> list:
        """
        Select meals ensuring variety in proteins and cooking methods.
        """
        if not candidates:
            return []

        # Score candidates: deal quality + variety bonus
        # Sort by total savings / deal score first
        candidates.sort(key=lambda m: m.protein.score + m.total_savings, reverse=True)

        selected = []
        used_proteins = set()
        used_cooking = set()

        # First pass: pick best deal for each unique protein
        for meal in candidates:
            protein_type = meal.protein.matched_preference.lower()
            if protein_type in used_proteins:
                continue
            selected.append(meal)
            used_proteins.add(protein_type)
            used_cooking.add(meal.cooking_method)
            if len(selected) >= num_meals:
                break

        # Second pass: fill remaining slots with best overall deals
        if len(selected) < num_meals:
            for meal in candidates:
                if meal in selected:
                    continue
                # Prefer different cooking methods for variety
                selected.append(meal)
                if len(selected) >= num_meals:
                    break

        return selected
