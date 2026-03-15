# Grocery Planner — To-Do

## Costco Investigation

Costco IS being fetched from Flipp (~400 items), but very few make it to the report — ~90% of Costco's Flipp flyer is non-grocery (TVs, furniture, clothing, golf equipment). No code bug — data quality issue.

**Sources evaluated (not worth pursuing):**
| Source | Why Not |
|--------|---------|
| costco.ca | Blocks scraping, no public API |
| Costco Insider | Image-based coupon books, needs OCR |
| RedFlagDeals | Unstructured forum posts, YMMV per warehouse |
| Reebee | Same Flipp backend data |

- [ ] **Improve Flipp matching** — Some food items like oatmeal, tortillas, haddock exist in the Costco flyer but aren't matched. Review LLM prompt in `src/llm_classifier.py` to ensure it doesn't over-filter. Small effort.
- [ ] **Evaluate CocoWest.ca scraping** — Active blog covering Western Canada unadvertised Costco deals. Narrative format, behind membership for early access. Medium effort, fragile.
- [ ] **Decide: keep or remove Costco** — If matching improvements don't yield enough value, remove from `config/stores.yaml`.

---

## Classification Fixes (from Mar 9 run)

- [ ] **Fix Salmon: haddock slipping through** — "Royal Harbour haddock fillets" matched as Salmon. Add "haddock" to avoid keywords in `config/tier_lists.yaml` and `config/preferences.yaml`.
- [ ] **Fix Beef Liver false positive** — "WHOLE BEEF BRISKET" matched as T1 Beef Liver. Investigate keywords/avoids for Beef Liver in `config/tier_lists.yaml`.
- [ ] **Fix Chicken Thighs bundle mismatch** — "PC MEATBALLS or CHICKEN WINGS" matched as Chicken Thighs. Consider adding "meatball" to avoid keywords.

---

## Features & Improvements

- [ ] **OurGroceries auto-add** — Checkboxes on each item + "Add All Selected" button to push to OurGroceries list. Button floats at bottom when items selected. Double-tap to select. Item type tag = OurGroceries name, subtitle = full Flipp name.
- [ ] **Click item to open original flyer**
- [ ] **Store color tint** — Background tint per store instead of text color, so you can recognize stores at a glance
- [ ] **Multi-Optimum account deals** — Scrape deals from multiple Optimum accounts and display on each eligible item
- [ ] **Update weekday fruit definition** — Fruits that can be eaten without cutting/washing: mandarin oranges, pears, apples, kiwi = weekday. Navel oranges, cantaloupe, pineapple = not weekday.
- [ ] **Item ordering in report rows** — Investigate what determines order and what's best
