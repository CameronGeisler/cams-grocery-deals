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

## New Feature Requests / Bugs
- [ ] **OurGroceries auto-add** — Long-term: checkboxes on each item in report + "Add All" button to push selected items to the correct OurGroceries list. Brainstorm UX later
- [ ] Multipack price bug — /lb calculation uses single pack size instead of total, inflating unit price