"""
Main pipeline orchestrator (simplified).

Runs the grocery planning process:
1. Load config files
2. Fetch flyer data from Flipp
3. Match items against staples + tier lists (with unit prices)
4. Generate report
"""

import os
import sys
import yaml
import shutil
import logging
import subprocess
from pathlib import Path

from src.flipp_client import FlippClient
from src.item_matcher import ItemMatcher
from src.report_generator import ReportGenerator
from src.models import PipelineResults

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    """Load a YAML config file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_dir: str = "config") -> dict:
    """Load all config files into a single dict."""
    base = Path(config_dir)
    config = {}

    config["settings"] = load_yaml(base / "settings.yaml")
    config["stores"] = load_yaml(base / "stores.yaml").get("stores", {})
    config["preferences"] = load_yaml(base / "preferences.yaml")
    config["tier_lists"] = load_yaml(base / "tier_lists.yaml")

    return config


def setup_logging():
    """Configure logging for the pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def deploy_to_github_pages(html_path: str, repo_path: str, base_dir: Path):
    """Copy the HTML report to the GitHub Pages repo and push."""
    try:
        # Resolve repo path relative to project root
        if not os.path.isabs(repo_path):
            repo_path = str(base_dir / repo_path)

        if not os.path.isdir(repo_path):
            logger.warning(f"Deploy repo not found: {repo_path}. Skipping deploy.")
            return

        dest = os.path.join(repo_path, "index.html")
        shutil.copy2(html_path, dest)

        result = subprocess.run(
            ["git", "add", "index.html"],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.warning(f"git add failed: {result.stderr}")
            return

        # Check if there are changes to commit
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True
        )
        if status.returncode == 0:
            logger.info("No changes to deploy (report unchanged).")
            return

        result = subprocess.run(
            ["git", "commit", "-m", "Update grocery deals"],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.warning(f"git commit failed: {result.stderr}")
            return

        result = subprocess.run(
            ["git", "push"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logger.info("Deployed to GitHub Pages.")
            print("  Published to: https://camerongeisler.github.io/cams-grocery-deals/")
        else:
            logger.warning(f"git push failed: {result.stderr}")

    except Exception as e:
        logger.warning(f"Deploy failed (non-critical): {e}")


def run_pipeline(dry_run: bool = False):
    """Execute the grocery planning pipeline."""
    setup_logging()

    # Resolve paths relative to the script location
    script_dir = Path(__file__).resolve().parent.parent
    config_dir = script_dir / "config"
    data_dir = script_dir / "data"

    logger.info("Loading configuration...")
    try:
        config = load_config(str(config_dir))
    except FileNotFoundError as e:
        print(f"\nError: Config file not found: {e}")
        print("Make sure all config files exist in the 'config' directory.")
        sys.exit(1)

    settings = config["settings"]

    # Check for required settings
    postal_code = settings.get("postal_code", "CHANGE_ME")
    if postal_code == "CHANGE_ME":
        print("\n" + "=" * 60)
        print("  FIRST TIME SETUP NEEDED")
        print("=" * 60)
        print(f"\nPlease edit: {config_dir / 'settings.yaml'}")
        print("  1. Set your postal_code (e.g., 'T2P 1J9')")
        print(f"\nAlso customize: {config_dir / 'preferences.yaml'}")
        print("  - Add/remove items from your staples list")
        print(f"\nAnd customize: {config_dir / 'tier_lists.yaml'}")
        print("  - Edit tier lists for meat, carbs, vegetables, fruit")
        print()
        sys.exit(0)

    results = PipelineResults()

    # --- Step 1: Fetch flyer data ---
    logger.info(f"Fetching flyer deals for postal code {postal_code}...")
    flipp = FlippClient(
        postal_code=postal_code,
        locale=settings.get("locale", "en"),
        cache_dir=str(data_dir),
    )

    try:
        all_store_items = flipp.get_all_deals(config["stores"])
    except Exception as e:
        logger.error(f"Failed to fetch flyer data: {e}")
        results.errors.append(f"Flipp API error: {e}")
        all_store_items = {}

    total_items = sum(len(v) for v in all_store_items.values())
    if total_items == 0:
        results.errors.append(
            "No flyer items found. Check your postal code and internet connection."
        )

    # --- Step 2: Match items against staples + tier lists ---
    logger.info("Matching items against staples and tier lists...")
    ollama_settings = settings.get("ollama", {})
    matching_mode = ollama_settings.get("matching_mode", "auto")
    matcher = ItemMatcher(
        config["preferences"], config["tier_lists"],
        matching_mode=matching_mode, ollama_settings=ollama_settings,
    )
    results = matcher.match_all(all_store_items)

    # --- Step 3: Generate report ---
    reporter = ReportGenerator(tier_lists=config["tier_lists"])

    output_conf = settings.get("output", {})
    html_path = output_conf.get("report_path", "index.html")
    if not os.path.isabs(html_path):
        html_path = str(script_dir / html_path)

    reporter.generate_html_report(results, html_path)

    # --- Step 4: Deploy to GitHub Pages (if configured) ---
    deploy_conf = settings.get("deploy", {})
    pages_repo = deploy_conf.get("github_pages_repo")
    if pages_repo:
        deploy_to_github_pages(html_path, pages_repo, script_dir)

    # Console summary
    staple_count = sum(len(v) for v in results.staples.values())
    tier_count = sum(len(v) for v in results.tier_results.values())
    store_count = len(all_store_items)
    print(f"\nGrocery Planner — {results.run_date.strftime('%B %d, %Y')}")
    print(f"Found {staple_count} staple matches, {tier_count} tier items across {store_count} stores.")
    print(f"Report saved to: {html_path}")

    if results.errors:
        print("\nWarnings:")
        for err in results.errors:
            print(f"  ! {err}")
