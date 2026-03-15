# Grocery Planner — Change Log

---

## Mar 15, 2026 — Added --fast flag for quick test runs

Added `--fast` CLI flag to `run.py`. When passed, overrides the LLM model to `qwen2.5:14b` (~3 min) instead of the default `qwen3:32b` (~50 min). Useful for testing changes without waiting for the full-accuracy run.

---

## Mar 15, 2026 — Consolidated to single folder for deploy

**Problem:** Two local folders (`grocery_planner` and `cams-grocery-deals`) both pointed to the same GitHub repo. The deploy step copied `index.html` to the second folder, committed, and pushed from there — unnecessary duplication.

**Fix:** Simplified `deploy_to_github_pages()` in `src/main.py` to commit and push `index.html` directly from the project directory. Removed the `deploy.github_pages_repo` setting from `config/settings.yaml`. The `cams-grocery-deals` folder can now be deleted.

---

## Mar 15, 2026 — Upgraded LLM to qwen3:32b

**Problem:** qwen2.5:14b was producing obvious false positives: dog food as chicken thighs, parsley as yogurt, steelhead fish as steak, frozen vegetables as frozen fruit, limes as oranges, peanut butter as oats, udon noodles as buckwheat.

**Fix:** Switched model from `qwen2.5:14b` to `qwen3:32b` in `config/settings.yaml`. Model was already installed locally and noted in the config as the recommended upgrade.

**Result:** All 8 tracked false positives resolved. Tier items increased from 82 to 98 (new finds: shrimp, lamb, papaya, watermelon, apples, cucumbers, romaine). Staples stayed steady at 73. Run time increased from ~3 min to ~50 min but only runs weekly.

---

## Mar 09, 2026 — Classification Fixes + Vegetables for Meals

**Salmon false positives fixed:** Added avoid keywords (`tilapia, pompano, cod, snakehead, tuna, breaded, fish stick, side dish, mixed pack`) to both `config/tier_lists.yaml` (Salmon T1) and `config/preferences.yaml` (Salmon staple). Dropped from ~10 wrong matches to 2 remaining questionable ones.

**Vegetables for Meals fixed:** Removed LLM matching entirely for this staple — it was matching vitamins and health products. Now derived in `src/item_matcher.py` by filtering the vegetables tier results against a `meal_vegetables` whitelist defined in `config/preferences.yaml`. Shows broccoli, carrots, peppers, zucchini, green beans — no junk.

**Result:** 53 staple hits, 70 tier items (Mar 9 flyer data).

---

## Mar 04, 2026 — Names-Only LLM Response

**Problem:** Diagnostic revealed 137 LLM entries where the `type` field was wrong (e.g. `"fruit"` instead of `"tier"`), silently dropping 65 valid matches. Root cause: asking the LLM to fill in bookkeeping fields (type/category/tier) it doesn't need to know.

**Fix:** LLM now returns only `{"idx": N, "match": "Name"}`. Code does all lookups via `staple_name_map` and `tier_name_map`. One name can match both a staple and a tier category — the code adds it to both automatically.

**Changes made:**
- `src/llm_classifier.py` — `__init__`: added `staple_name_map` and `tier_name_map` for case-insensitive lookup
- `src/llm_classifier.py` — `_parse_llm_response()`: reads only `match` field, does code-side lookup
- `src/llm_classifier.py` — `_build_system_prompt()`: simplified response format, added exact-name rule
- `tests/diagnose_llm.py` — `_parse_no_validation()`: updated to use same names-only lookup

**Result:** 79 staple hits (fully recovered to baseline), 89 tier items (up from 61).

---

## Mar 04, 2026 — LLM Classification Improvement

**Problem:** The old two-step pipeline identified a generic food name (e.g. `"beef strips"`) then keyword-matched it against staples/tiers. This threw away 40–70% of valid identifications because the LLM's phrasing didn't contain the exact keyword.

**Fix:** The LLM now receives the full target list (all staple names + all tier items with tier numbers) in the system prompt and returns the exact match name directly. The keyword matching layer is removed entirely.

**Changes made (only `src/llm_classifier.py`):**
- `__init__`: Replaced `staple_keywords`/`tier_keywords` with `staple_avoids`, `tier_avoids`, `tier_tiers`
- `_build_system_prompt()`: Dynamically builds prompt listing all staples and tier items by name
- `_parse_llm_response()`: Reads `entry["match"]` directly, validates against known names
- Deleted `_match_food_to_lists()` and `_food_matches_keywords()` (no longer needed)

**Result:** Pipeline ran clean. 67 staple hits, 61 tier items.
