"""
OurGroceries integration: sync deal results to your shopping lists.

Items added by this system are tagged with [GP] in the note field,
so the script can clean up its own additions without touching
manually-added items.
"""

import asyncio
import logging
from typing import Optional
from src.models import PipelineResults, ScoredDeal, DealRating
from src.utils import format_price

logger = logging.getLogger(__name__)

SYSTEM_TAG = "[GP]"


class GrocerySync:
    def __init__(self, username: str, password: str, list_mapping: dict):
        self.username = username
        self.password = password
        self.list_mapping = list_mapping  # store_key -> OurGroceries list name
        self.og = None
        self.list_ids = {}

    async def connect(self):
        """Login to OurGroceries and resolve list names to IDs."""
        try:
            from ourgroceries import OurGroceries
        except ImportError:
            logger.error(
                "ourgroceries package not installed. "
                "Run: pip install ourgroceries"
            )
            return False

        try:
            self.og = OurGroceries(self.username, self.password)
            await self.og.login()
        except Exception as e:
            logger.error(f"Failed to login to OurGroceries: {e}")
            return False

        # Resolve list names to IDs
        try:
            lists_response = await self.og.get_my_lists()
            all_lists = lists_response.get("shoppingLists", [])

            for config_key, list_name in self.list_mapping.items():
                if not list_name:
                    continue
                for l in all_lists:
                    if l["name"].lower() == list_name.lower():
                        self.list_ids[config_key] = l["id"]
                        logger.info(f"  Mapped '{config_key}' -> '{l['name']}' (id: {l['id']})")
                        break
                else:
                    logger.warning(f"  List '{list_name}' not found in OurGroceries")

        except Exception as e:
            logger.error(f"Failed to get OurGroceries lists: {e}")
            return False

        logger.info(f"Connected to OurGroceries. Found {len(self.list_ids)} lists.")
        return True

    async def sync_all(self, results: PipelineResults):
        """Sync all results to OurGroceries lists."""
        if not self.og:
            logger.error("Not connected to OurGroceries")
            return

        # Sync store-specific lists
        for store_key, store_list in results.store_lists.items():
            list_name = self.list_mapping.get(store_key)
            if not list_name or store_key not in self.list_ids:
                continue

            list_id = self.list_ids[store_key]
            await self._sync_store_list(list_id, store_list)

        # Sync meal plan ingredients to "Need Soon" list
        if "need_soon" in self.list_ids and results.meal_suggestions:
            await self._sync_meal_plan(
                self.list_ids["need_soon"],
                results.meal_suggestions
            )

        # Sync exceptional deals to "Need Later" for awareness
        if "need_later" in self.list_ids and results.exceptional_deals:
            await self._sync_exceptional(
                self.list_ids["need_later"],
                results.exceptional_deals
            )

        logger.info("OurGroceries sync complete")

    async def _sync_store_list(self, list_id: str, store_list):
        """Update a store's OurGroceries list with this week's deals."""
        try:
            # Get current items
            current = await self.og.get_list_items(list_id)
            current_items = current.get("list", {}).get("items", [])

            # Remove items previously added by this system (have [GP] tag)
            for item in current_items:
                note = item.get("note", "") or ""
                if SYSTEM_TAG in note:
                    try:
                        await self.og.remove_item_from_list(list_id, item["id"])
                    except Exception as e:
                        logger.warning(f"Failed to remove old item: {e}")

            # Add new items
            for deal in store_list.items[:15]:  # Cap at 15 items per store
                note = self._format_deal_note(deal)
                try:
                    await self.og.add_item_to_list(
                        list_id,
                        deal.name,
                        note=note,
                    )
                except Exception as e:
                    logger.warning(f"Failed to add item '{deal.name}': {e}")

            # Add price match items
            for deal in store_list.price_match_items:
                note = self._format_price_match_note(deal)
                try:
                    await self.og.add_item_to_list(
                        list_id,
                        f"PM: {deal.name}",
                        note=note,
                    )
                except Exception as e:
                    logger.warning(f"Failed to add price match item '{deal.name}': {e}")

            total = len(store_list.items) + len(store_list.price_match_items)
            logger.info(f"  Synced {total} items to {store_list.store_display_name} list")

        except Exception as e:
            logger.error(f"Failed to sync {store_list.store_display_name}: {e}")

    async def _sync_meal_plan(self, list_id: str, meals: list):
        """Add meal plan header and ingredients to Need Soon list."""
        try:
            # Get current items and remove old [GP] items
            current = await self.og.get_list_items(list_id)
            current_items = current.get("list", {}).get("items", [])

            for item in current_items:
                note = item.get("note", "") or ""
                if SYSTEM_TAG in note:
                    try:
                        await self.og.remove_item_from_list(list_id, item["id"])
                    except Exception:
                        pass

            # Add meal plan items
            for i, meal in enumerate(meals, 1):
                # Add protein
                note = (
                    f"{SYSTEM_TAG} Meal {i}: {meal.name} | "
                    f"{format_price(meal.protein.price, meal.protein.item.unit)} "
                    f"at {meal.protein.store}"
                )
                await self.og.add_item_to_list(list_id, meal.protein.name, note=note)

                # Add vegetables (avoid duplicates)
                seen = set()
                for veg in meal.vegetables:
                    veg_key = veg.matched_preference.lower()
                    if veg_key not in seen:
                        seen.add(veg_key)
                        veg_note = (
                            f"{SYSTEM_TAG} For: {meal.name} | "
                            f"{format_price(veg.price, veg.item.unit)} at {veg.store}"
                        )
                        await self.og.add_item_to_list(
                            list_id, veg.matched_preference.title(), note=veg_note
                        )

            logger.info(f"  Synced {len(meals)} meal plans to Need Soon list")

        except Exception as e:
            logger.error(f"Failed to sync meal plan: {e}")

    async def _sync_exceptional(self, list_id: str, exceptional_deals: list):
        """Add exceptional deals to Need Later for awareness."""
        try:
            # Get current and remove old [GP] items
            current = await self.og.get_list_items(list_id)
            current_items = current.get("list", {}).get("items", [])

            for item in current_items:
                note = item.get("note", "") or ""
                if SYSTEM_TAG in note:
                    try:
                        await self.og.remove_item_from_list(list_id, item["id"])
                    except Exception:
                        pass

            # Add top exceptional deals
            for deal in exceptional_deals[:8]:
                note = self._format_deal_note(deal)
                await self.og.add_item_to_list(list_id, deal.name, note=note)

            logger.info(f"  Synced {min(len(exceptional_deals), 8)} exceptional deals to Need Later")

        except Exception as e:
            logger.error(f"Failed to sync exceptional deals: {e}")

    def _format_deal_note(self, deal: ScoredDeal) -> str:
        """Format a human-readable note for an OurGroceries item."""
        parts = [SYSTEM_TAG]
        if deal.price is not None:
            parts.append(format_price(deal.price, deal.item.unit))
        parts.append(f"at {deal.store}")
        if deal.discount_percent:
            parts.append(f"({deal.discount_percent:.0f}% off)")
        if deal.rating.label:
            parts.append(f"- {deal.rating.label}")
        return " ".join(parts)

    def _format_price_match_note(self, deal: ScoredDeal) -> str:
        """Format note for price-match items."""
        parts = [SYSTEM_TAG, "PRICE MATCH:"]
        if deal.price is not None:
            parts.append(format_price(deal.price, deal.item.unit))
        parts.append(f"from {deal.store} flyer")
        return " ".join(parts)


def run_sync(username: str, password: str, list_mapping: dict,
             results: PipelineResults):
    """Synchronous wrapper for async OurGroceries sync."""
    syncer = GrocerySync(username, password, list_mapping)

    async def _do_sync():
        connected = await syncer.connect()
        if connected:
            await syncer.sync_all(results)
        return connected

    return asyncio.run(_do_sync())
