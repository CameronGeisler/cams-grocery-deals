# Grocery Planner - To Do

## Completed (2026-02-23)
- [x] Switched LLM from qwen2.5:14b to qwen3:32b (best accuracy, zero hallucinations)
- [x] Simplified LLM to food-recognition only — LLM returns `{idx, food}`, code handles all staple/tier matching
- [x] Removed post-validation entirely — code-side bidirectional keyword matching replaces it
- [x] Reduced batch size from 100 to 25 for better accuracy
- [x] Full pipeline run: 96 staple + 138 tier = 234 total matches from 2,245 items

## Keyword Broadening
These may already be partially resolved by the new bidirectional matching (e.g. LLM says "yogurt" which matches keyword "greek yogurt" because "yogurt" is a substring). Worth verifying on next run.

- [ ] Broaden yogurt keywords in preferences.yaml and tier_lists.yaml (add "yogurt" as keyword)
- [ ] Add "babybel" to Cheese keywords in preferences.yaml
- [ ] Add "lactose free milk" to Milk keywords in preferences.yaml
- [ ] Add "red onion", "red onions" to Onions staple keywords in preferences.yaml
- [ ] Consider adding Basmati Rice as a tier item in tier_lists.yaml

## New Feature Requests / Bugs
- [ ] **Missing quantity/unit info** — Many items show just a price with no quantity (e.g. "Avocados $3.94" from Walmart — per bag? per ea? Same with Maple Leaf bacon, no grams). Two potential fixes:
  - Investigate whether Flipp API returns quantity data we're not capturing
  - Get flyer images from Flipp and display them so the user can see the full listing
- [ ] **LLM speed** — Full run takes ~53 minutes with qwen3:32b, too slow for testing. Explore: disable thinking mode, try smaller model (qwen3:14b), increase batch size, or parallelize requests
- [ ] **Color-code stores** — Make store names color-coded in the HTML report for easier scanning
- [ ] **Dark mode / high contrast** — Current dark mode needs better contrast (accessibility — dad needs to see well)
- [ ] **OurGroceries auto-add** — Long-term: checkboxes on each item in report + "Add All" button to push selected items to the correct OurGroceries list. Brainstorm UX later
