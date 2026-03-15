"""
Diagnostic script for LLM item classification.

Tests the Ollama-based classifier to identify false positives, false negatives,
index confusion, and the impact of batch size and post-validation.

Usage:
    python tests/diagnose_llm.py --capture       # Phase 1: Capture raw LLM output
    python tests/diagnose_llm.py --compare       # Phase 2: Compare LLM vs keywords
    python tests/diagnose_llm.py --batch-test    # Phase 3: Test batch sizes (25, 50, 100)
    python tests/diagnose_llm.py --batch-test 25 # Phase 3: Test a single batch size
    python tests/diagnose_llm.py --prompt-test   # Phase 4: Test item_name in prompt
"""

import argparse
import json
import logging
import os
import sys
import time
import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import FlyerItem, RankedItem, PipelineResults
from src.llm_classifier import OllamaClassifier, REQUEST_TIMEOUT
from src.item_matcher import ItemMatcher
from src.main import load_yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DIAG_DIR = os.path.join(DATA_DIR, "diagnostics")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_cached_items() -> dict:
    """Load flyer items from data/last_run.json."""
    path = os.path.join(DATA_DIR, "last_run.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    store_items = {}
    for store_key, items in raw.items():
        store_items[store_key] = [
            FlyerItem(
                name=item["name"],
                price=item.get("price"),
                price_text=item.get("price_text", ""),
                unit=item.get("unit", "each"),
                merchant=item.get("merchant", store_key),
                flyer_id="",
            )
            for item in items
        ]
    return store_items


def load_config():
    """Load preferences and tier_lists."""
    prefs = load_yaml(os.path.join(CONFIG_DIR, "preferences.yaml"))
    tiers = load_yaml(os.path.join(CONFIG_DIR, "tier_lists.yaml"))
    settings = load_yaml(os.path.join(CONFIG_DIR, "settings.yaml"))
    return prefs, tiers, settings


def flatten_items(store_items: dict) -> list:
    """Flatten store_items dict into a single list."""
    all_items = []
    for items in store_items.values():
        all_items.extend(items)
    return all_items


def extract_match_set(results: PipelineResults) -> dict:
    """Extract a dict of (item_name, merchant) -> match_info from PipelineResults."""
    matches = {}
    for staple_name, ranked_items in results.staples.items():
        for ri in ranked_items:
            key = (ri.item.name, ri.item.merchant)
            matches[key] = {"type": "staple", "match": staple_name}
    for category, ranked_items in results.tier_results.items():
        for ri in ranked_items:
            key = (ri.item.name, ri.item.merchant)
            if key not in matches:  # staple takes precedence
                matches[key] = {
                    "type": "tier", "match": ri.matched_tier_item,
                    "category": category, "tier": ri.tier,
                }
    return matches


def has_keyword_overlap(item_name: str, match_name: str) -> bool:
    """Simple check: does the item name contain a word from the match name?"""
    item_lower = item_name.lower()
    match_lower = match_name.lower()
    # Check if match name (or singular form) appears in item
    if match_lower in item_lower:
        return True
    if match_lower.rstrip("s") in item_lower:
        return True
    # Check individual words from match name
    for word in match_lower.split():
        if len(word) > 3 and word in item_lower:
            return True
    return False


# ── Diagnostic Classifier ────────────────────────────────────────────────────

class DiagnosticClassifier(OllamaClassifier):
    """Subclass that captures raw LLM responses before validation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_logs = []
        self.skip_validation = False  # Set True for no-validation mode

    def _classify_batch(self, batch: list, start_index: int) -> dict:
        """Override to capture raw LLM response."""
        user_prompt = self._build_user_prompt(batch)

        batch_log = {
            "batch_start": start_index,
            "batch_size": len(batch),
            "items_sent": [
                {"idx": i, "name": batch[i].name, "merchant": batch[i].merchant}
                for i in range(len(batch))
            ],
        }

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
                    "options": {"temperature": 0.1, "num_ctx": 16384},
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")

            # Save raw response
            try:
                raw_data = json.loads(content)
            except json.JSONDecodeError:
                raw_data = {"error": "invalid JSON", "raw": content[:500]}

            batch_log["raw_llm_response"] = raw_data

            # Parse with validation (standard behavior)
            results_with_validation = self._parse_llm_response(content, batch, start_index)
            batch_log["accepted_with_validation"] = {
                str(k): v for k, v in results_with_validation.items()
            }

            # Parse WITHOUT validation to see what would pass
            results_no_validation = self._parse_no_validation(raw_data, batch, start_index)
            batch_log["accepted_no_validation"] = {
                str(k): v for k, v in results_no_validation.items()
            }

            # Detect index confusion
            confusions = self._detect_index_confusion(raw_data, batch)
            batch_log["index_confusions"] = confusions

            self.batch_logs.append(batch_log)

            if self.skip_validation:
                return results_no_validation
            return results_with_validation

        except Exception as e:
            batch_log["error"] = str(e)
            self.batch_logs.append(batch_log)
            return {}

    def _parse_no_validation(self, data: dict, batch: list, start_index: int) -> dict:
        """Parse LLM response WITHOUT avoid-keyword filtering. Uses name-only lookup."""
        results = {}
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

            match_name = entry.get("match", "").strip()
            if not match_name:
                continue

            abs_idx = start_index + idx
            name_lower = match_name.lower()

            # Check staples (case-insensitive, no avoid filtering)
            canonical_staple = self.staple_name_map.get(name_lower)
            if canonical_staple:
                results[abs_idx] = {
                    "type": "staple",
                    "match": canonical_staple,
                    "category": self.staple_categories.get(canonical_staple, "other"),
                    "tier": None,
                }

            # Check tiers (case-insensitive, no avoid filtering)
            for category, canonical_tier, tier_num in self.tier_name_map.get(name_lower, []):
                results[abs_idx] = {
                    "type": "tier",
                    "match": canonical_tier,
                    "category": category,
                    "tier": tier_num,
                }

        return results

    def _detect_index_confusion(self, data: dict, batch: list) -> list:
        """Detect cases where the LLM's idx doesn't match the item it meant."""
        confusions = []
        items_list = data.get("items", [])
        if isinstance(data, list):
            items_list = data

        for entry in items_list:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("idx")
            match_name = entry.get("match", "")
            if idx is None or not isinstance(idx, int):
                continue
            if idx < 0 or idx >= len(batch):
                continue

            claimed_item = batch[idx].name
            claimed_has_overlap = has_keyword_overlap(claimed_item, match_name)

            if not claimed_has_overlap:
                # Find which item the LLM probably meant
                candidates = []
                for i, item in enumerate(batch):
                    if i != idx and has_keyword_overlap(item.name, match_name):
                        candidates.append({"idx": i, "name": item.name})

                confusions.append({
                    "llm_idx": idx,
                    "llm_claimed_item": claimed_item,
                    "llm_match": match_name,
                    "llm_type": entry.get("type"),
                    "likely_intended": candidates[:3],  # Top 3 candidates
                })

        return confusions


# ── Prompt-improved Classifier ───────────────────────────────────────────────

class PromptTestClassifier(DiagnosticClassifier):
    """Tests a modified prompt that asks for item_name in the response."""

    def _build_system_prompt(self) -> str:
        """Same as parent but asks for item_name in response."""
        prompt = super()._build_system_prompt()
        # Replace the response format line
        old_format = (
            'RESPOND with JSON: {"items": [{"idx": 0, "type": "staple", "match": "Avocados"}, '
            '{"idx": 3, "type": "tier", "category": "meat", "match": "Salmon", "tier": 1}]}'
        )
        new_format = (
            'RESPOND with JSON: {"items": [{"idx": 0, "name": "HASS AVOCADOS PKG OF 5", '
            '"type": "staple", "match": "Avocados"}, '
            '{"idx": 3, "name": "ATLANTIC SALMON FILLETS", '
            '"type": "tier", "category": "meat", "match": "Salmon", "tier": 1}]}\n'
            'IMPORTANT: The "name" field MUST be the EXACT flyer item name from the list above. '
            'This helps verify the idx is correct.'
        )
        return prompt.replace(old_format, new_format)


# ── Phase 1: Capture ─────────────────────────────────────────────────────────

def run_capture(store_items, prefs, tiers, settings):
    """Phase 1: Capture raw LLM output for each batch."""
    print("\n=== PHASE 1: Capture Raw LLM Output ===\n")

    ollama = settings.get("ollama", {})
    model_name = ollama.get("model", "qwen2.5:14b")
    classifier = DiagnosticClassifier(
        staples=prefs.get("staples", []),
        tier_lists=tiers,
        ollama_url=ollama.get("url", "http://localhost:11434"),
        model=model_name,
        batch_size=25,  # Best accuracy from Phase 3 testing
    )

    if not classifier.is_available():
        print(f"ERROR: Model '{model_name}' not available. Pull it with: ollama pull {model_name}")
        return

    print(f"Model: {classifier.model}, Batch size: {classifier.batch_size}")
    all_items = flatten_items(store_items)
    print(f"Total items: {len(all_items)}\n")

    results = classifier.classify_all(store_items)

    # Save batch logs per model (so they don't overwrite each other)
    model_tag = model_name.replace(":", "_").replace("/", "_")
    model_dir = os.path.join(DIAG_DIR, model_tag)
    os.makedirs(model_dir, exist_ok=True)
    for i, log in enumerate(classifier.batch_logs):
        path = os.path.join(model_dir, f"batch_{i:03d}_raw.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, default=str)

    # Print summary
    total_raw = 0
    total_accepted = 0
    total_no_val = 0
    total_confusions = 0
    for log in classifier.batch_logs:
        raw = log.get("raw_llm_response", {})
        raw_items = raw.get("items", []) if isinstance(raw, dict) else []
        total_raw += len(raw_items)
        total_accepted += len(log.get("accepted_with_validation", {}))
        total_no_val += len(log.get("accepted_no_validation", {}))
        total_confusions += len(log.get("index_confusions", []))

    print(f"Results:")
    print(f"  Raw LLM classifications:    {total_raw}")
    print(f"  Accepted (with validation): {total_accepted}")
    print(f"  Accepted (no validation):   {total_no_val}")
    print(f"  Rejected by validation:     {total_no_val - total_accepted}")
    print(f"  Index confusions detected:  {total_confusions}")

    # Show index confusions
    if total_confusions > 0:
        print(f"\n--- Index Confusions ---")
        for log in classifier.batch_logs:
            for c in log.get("index_confusions", []):
                print(f"  LLM said idx={c['llm_idx']} ({c['llm_claimed_item'][:50]})")
                print(f"    -> match: {c['llm_match']} ({c['llm_type']})")
                if c["likely_intended"]:
                    for cand in c["likely_intended"]:
                        print(f"    -> probably meant idx={cand['idx']} ({cand['name'][:50]})")
                else:
                    print(f"    -> no obvious candidate found in batch")
                print()

    summary_path = os.path.join(model_dir, "capture_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "model": model_name,
            "total_items": len(all_items),
            "batch_size": classifier.batch_size,
            "total_batches": len(classifier.batch_logs),
            "raw_classifications": total_raw,
            "accepted_with_validation": total_accepted,
            "accepted_no_validation": total_no_val,
            "rejected_by_validation": total_no_val - total_accepted,
            "index_confusions": total_confusions,
        }, f, indent=2)

    print(f"\nBatch logs saved to: {model_dir}/")


# ── Phase 2: Compare ─────────────────────────────────────────────────────────

def run_compare(store_items, prefs, tiers, settings):
    """Phase 2: Compare keyword vs LLM (with/without validation)."""
    print("\n=== PHASE 2: Compare Matching Methods ===\n")

    ollama = settings.get("ollama", {})

    # 1. Keyword baseline
    print("Running keyword matching...")
    kw_matcher = ItemMatcher(prefs, tiers, matching_mode="keyword")
    kw_results = kw_matcher.match_all(store_items)
    kw_matches = extract_match_set(kw_results)
    print(f"  Keyword matches: {len(kw_matches)}")

    # 2. LLM with validation
    print("Running LLM matching (with validation)...")
    classifier = DiagnosticClassifier(
        staples=prefs.get("staples", []),
        tier_lists=tiers,
        ollama_url=ollama.get("url", "http://localhost:11434"),
        model=ollama.get("model", "qwen2.5:14b"),
        batch_size=ollama.get("batch_size", 100),
    )
    if not classifier.is_available():
        print("ERROR: Ollama not available.")
        return

    llm_val_results = classifier.classify_all(store_items)
    llm_val_matches = extract_match_set(llm_val_results)
    print(f"  LLM (validated) matches: {len(llm_val_matches)}")

    # 3. LLM without validation (reuse the batch logs from above)
    print("Extracting LLM results without validation (from same run)...")
    llm_noval_matches = {}
    all_items = flatten_items(store_items)
    for log in classifier.batch_logs:
        for idx_str, classification in log.get("accepted_no_validation", {}).items():
            idx = int(idx_str)
            if idx < len(all_items):
                item = all_items[idx]
                key = (item.name, item.merchant)
                llm_noval_matches[key] = classification
    print(f"  LLM (no validation) matches: {len(llm_noval_matches)}")

    # Compare
    kw_set = set(kw_matches.keys())
    llm_val_set = set(llm_val_matches.keys())
    llm_noval_set = set(llm_noval_matches.keys())

    print(f"\n--- Comparison ---")
    print(f"{'Method':<30} {'Matches':>8}")
    print(f"{'-'*38}")
    print(f"{'Keyword (baseline)':<30} {len(kw_set):>8}")
    print(f"{'LLM + validation':<30} {len(llm_val_set):>8}")
    print(f"{'LLM (no validation)':<30} {len(llm_noval_set):>8}")

    # What does validation filter out?
    validation_killed = llm_noval_set - llm_val_set
    print(f"\n--- Validation Impact ---")
    print(f"Items rejected by validation: {len(validation_killed)}")
    if validation_killed:
        print(f"\nRejected items (validation killed these):")
        for key in sorted(validation_killed):
            info = llm_noval_matches[key]
            in_keywords = "YES (keyword also found it)" if key in kw_set else "NO"
            print(f"  {key[0][:55]:<55} → {info['match']:<20} [kw baseline: {in_keywords}]")

    # LLM-only matches (things LLM found that keywords didn't)
    llm_only_noval = llm_noval_set - kw_set
    print(f"\n--- LLM Found, Keywords Missed (no validation) ---")
    print(f"Count: {len(llm_only_noval)}")
    if llm_only_noval:
        for key in sorted(llm_only_noval):
            info = llm_noval_matches[key]
            print(f"  {key[0][:55]:<55} → {info['match']}")

    # Keywords found, LLM missed
    kw_only = kw_set - llm_noval_set
    print(f"\n--- Keywords Found, LLM Missed ---")
    print(f"Count: {len(kw_only)}")
    if kw_only:
        for key in sorted(kw_only):
            info = kw_matches[key]
            print(f"  {key[0][:55]:<55} → {info['match']}")

    # Agreement
    agree = kw_set & llm_noval_set
    print(f"\n--- Both Agree ---")
    print(f"Count: {len(agree)}")

    # Save report
    os.makedirs(DIAG_DIR, exist_ok=True)
    report = {
        "keyword_count": len(kw_set),
        "llm_validated_count": len(llm_val_set),
        "llm_no_validation_count": len(llm_noval_set),
        "validation_killed": len(validation_killed),
        "llm_only": len(llm_only_noval),
        "keyword_only": len(kw_only),
        "both_agree": len(agree),
        "validation_killed_items": [
            {"item": k[0], "store": k[1], "match": llm_noval_matches[k]["match"],
             "in_keyword_baseline": k in kw_set}
            for k in sorted(validation_killed)
        ],
        "llm_only_items": [
            {"item": k[0], "store": k[1], "match": llm_noval_matches[k]["match"]}
            for k in sorted(llm_only_noval)
        ],
        "keyword_only_items": [
            {"item": k[0], "store": k[1], "match": kw_matches[k]["match"]}
            for k in sorted(kw_only)
        ],
    }
    path = os.path.join(DIAG_DIR, "comparison_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull report saved to: {path}")


# ── Phase 3: Batch Size Test ─────────────────────────────────────────────────

def run_batch_test(store_items, prefs, tiers, settings, sizes=None):
    """Phase 3: Test different batch sizes."""
    if sizes is None:
        sizes = [25, 50, 100]

    print(f"\n=== PHASE 3: Batch Size Experiment ({sizes}) ===\n")

    ollama = settings.get("ollama", {})
    all_items = flatten_items(store_items)
    print(f"Total items: {len(all_items)}\n")

    results_table = []

    for batch_size in sizes:
        print(f"--- Testing batch_size={batch_size} ---")
        classifier = DiagnosticClassifier(
            staples=prefs.get("staples", []),
            tier_lists=tiers,
            ollama_url=ollama.get("url", "http://localhost:11434"),
            model=ollama.get("model", "qwen2.5:14b"),
            batch_size=batch_size,
        )
        if not classifier.is_available():
            print("ERROR: Ollama not available.")
            return

        start_time = time.time()
        classifier.classify_all(store_items)
        elapsed = time.time() - start_time

        total_raw = 0
        total_accepted = 0
        total_no_val = 0
        total_confusions = 0
        for log in classifier.batch_logs:
            raw = log.get("raw_llm_response", {})
            raw_items = raw.get("items", []) if isinstance(raw, dict) else []
            total_raw += len(raw_items)
            total_accepted += len(log.get("accepted_with_validation", {}))
            total_no_val += len(log.get("accepted_no_validation", {}))
            total_confusions += len(log.get("index_confusions", []))

        row = {
            "batch_size": batch_size,
            "batches": len(classifier.batch_logs),
            "raw_matches": total_raw,
            "accepted_validated": total_accepted,
            "accepted_no_val": total_no_val,
            "rejected": total_no_val - total_accepted,
            "index_confusions": total_confusions,
            "time_seconds": round(elapsed, 1),
        }
        results_table.append(row)
        print(f"  Raw: {total_raw}, Accepted: {total_accepted}, "
              f"NoVal: {total_no_val}, Confusions: {total_confusions}, "
              f"Time: {elapsed:.0f}s")

        # Save per-size batch logs
        os.makedirs(DIAG_DIR, exist_ok=True)
        for i, log in enumerate(classifier.batch_logs):
            path = os.path.join(DIAG_DIR, f"batch_sz{batch_size}_{i:03d}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(log, f, indent=2, default=str)

        print()

    # Print comparison table
    print(f"\n{'Batch':>6} {'Batches':>8} {'Raw':>6} {'Validated':>10} "
          f"{'No-Val':>7} {'Rejected':>9} {'Confusions':>11} {'Time':>6}")
    print("-" * 75)
    for r in results_table:
        print(f"{r['batch_size']:>6} {r['batches']:>8} {r['raw_matches']:>6} "
              f"{r['accepted_validated']:>10} {r['accepted_no_val']:>7} "
              f"{r['rejected']:>9} {r['index_confusions']:>11} "
              f"{r['time_seconds']:>5.0f}s")

    # Save table
    path = os.path.join(DIAG_DIR, "batch_size_comparison.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results_table, f, indent=2)
    print(f"\nResults saved to: {path}")


# ── Phase 4: Prompt Test ─────────────────────────────────────────────────────

def run_prompt_test(store_items, prefs, tiers, settings):
    """Phase 4: Test asking LLM to return item_name alongside idx."""
    print("\n=== PHASE 4: Prompt Improvement Test (item_name) ===\n")

    ollama = settings.get("ollama", {})
    batch_size = ollama.get("batch_size", 100)

    # Use the prompt-improved classifier on just the first batch
    classifier = PromptTestClassifier(
        staples=prefs.get("staples", []),
        tier_lists=tiers,
        ollama_url=ollama.get("url", "http://localhost:11434"),
        model=ollama.get("model", "qwen2.5:14b"),
        batch_size=batch_size,
    )
    if not classifier.is_available():
        print("ERROR: Ollama not available.")
        return

    all_items = flatten_items(store_items)
    # Run just the first batch
    batch = all_items[:batch_size]
    print(f"Testing with first {len(batch)} items (batch_size={batch_size})\n")

    classifier._classify_batch(batch, 0)

    if not classifier.batch_logs:
        print("ERROR: No batch results.")
        return

    log = classifier.batch_logs[0]
    raw = log.get("raw_llm_response", {})
    items_list = raw.get("items", []) if isinstance(raw, dict) else []

    total = len(items_list)
    idx_matches = 0
    idx_mismatches = 0
    no_name_field = 0
    recoverable = 0

    print(f"LLM returned {total} classifications\n")

    for entry in items_list:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("idx")
        returned_name = entry.get("name", "")
        match_name = entry.get("match", "")

        if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(batch):
            continue

        actual_name = batch[idx].name

        if not returned_name:
            no_name_field += 1
            continue

        # Check if the returned name matches the item at that idx
        if returned_name.strip().lower() == actual_name.strip().lower():
            idx_matches += 1
        else:
            idx_mismatches += 1
            # Try to find the correct item
            found = False
            for i, item in enumerate(batch):
                if returned_name.strip().lower() in item.name.lower() or \
                   item.name.lower() in returned_name.strip().lower():
                    recoverable += 1
                    found = True
                    print(f"  MISMATCH: idx={idx}")
                    print(f"    LLM returned name: {returned_name[:60]}")
                    print(f"    Actual at idx={idx}: {actual_name[:60]}")
                    print(f"    Correct idx={i}:     {item.name[:60]}")
                    print(f"    Match: {match_name}")
                    print()
                    break
            if not found:
                print(f"  MISMATCH (unrecoverable): idx={idx}")
                print(f"    LLM returned name: {returned_name[:60]}")
                print(f"    Actual at idx={idx}: {actual_name[:60]}")
                print(f"    Match: {match_name}")
                print()

    print(f"\n--- Summary ---")
    print(f"Total classifications:  {total}")
    print(f"Index correct:          {idx_matches}")
    print(f"Index WRONG:            {idx_mismatches}")
    print(f"  Recoverable via name: {recoverable}")
    print(f"  Unrecoverable:        {idx_mismatches - recoverable}")
    print(f"No name field returned: {no_name_field}")

    if total > 0:
        accuracy = idx_matches / max(idx_matches + idx_mismatches, 1) * 100
        print(f"\nIndex accuracy: {accuracy:.1f}%")

    # Save results
    os.makedirs(DIAG_DIR, exist_ok=True)
    path = os.path.join(DIAG_DIR, "prompt_test_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "batch_size": batch_size,
            "total_classifications": total,
            "idx_correct": idx_matches,
            "idx_wrong": idx_mismatches,
            "recoverable": recoverable,
            "no_name_field": no_name_field,
            "raw_response": raw,
        }, f, indent=2, default=str)
    print(f"\nResults saved to: {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnose LLM item classification")
    parser.add_argument("--capture", action="store_true", help="Phase 1: Capture raw LLM output")
    parser.add_argument("--compare", action="store_true", help="Phase 2: Compare methods")
    parser.add_argument("--batch-test", nargs="?", const="all", default=None,
                        help="Phase 3: Test batch sizes (default: 25,50,100; or specify one)")
    parser.add_argument("--prompt-test", action="store_true", help="Phase 4: Test item_name prompt")
    parser.add_argument("--model", type=str, default=None,
                        help="Override Ollama model (e.g., gemma3:27b, qwen3:32b)")
    args = parser.parse_args()

    if not any([args.capture, args.compare, args.batch_test, args.prompt_test]):
        parser.print_help()
        return

    # Setup
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    store_items = load_cached_items()
    prefs, tiers, settings = load_config()

    # Override model if specified
    if args.model:
        if "ollama" not in settings:
            settings["ollama"] = {}
        settings["ollama"]["model"] = args.model

    total = sum(len(v) for v in store_items.values())
    print(f"Loaded {total} items from {len(store_items)} stores")

    if args.capture:
        run_capture(store_items, prefs, tiers, settings)
    if args.compare:
        run_compare(store_items, prefs, tiers, settings)
    if args.batch_test:
        if args.batch_test == "all":
            run_batch_test(store_items, prefs, tiers, settings)
        else:
            run_batch_test(store_items, prefs, tiers, settings, sizes=[int(args.batch_test)])
    if args.prompt_test:
        run_prompt_test(store_items, prefs, tiers, settings)


if __name__ == "__main__":
    main()
