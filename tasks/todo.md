# Costco Deals - Investigation & Future Tasks

## Investigation Summary

Costco IS being fetched from Flipp (410 items), but only 8 make it to the report. ~90% of Costco's Flipp flyer is non-grocery (TVs, furniture, clothing, golf equipment). No code bug — data quality issue.

**Current matches:** 5 cheese, 1 yogurt, 1 spaghetti (carbs T3), 1 beets (vegetables T2)

## To-Do

- [ ] **Improve Flipp matching** — Some food items like oatmeal, tortillas, haddock exist in the Costco flyer but aren't matched. Review LLM prompt in `src/llm_classifier.py` to ensure it doesn't over-filter (e.g. oatmeal skipped as "cereal"). Add haddock/white fish to `config/tier_lists.yaml`. Small effort.

- [ ] **Evaluate CocoWest.ca scraping** — Active blog (cocowest.ca) covering Western Canada unadvertised Costco deals. Monday sales posts, weekend updates. Narrative format (not structured), behind membership for early access. Would need HTML parsing. Medium effort, fragile.

- [ ] **Decide: keep or remove Costco** — If matching improvements don't yield enough value, remove from `config/stores.yaml`. Config already notes: "Check Costco app separately for deals."

## Sources Evaluated (not worth pursuing)

| Source | Why Not |
|--------|---------|
| costco.ca | Blocks scraping, no public API |
| Costco Insider | Image-based coupon books, needs OCR |
| RedFlagDeals | Unstructured forum posts, YMMV per warehouse |
| Reebee | Same Flipp backend data |

## Classification Fixes (from Mar 8 evaluation)
- [ ] **Fix Salmon false positives** — LLM matches any seafood as "Salmon": pompano, tilapia, snakehead, black cod, tuna, seafood mixed packs, and even "Reser's side dishes" (non-food). Tighten avoid keywords in `config/tier_lists.yaml` for Salmon (add: tilapia, pompano, snakehead, cod, tuna, side dish). Also investigate why "breaded" avoid didn't filter out the High Liner fish sticks.
- [ ] **Fix Chicken Thighs false positive** — "Smoked Cured Speck Whole Piece" (Costco, cured pork) was matched as Chicken Thighs. Add avoid keywords: speck, cured, prosciutto.
- [ ] **Fix Vegetables for Meals** — Currently matches vitamins and health products (e.g. Nature's Bounty). The category has no real content. Fix: populate it from the vegetables tier list, but only include "meal-sized" vegetables (broccoli, carrots, peppers, zucchini, green beans, cauliflower, etc.). Exclude small/condiment vegetables like tomatoes, lemons, cilantro, ginger, pickles. Probably best implemented as a filter in `src/report_generator.py` or `src/item_matcher.py` that pulls from tier results rather than its own LLM match.
- [ ] **Fix Dill Pickles false positive** — "TAMAM SLICED PICKLE TURNIPS" matched as Dill Pickles. Add avoid keyword: turnip.

## New Feature Requests / Bugs
- [ ] **OurGroceries auto-add** — Long-term: checkboxes on each item in report + "Add All Selected" button to push selected items to the correct OurGroceries list. Button probably should be small but hover at the bottom when at least one is clicked. Slight visual element to be able to easily recognize that item is selected. Maybe double tap to select, to avoid accidently tappnig it idk. When it adds, the item type tag should be the name of the item in OurGroceries, and the Flipp long item name can be the subtitle. Brainstorm more later.
- [ ] What is used to determine the order of the items displayed in each row? What is best?


- update what counts as a weekday fruit, basically it's fruits which can be eaten simply without too much cutting or washing. for example mandarin oranges are weekday fruit, navel oranges are not because they require cutting. pears, apples, kiwi are weekday, but cantelope or pineapple are not.
- ~~improve classification so fewer errors~~ ✓ Done — see review below
- vegetables for meals list easy, like hardy vegetables 
- scrape deals from multiple Optimum accounts, and display them on each eligible item
- be able to click item to open original flyer


- maybe, background color tint shows what store it is, as opposed to text color, so you can tell at a glance, and get used to each store color over time

## Review — LLM Classification Improvement (Mar 04, 2026)

**Problem:** The old two-step pipeline identified a generic food name (e.g. `"beef strips"`) then keyword-matched it against staples/tiers. This threw away 40–70% of valid identifications because the LLM's phrasing didn't contain the exact keyword.

**Fix:** The LLM now receives the full target list (all staple names + all tier items with tier numbers) in the system prompt and returns the exact match name directly. The keyword matching layer is removed entirely.

**Changes made (only `src/llm_classifier.py`):**
- `__init__`: Replaced `staple_keywords`/`tier_keywords` with `staple_avoids`, `tier_avoids`, `tier_tiers` (validation + avoid-filtering only)
- `_build_system_prompt()`: Dynamically builds prompt listing all staples and tier items by name — LLM picks from this list
- `_parse_llm_response()`: Reads `entry["match"]` directly, validates against known names, applies avoid keywords against original item name
- Deleted `_match_food_to_lists()` and `_food_matches_keywords()` (no longer needed)

**Result:** Pipeline ran clean. 67 staple hits, 61 tier items (different week's flyer data — not directly comparable to previous 79/96).

## Review — Names-Only LLM Response (Mar 04, 2026)

**Problem:** Diagnostic revealed 137 LLM entries where the `type` field was wrong (e.g. `"fruit"` instead of `"tier"`), silently dropping 65 valid matches. Root cause: asking the LLM to fill in bookkeeping fields (type/category/tier) it doesn't need to know.

**Fix:** LLM now returns only `{"idx": N, "match": "Name"}`. Code does all lookups via `staple_name_map` and `tier_name_map`. One name can match both a staple and a tier category — the code adds it to both automatically.

**Changes made:**
- `src/llm_classifier.py` — `__init__`: added `staple_name_map` (lowercased → canonical) and `tier_name_map` (lowercased → list of `(category, canonical, tier_num)`) for case-insensitive lookup
- `src/llm_classifier.py` — `_parse_llm_response()`: reads only `match` field, does code-side lookup against both maps, applies avoid-keywords as before
- `src/llm_classifier.py` — `_build_system_prompt()`: simplified response format to `{"idx": N, "match": "Name"}`, added exact-name rule
- `tests/diagnose_llm.py` — `_parse_no_validation()`: updated to use same names-only lookup (no avoid filtering)

**Result:** 79 staple hits (fully recovered to baseline), 89 tier items (up from 61, near 96 baseline — small delta likely due to flyer data changes).