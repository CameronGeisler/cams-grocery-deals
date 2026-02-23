# Grocery Planner

Automates the weekly "scan all the flyers" process and turns it into an actionable shopping plan.

## What It Does

Every week, grocery stores publish flyers with discounted items. Finding the best deals across multiple stores, matching them to what you actually want to buy, and building a meal plan around what's on sale is time-consuming. Grocery Planner does all of this automatically.

It fetches current flyer data, scores every deal against your preferences and price history, suggests meals based on what's on sale, identifies items worth price-matching at your primary store, and syncs everything directly to your OurGroceries shopping list.

## How It Works

```
Flipp API → Item Matcher → Deal Scorer → Price Tracker
                                              ↓
                           Price Match Optimizer → Meal Planner
                                              ↓
                           Report Generator + OurGroceries Sync
```

1. **Fetch** — Pulls the current week's flyers from Flipp for your postal code (no API key required)
2. **Match** — Filters items against your preferences: specific meat cuts, produce, and recurring staples
3. **Score** — Rates each deal 0–100 based on discount size, historical price, quality keywords, and loyalty points value
4. **Track** — Stores prices in a local SQLite database to detect genuine historical lows
5. **Optimize** — Picks the top competitor deals worth price-matching at your primary store
6. **Plan** — Suggests meals based on proteins and vegetables currently on sale
7. **Report** — Outputs a scannable console summary and a styled HTML report
8. **Sync** — Pushes store-specific shopping lists into the OurGroceries app

## Key Features

- Covers multiple stores: Superstore, Shoppers Drug Mart, No Frills, FreshCo, Walmart, Costco
- Deal ratings: NOT A DEAL → OKAY → GOOD → GREAT → EXCEPTIONAL
- Historical price tracking — knows when a price is actually a low
- Quality-aware scoring (e.g. AAA beef, grass-fed, organic score higher)
- Meal planning from templates, with protein variety enforcement
- Price match strategy limited to your configured top N items
- Auto-syncs to OurGroceries, cleaning up previous week's entries
- Fully configuration-driven — no code changes needed to customize behavior

## Quick Start

```bash
# Windows
run.bat

# Or directly
python run.py
```

Options:
```bash
python run.py --no-sync       # Skip OurGroceries sync
python run.py --no-html       # Skip HTML report
python run.py --force-fetch   # Ignore cached flyer data
python run.py --debug         # Verbose output
```

## Configuration

All customization is done via YAML files in `config/`:

| File | Purpose |
|------|---------|
| `settings.yaml` | Postal code, OurGroceries login, output options, primary store |
| `stores.yaml` | Which stores to check and their Flipp identifiers |
| `preferences.yaml` | Your repeat-buy items, preferred meat cuts, produce list |
| `price_thresholds.yaml` | Reference prices used for deal scoring |
| `meal_templates.yaml` | Meal recipes that drive the meal planner |

## Dependencies

```
requests       - HTTP calls to Flipp API
ourgroceries   - OurGroceries app integration
pyyaml         - Config file parsing
aiohttp        - Async HTTP for OurGroceries sync
```

Install with:
```bash
pip install -r requirements.txt
```
