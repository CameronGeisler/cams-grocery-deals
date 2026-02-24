"""
Grocery Planner - Weekly deal finder.

Run this script once a week (ideally Thursday when new flyers drop).
Results are saved to an HTML report you can view on your phone.

Usage:
    python run.py                # Full run: fetch deals, classify, generate report
    python run.py --report-only  # Regenerate report from cached results (instant)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import run_pipeline

if __name__ == "__main__":
    report_only = "--report-only" in sys.argv
    run_pipeline(report_only=report_only)
