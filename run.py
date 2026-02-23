"""
Grocery Planner - Weekly deal finder.

Run this script once a week (ideally Thursday when new flyers drop).
Results are saved to an HTML report you can view on your phone.

Usage:
    python run.py              # Full run: fetch deals, generate report
    python run.py --dry-run    # Same thing (sync features disabled for now)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import run_pipeline

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_pipeline(dry_run=dry_run)
