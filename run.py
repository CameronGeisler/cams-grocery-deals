"""
Grocery Planner - Weekly deal finder.

Run this script once a week (ideally Thursday when new flyers drop).
Results are saved to an HTML report you can view on your phone.

Usage:
    python run.py                # Full run: fetch deals, classify, generate report
    python run.py --report-only  # Regenerate report from cached results (instant)
    python run.py --fast         # Full run with faster model (qwen2.5:14b, ~3 min)
    python run.py --dump         # Write data/classifications.txt for manual verification
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import run_pipeline

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(PROJECT_ROOT, "data", "results_cache.pkl")
DUMP_PATH = os.path.join(PROJECT_ROOT, "data", "classifications.txt")


def dump_classifications():
    """Load cached results and write a human-readable classifications.txt."""
    if not os.path.exists(CACHE_PATH):
        print("No cache found. Run `python run.py` first.")
        return

    with open(CACHE_PATH, "rb") as f:
        results = pickle.load(f)

    lines = []

    # --- STAPLES ---
    lines.append("=== STAPLES ===")
    for staple_name, ranked_items in results.staples.items():
        if not ranked_items:
            continue
        lines.append(f"\n{staple_name}")
        for ri in ranked_items:
            price = ri.item.price_text or "N/A"
            lines.append(f"  {ri.item.name:<60}  {price:<10}  {ri.item.merchant}")

    # --- TIER ITEMS ---
    lines.append("\n\n=== TIER ITEMS ===")
    for category, ranked_items in results.tier_results.items():
        if not ranked_items:
            continue
        lines.append(f"\n{category.upper()}")
        for ri in ranked_items:
            tier = f"T{ri.tier}" if ri.tier else "  "
            match = ri.matched_tier_item or ""
            price = ri.item.price_text or "N/A"
            lines.append(f"  {tier}  {match:<20}  {ri.item.name:<60}  {price:<10}  {ri.item.merchant}")

    output = "\n".join(lines)
    with open(DUMP_PATH, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Classifications written to: {DUMP_PATH}")
    staple_count = sum(len(v) for v in results.staples.values())
    tier_count = sum(len(v) for v in results.tier_results.values())
    print(f"  {staple_count} staple matches, {tier_count} tier items")


if __name__ == "__main__":
    if "--dump" in sys.argv:
        dump_classifications()
    else:
        report_only = "--report-only" in sys.argv
        fast = "--fast" in sys.argv
        run_pipeline(report_only=report_only, fast=fast)
