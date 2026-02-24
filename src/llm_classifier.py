"""
LLM-based item classifier using local Ollama.

Replaces keyword matching with an LLM that classifies flyer items against
staples and tier lists. Falls back to keyword matching if Ollama is unavailable.
"""

import json
import logging
import time
import requests
from datetime import date
from src.models import FlyerItem, RankedItem, UnitPrice, PipelineResults
from src.utils import compute_unit_price

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:32b"
BATCH_SIZE = 25
REQUEST_TIMEOUT = 180


class OllamaClassifier:
    def __init__(self, staples: list, tier_lists: dict,
                 ollama_url: str = DEFAULT_OLLAMA_URL,
                 model: str = DEFAULT_MODEL,
                 batch_size: int = BATCH_SIZE):
        self.staples = staples
        self.tier_lists = tier_lists
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size

        # Build lookup tables for code-side matching
        self.staple_categories = {s["name"]: s.get("category", "other") for s in staples}

        self.staple_keywords = {}
        for s in staples:
            self.staple_keywords[s["name"]] = {
                "keywords": [k.lower() for k in s.get("keywords", [])],
                "avoid": [a.lower() for a in s.get("avoid", [])],
            }

        self.tier_keywords = {}
        for category in ("meat", "carbs", "vegetables", "fruit"):
            for tier_group in tier_lists.get(category, []):
                for entry in tier_group.get("items", []):
                    self.tier_keywords[(category, entry["name"])] = {
                        "keywords": [k.lower() for k in entry.get("keywords", [])],
                        "avoid": [a.lower() for a in entry.get("avoid", [])],
                    }

        self.system_prompt = self._build_system_prompt()

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = resp.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] + ":" + m.get("name", "").split(":")[-1]
                          if ":" in m.get("name", "") else m.get("name", "")
                          for m in models]
            # Also check base name without tag
            base_names = [m.get("name", "").split(":")[0] for m in models]
            model_base = self.model.split(":")[0]
            return self.model in model_names or model_base in base_names or any(self.model in n for n in model_names)
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    def classify_all(self, all_store_items: dict) -> PipelineResults:
        """Classify all flyer items using the LLM."""
        # Flatten items
        all_items = []
        for store_key, items in all_store_items.items():
            all_items.extend(items)

        # Pre-compute unit prices
        unit_prices = {}
        for item in all_items:
            unit_prices[id(item)] = compute_unit_price(item)

        # Process in batches
        all_classifications = []
        total_batches = (len(all_items) + self.batch_size - 1) // self.batch_size

        for batch_num in range(total_batches):
            start = batch_num * self.batch_size
            end = min(start + self.batch_size, len(all_items))
            batch = all_items[start:end]

            logger.info(f"  LLM batch {batch_num + 1}/{total_batches}: "
                       f"classifying items {start}-{end - 1}")

            batch_results = self._classify_batch(batch, start)
            all_classifications.extend(batch_results.values())

            if batch_num < total_batches - 1:
                time.sleep(0.5)

        # Convert classifications to PipelineResults
        return self._build_results(all_items, all_classifications, unit_prices)

    def _classify_batch(self, batch: list, start_index: int) -> dict:
        """Send a batch of items to Ollama and parse the response."""
        user_prompt = self._build_user_prompt(batch)

        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "format": "json",
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_ctx": 16384,
                    },
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()
            content = result.get("message", {}).get("content", "{}")
            return self._parse_llm_response(content, batch, start_index)

        except requests.Timeout:
            logger.warning(f"Ollama timeout on batch starting at {start_index}")
            return {}
        except requests.RequestException as e:
            logger.warning(f"Ollama request failed: {e}")
            return {}
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse Ollama response: {e}")
            return {}

    def _parse_llm_response(self, content: str, batch: list, start_index: int) -> dict:
        """Parse the LLM's food identifications and match against staples/tiers."""
        results = {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON")
            return results

        items_list = data.get("items", [])
        if isinstance(data, list):
            items_list = data

        for entry in items_list:
            if not isinstance(entry, dict):
                continue

            idx = entry.get("idx")
            if idx is None or not isinstance(idx, int):
                continue
            if idx < 0 or idx >= len(batch):
                continue

            food_name = entry.get("food", "").strip()
            if not food_name:
                continue

            abs_idx = start_index + idx
            item_name = batch[idx].name

            # Match the LLM's food identification against our staples and tiers
            matches = self._match_food_to_lists(food_name, item_name)

            # Store all matches for this item
            for match in matches:
                key = (abs_idx, match["type"], match["match"])
                results[key] = {
                    "abs_idx": abs_idx,
                    "type": match["type"],
                    "match": match["match"],
                    "category": match["category"],
                    "tier": match.get("tier"),
                }

        return results

    def _match_food_to_lists(self, food_name: str, item_name: str) -> list:
        """Match the LLM's food identification against staples and tier lists.

        Uses bidirectional substring matching: checks if any keyword is in the
        food name OR if the food name is in any keyword.
        Avoid lists are checked against the original item name.

        Returns list of matches (an item can match multiple categories).
        """
        food_lower = food_name.lower()
        item_lower = item_name.lower()
        matches = []

        # Check staples
        for staple in self.staples:
            sname = staple["name"]
            lookup = self.staple_keywords.get(sname)
            if not lookup:
                continue

            # Check avoid list against original item name
            avoided = False
            for avoid_word in lookup["avoid"]:
                if avoid_word in item_lower:
                    avoided = True
                    break
            if avoided:
                continue

            # Bidirectional keyword match against LLM's food name
            if self._food_matches_keywords(food_lower, lookup["keywords"], sname):
                matches.append({
                    "type": "staple",
                    "match": sname,
                    "category": self.staple_categories.get(sname, "other"),
                })

        # Check tier items
        for category in ("meat", "carbs", "vegetables", "fruit"):
            for tier_group in self.tier_lists.get(category, []):
                tier_num = tier_group.get("tier", 1)
                for entry in tier_group.get("items", []):
                    ename = entry["name"]
                    lookup = self.tier_keywords.get((category, ename))
                    if not lookup:
                        continue

                    # Check avoid list against original item name
                    avoided = False
                    for avoid_word in lookup["avoid"]:
                        if avoid_word in item_lower:
                            avoided = True
                            break
                    if avoided:
                        continue

                    # Bidirectional keyword match against LLM's food name
                    if self._food_matches_keywords(food_lower, lookup["keywords"], ename):
                        matches.append({
                            "type": "tier",
                            "match": ename,
                            "category": category,
                            "tier": tier_num,
                        })

        return matches

    @staticmethod
    def _food_matches_keywords(food_lower: str, keywords: list, name: str) -> bool:
        """Check if a food name matches any keyword (bidirectional substring)."""
        # Check keywords
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in food_lower or food_lower in kw_lower:
                return True
        # Check the category/item name itself
        name_lower = name.lower()
        if name_lower in food_lower or food_lower in name_lower:
            return True
        return False

    def _build_results(self, all_items: list, classifications: list,
                       unit_prices: dict) -> PipelineResults:
        """Convert classifications into PipelineResults format."""
        staples_dict = {}
        tier_dict = {}

        # Initialize with all staple names (preserving config order)
        for staple in self.staples:
            staples_dict[staple["name"]] = []

        for category in ("meat", "carbs", "vegetables", "fruit"):
            tier_dict[category] = []

        # Track seen items for deduplication
        staple_seen = {}  # staple_name -> set of (item_name, merchant)
        tier_seen = {}    # category -> set of (item_name, merchant)

        for classification in classifications:
            abs_idx = classification["abs_idx"]
            if abs_idx >= len(all_items):
                continue

            item = all_items[abs_idx]
            up = unit_prices[id(item)]
            match_type = classification["type"]
            match_name = classification["match"]
            dedup_key = (item.name, item.merchant)

            if match_type == "staple":
                if match_name not in staple_seen:
                    staple_seen[match_name] = set()
                if dedup_key in staple_seen[match_name]:
                    continue
                staple_seen[match_name].add(dedup_key)

                if match_name not in staples_dict:
                    staples_dict[match_name] = []

                staples_dict[match_name].append(RankedItem(
                    item=item,
                    category=classification.get("category", "other"),
                    unit_price=up,
                    matched_staple=match_name,
                ))

            elif match_type == "tier":
                category = classification["category"]
                tier_num = classification["tier"]

                if category not in tier_seen:
                    tier_seen[category] = set()
                if dedup_key in tier_seen[category]:
                    continue
                tier_seen[category].add(dedup_key)

                # Check if this item also matched a staple
                staple_name = None
                for sname, seen_keys in staple_seen.items():
                    if dedup_key in seen_keys:
                        staple_name = sname
                        break

                if category not in tier_dict:
                    tier_dict[category] = []

                tier_dict[category].append(RankedItem(
                    item=item,
                    category=category,
                    unit_price=up,
                    matched_tier_item=match_name,
                    tier=tier_num,
                    matched_staple=staple_name,
                ))

        # Sort results
        for name in staples_dict:
            staples_dict[name].sort(key=lambda r: r.sort_key)
        for cat in tier_dict:
            tier_dict[cat].sort(key=lambda r: r.sort_key)

        staple_count = sum(len(v) for v in staples_dict.values())
        tier_count = sum(len(v) for v in tier_dict.values())
        logger.info(f"  LLM classified: {staple_count} staple hits, {tier_count} tier items")

        return PipelineResults(
            staples=staples_dict,
            tier_results=tier_dict,
            run_date=date.today(),
        )

    def _build_system_prompt(self) -> str:
        """Build a simple food-identification prompt."""
        return "\n".join([
            "You are a food identifier for grocery flyer items.",
            "For each item, identify what food it is using a short, common name.",
            "",
            "RULES:",
            "1. Only identify REAL FOOD items (fresh, raw, or basic grocery staples).",
            "2. SKIP all non-food: cleaning products, health/beauty, baby products,",
            "   pet food, electronics, appliances, clothing, diapers, medicine.",
            "3. SKIP processed/prepared foods: frozen meals, sauces, condiments, oils,",
            "   juices, dips, spreads, snack chips, candy, cookies, cereal, energy drinks.",
            "4. Use simple food names: \"pineapple\", \"chicken thighs\", \"salmon\",",
            "   \"greek yogurt\", \"eggs\", \"cheddar cheese\", \"broccoli\".",
            "5. Be PRECISE: 'Avocado Oil' is oil (skip). 'Garlic Bread' is bread (skip).",
            "   'Cadbury Mini Eggs' is candy (skip). 'Lemon Juice' is juice (skip).",
            "6. Double-check idx values match the line number of the item.",
            "",
            "RESPOND with JSON: {\"items\": [{\"idx\": 0, \"food\": \"pineapple\"}, "
            "{\"idx\": 3, \"food\": \"chicken thighs\"}]}",
            "",
            "Only include food items. Skip everything else.",
        ])

    def _build_user_prompt(self, batch: list) -> str:
        """Build the user prompt for a batch of items."""
        lines = ["Classify these flyer items:", ""]
        for i, item in enumerate(batch):
            price_str = f" ${item.price:.2f}" if item.price else ""
            lines.append(f"{i}. {item.name}{price_str} [{item.merchant}]")
        lines.append("")
        lines.append("Return JSON with classifications. Skip non-matching items.")
        return "\n".join(lines)
