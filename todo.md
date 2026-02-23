# Grocery Planner - To Do

## Keyword Coverage Gaps (found 2026-02-23)

After adding post-validation keyword cross-check, these legitimate items got rejected
because their keywords are too narrow. Consider broadening keywords in config files.

### Yogurt (biggest gap - ~8 items rejected)
- Activia, Oikos, Liberté, iögo, Khaas Halal, Chalo Dahi, Verka Dahi all rejected
- Root cause: Greek Yogurt keywords only match "greek yogurt", "plain greek", "0% greek", "skyr"
- Items like "Liberté Greek 650g yogurt tubs" have "Greek" and "yogurt" but not "greek yogurt" as a contiguous string
- **Fix**: Add broader keywords like "yogurt" to the Yogurt staple, or add specific brand names

### Cheese
- Mini Babybel rejected — it IS cheese but doesn't match "cheddar", "mozzarella", etc.
- **Fix**: Add "babybel" to Cheese keywords

### Milk
- Natrel 2L lactose free rejected — it IS milk but doesn't match "2% milk", "whole milk", etc.
- **Fix**: Add "lactose free" or just "natrel" to Milk keywords

### Rice
- Tilda basmati rice → matched to "Brown Rice" but rejected (basmati ≠ brown rice)
- This is a correct rejection, but consider adding a "Basmati Rice" tier item if wanted

### Romaine Lettuce (LLM mismatch, not keyword issue)
- "Romaine lettuce hearts" exists in tier lists as "Romaine Lettuce" under vegetables
- But LLM matched it to "Chicken Thighs" instead — classic index confusion
- Smaller batch size should help, but this is still a false negative in the final result

### Fewer items in report after validation fix
- Item count dropped from 87 (41 staple + 46 tier) to 37 (21 staple + 16 tier)
- ~26 were confirmed false positives (correct to remove)
- ~24 legitimate items now missing due to narrow keywords + LLM still mismatching some items
- Several staples showing "not on sale" that should have matches: Chicken Thighs, Onions, Tomatoes, Vegetables for Meals
- Root cause: LLM sometimes matches items to the wrong category (e.g., Romaine → Chicken Thighs), validation rejects it, item becomes a false negative
- Broadening keywords is the quickest fix to recover most missing items

## To Do
- [ ] Broaden yogurt keywords in preferences.yaml and tier_lists.yaml (add "yogurt" as keyword)
- [ ] Add "babybel" to Cheese keywords in preferences.yaml
- [ ] Add "lactose free milk" to Milk keywords in preferences.yaml
- [ ] Add "red onion", "red onions" to Onions staple keywords in preferences.yaml
- [ ] Consider adding Basmati Rice as a tier item in tier_lists.yaml
- [ ] Investigate why Chicken Thighs, Tomatoes, Vegetables for Meals show "not on sale"
- [ ] Monitor rejection log each week for new false negatives

## New Feature Requests / Bugs
- [ ] Dark mode needs to be a high contrast theme (for accessibility — dad needs to see well)
- [ ] Add pictures of grocery items to the report — investigate if images are retrievable from Flipp API or another source
- [ ] Investigate why many items have no weight or quantity info — find root cause and fix
