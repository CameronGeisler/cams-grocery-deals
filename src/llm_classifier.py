"""
LLM-based item classifier using local Ollama.

Replaces keyword matching with an LLM that classifies flyer items against
staples and tier lists. Falls back to keyword matching if Ollama is unavailable.
"""

import json
import logging
import time
import requests
from typing import Optional
from datetime import date
from src.models import FlyerItem, RankedItem, UnitPrice, PipelineResults
from src.utils import compute_unit_price

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:14b"
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

        # Build lookup tables for validation
        self.staple_names = {s["name"] for s in staples}
        self.staple_categories = {s["name"]: s.get("category", "other") for s in staples}
        self.tier_items = {}  # (category, tier_num) -> set of item names
        self.all_tier_names = {}  # category -> set of all item names
        for category in ("meat", "carbs", "vegetables", "fruit"):
            self.all_tier_names[category] = set()
            for tier_group in tier_lists.get(category, []):
                tier_num = tier_group.get("tier", 1)
                names = {entry["name"] for entry in tier_group.get("items", [])}
                self.tier_items[(category, tier_num)] = names
                self.all_tier_names[category].update(names)

        # Build keyword+avoid lookups for post-validation
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
        all_classifications = {}
        total_batches = (len(all_items) + self.batch_size - 1) // self.batch_size

        for batch_num in range(total_batches):
            start = batch_num * self.batch_size
            end = min(start + self.batch_size, len(all_items))
            batch = all_items[start:end]

            logger.info(f"  LLM batch {batch_num + 1}/{total_batches}: "
                       f"classifying items {start}-{end - 1}")

            batch_results = self._classify_batch(batch, start)
            all_classifications.update(batch_results)

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
        """Parse the JSON response from the LLM."""
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

            abs_idx = start_index + idx
            match_type = entry.get("type", "none")

            if match_type == "none":
                continue

            match_name = entry.get("match", "").strip()
            category = entry.get("category", "").strip().lower()
            tier = entry.get("tier")

            # Validate the classification
            item_name = batch[idx].name

            if match_type == "staple":
                validated_name = self._validate_staple_name(match_name)
                if not validated_name:
                    continue
                # Keyword cross-check: does the flyer item relate to this staple?
                if not self._validate_classification(item_name, "staple", validated_name, ""):
                    continue
                results[abs_idx] = {
                    "type": "staple",
                    "match": validated_name,
                    "category": self.staple_categories.get(validated_name, "other"),
                    "tier": None,
                }

            elif match_type == "tier":
                if category not in self.all_tier_names:
                    continue
                validated_name = self._validate_tier_name(match_name, category)
                if not validated_name:
                    continue
                # Keyword cross-check: does the flyer item relate to this tier item?
                if not self._validate_classification(item_name, "tier", validated_name, category):
                    continue
                # Find which tier this item belongs to
                validated_tier = None
                for tier_num in (1, 2, 3):
                    if validated_name in self.tier_items.get((category, tier_num), set()):
                        validated_tier = tier_num
                        break
                if validated_tier is None:
                    continue

                results[abs_idx] = {
                    "type": "tier",
                    "match": validated_name,
                    "category": category,
                    "tier": validated_tier,
                }

        return results

    def _validate_staple_name(self, name: str) -> Optional[str]:
        """Find the matching staple name, handling LLM spelling variants."""
        if name in self.staple_names:
            return name
        # Case-insensitive match
        name_lower = name.lower()
        for sn in self.staple_names:
            if sn.lower() == name_lower:
                return sn
        # Substring match
        for sn in self.staple_names:
            if name_lower in sn.lower() or sn.lower() in name_lower:
                return sn
        return None

    def _validate_tier_name(self, name: str, category: str) -> Optional[str]:
        """Find the matching tier item name within a category."""
        tier_names = self.all_tier_names.get(category, set())
        if name in tier_names:
            return name
        # Case-insensitive match
        name_lower = name.lower()
        for tn in tier_names:
            if tn.lower() == name_lower:
                return tn
        # Substring match
        for tn in tier_names:
            if name_lower in tn.lower() or tn.lower() in name_lower:
                return tn
        return None

    def _validate_classification(self, item_name: str, match_type: str,
                                  match_name: str, category: str) -> bool:
        """Verify an LLM classification by checking keyword overlap.

        Returns True if valid, False if rejected. Logs all rejections.
        """
        item_lower = item_name.lower()

        # Look up keywords and avoid list
        if match_type == "staple":
            lookup = self.staple_keywords.get(match_name)
        elif match_type == "tier":
            lookup = self.tier_keywords.get((category, match_name))
        else:
            return False

        if not lookup:
            logger.warning(f"[VALIDATION] REJECTED: \"{item_name}\" → {match_name} "
                          f"(no lookup found for {match_type}:{match_name})")
            return False

        # Check avoid list first
        for avoid_word in lookup["avoid"]:
            if avoid_word in item_lower:
                logger.warning(f"[VALIDATION] REJECTED: \"{item_name}\" → {match_name} "
                              f"(avoid word: \"{avoid_word}\")")
                return False

        # Check if any keyword appears in the flyer item name
        for keyword in lookup["keywords"]:
            if keyword in item_lower:
                return True

        # Check if match name itself appears (strip trailing 's' for singular/plural)
        match_lower = match_name.lower()
        if match_lower in item_lower:
            return True
        match_stripped = match_lower.rstrip("s")
        if match_stripped and match_stripped in item_lower:
            return True

        logger.warning(f"[VALIDATION] REJECTED: \"{item_name}\" → {match_name} "
                      f"(no keyword overlap)")
        return False

    def _build_results(self, all_items: list, classifications: dict,
                       unit_prices: dict) -> PipelineResults:
        """Convert raw classifications into PipelineResults format."""
        staples_dict = {}
        tier_dict = {}

        # Initialize with all staple names (preserving config order)
        for staple in self.staples:
            staples_dict[staple["name"]] = []

        for category in ("meat", "carbs", "vegetables", "fruit"):
            tier_dict[category] = []

        # Track seen items for deduplication
        staple_seen = {}
        tier_seen = {}

        for idx, classification in classifications.items():
            if idx >= len(all_items):
                continue

            item = all_items[idx]
            up = unit_prices[id(item)]
            match_type = classification["type"]
            match_name = classification["match"]

            if match_type == "staple":
                dedup_key = (item.name, item.merchant)
                if match_name not in staple_seen:
                    staple_seen[match_name] = set()
                if dedup_key in staple_seen[match_name]:
                    continue
                staple_seen[match_name].add(dedup_key)

                staples_dict[match_name].append(RankedItem(
                    item=item,
                    category=classification.get("category", "other"),
                    unit_price=up,
                    matched_staple=match_name,
                ))

            elif match_type == "tier":
                category = classification["category"]
                tier_num = classification["tier"]

                dedup_key = (item.name, item.merchant)
                if category not in tier_seen:
                    tier_seen[category] = set()
                if dedup_key in tier_seen[category]:
                    continue
                tier_seen[category].add(dedup_key)

                # Cross-reference: check if this item is also a staple
                staple_name = None
                for sname, sitems in staples_dict.items():
                    for ri in sitems:
                        if ri.item.name == item.name and ri.item.merchant == item.merchant:
                            staple_name = sname
                            break
                    if staple_name:
                        break

                tier_dict[category].append(RankedItem(
                    item=item,
                    category=category,
                    unit_price=up,
                    matched_tier_item=match_name,
                    tier=tier_num,
                    matched_staple=staple_name,
                ))

        # Post-processing: tier items that match a staple should also appear in staples.
        # The LLM sometimes classifies "FARMER'S MARKET LEMONS" as tier:fruit:Lemons
        # instead of staple:Lemon. Cross-reference tier results with staple names.
        tier_to_staple = {}  # tier item name -> staple name
        for staple in self.staples:
            sname = staple["name"].lower()
            for category in ("meat", "carbs", "vegetables", "fruit"):
                for tn in self.all_tier_names.get(category, set()):
                    if tn.lower() == sname or tn.lower().rstrip("s") == sname.rstrip("s"):
                        tier_to_staple[tn] = staple["name"]

        for category, tier_items in tier_dict.items():
            for ri in tier_items:
                matched_staple_name = tier_to_staple.get(ri.matched_tier_item)
                if matched_staple_name and matched_staple_name in staples_dict:
                    dedup_key = (ri.item.name, ri.item.merchant)
                    if matched_staple_name not in staple_seen:
                        staple_seen[matched_staple_name] = set()
                    if dedup_key not in staple_seen[matched_staple_name]:
                        staple_seen[matched_staple_name].add(dedup_key)
                        staples_dict[matched_staple_name].append(RankedItem(
                            item=ri.item,
                            category=ri.category,
                            unit_price=ri.unit_price,
                            matched_staple=matched_staple_name,
                        ))
                    # Also tag the tier item as a staple
                    ri.matched_staple = matched_staple_name

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
        """Build the system prompt with staples and tier lists."""
        lines = [
            "You are a grocery item classifier. You receive flyer items and classify each one.",
            "Classify as 'staple', 'tier', or skip (don't include) if no match.",
            "",
            "STAPLES (items bought every week):",
        ]
        for s in self.staples:
            lines.append(f"  - {s['name']}")

        lines.append("")
        lines.append("TIER LISTS (ranked food items):")
        for category in ("meat", "carbs", "vegetables", "fruit"):
            lines.append(f"  {category.upper()}:")
            for tier_group in self.tier_lists.get(category, []):
                tier_num = tier_group.get("tier", 1)
                for entry in tier_group.get("items", []):
                    lines.append(f"    Tier {tier_num}: {entry['name']}")

        lines.extend([
            "",
            "RULES:",
            "1. Only match FRESH, RAW, or MINIMALLY PROCESSED food items.",
            "2. EXCLUDE: prepared/frozen meals, sauces, condiments, oils, juices, dips, spreads,",
            "   deli meats, snacks, candy, baked goods, cleaning products, health/beauty items.",
            "3. Be PRECISE: 'Avocado Oil' is NOT 'Avocados'. 'Garlic Bread' is NOT 'Garlic'.",
            "   'Cadbury Mini Eggs' is candy, NOT 'Eggs'. 'Egg Noodles' is NOT 'Eggs'.",
            "   'Lemon Juice' is NOT 'Lemons'. 'Coconut Milk' is NOT 'Coconut'.",
            "4. If an item could match a staple, classify it as 'staple' (not 'tier').",
            "5. When unsure, skip the item. False negatives are better than false positives.",
            "6. Use the EXACT names from the lists above for the 'match' field.",
            "7. CRITICAL: NEVER classify non-food products (medicine, cleaning supplies,",
            "   personal care, pet food, baby products, electronics, appliances, clothing).",
            "8. The flyer item name MUST contain a word related to the match. If there is",
            "   no clear textual connection, skip it.",
            "9. IMPORTANT: Double-check your idx values. The idx MUST correspond to the",
            "   exact line number of the item you are classifying.",
            "",
            "RESPOND with JSON: {\"items\": [{\"idx\": 0, \"type\": \"staple\", \"match\": \"Avocados\"}, "
            "{\"idx\": 3, \"type\": \"tier\", \"category\": \"meat\", \"match\": \"Salmon\", \"tier\": 1}]}",
            "",
            "Only include items that match. Skip items that don't match anything.",
        ])
        return "\n".join(lines)

    def _build_user_prompt(self, batch: list) -> str:
        """Build the user prompt for a batch of items."""
        lines = ["Classify these flyer items:", ""]
        for i, item in enumerate(batch):
            price_str = f" ${item.price:.2f}" if item.price else ""
            lines.append(f"{i}. {item.name}{price_str} [{item.merchant}]")
        lines.append("")
        lines.append("Return JSON with classifications. Skip non-matching items.")
        return "\n".join(lines)
