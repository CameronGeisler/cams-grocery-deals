"""Tests for item matching logic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import FlyerItem
from src.item_matcher import ItemMatcher


def make_item(name, price=None, merchant="Test Store"):
    return FlyerItem(
        name=name, price=price, price_text=f"${price}" if price else "",
        unit="each", merchant=merchant, flyer_id="test"
    )


PREFERENCES = {
    "repeat_list": {
        "dairy": [
            {"name": "2% Milk", "variants": ["2% milk", "partly skimmed milk"], "max_good_price": 5.99},
            {"name": "Large Eggs", "variants": ["large eggs", "free run eggs"], "max_good_price": 4.49},
        ]
    },
    "meat_preferences": {
        "preferred_cuts": ["top sirloin", "chicken breast", "strip loin"],
        "avoid_keywords": ["processed", "deli", "breaded", "nugget", "strip", "patties"],
        "override_phrases": ["strip loin", "striploin"],
    },
    "produce_preferences": {
        "fruits": ["strawberries", "blueberries", "bananas"],
        "vegetables": ["broccoli", "bell pepper", "spinach"],
    },
}


def test_match_repeat_list():
    """Test repeat list matching."""
    matcher = ItemMatcher(PREFERENCES)
    items = [
        make_item("2% Milk 4L", 4.99, "Superstore"),
        make_item("Partly Skimmed Milk 4L", 4.49, "No Frills"),
        make_item("Chocolate Milk 1L", 2.99, "Superstore"),
        make_item("Large Eggs Dozen", 3.99, "Superstore"),
    ]

    all_store_items = {"store1": items}
    results = matcher.match_all(all_store_items)

    # Should find milk matches
    assert "2% Milk" in results["repeat_list"]
    milk_matches = results["repeat_list"]["2% Milk"]
    assert len(milk_matches) >= 2  # Both 2% Milk and Partly Skimmed

    # Cheapest should be first (matches are (FlyerItem, pref_name) tuples)
    if len(milk_matches) > 1:
        assert milk_matches[0][0].price <= milk_matches[1][0].price

    # Should find egg matches
    assert "Large Eggs" in results["repeat_list"]
    assert len(results["repeat_list"]["Large Eggs"]) >= 1


def test_match_meats_preferred():
    """Test meat matching - preferred cuts."""
    matcher = ItemMatcher(PREFERENCES)
    items = [
        make_item("AAA Top Sirloin Steak", 8.99),
        make_item("Boneless Chicken Breast", 4.99),
        make_item("Breaded Chicken Strips", 6.99),  # Should be avoided
        make_item("Deli Ham Sliced", 3.99),  # Should be avoided
    ]

    all_store_items = {"store1": items}
    results = matcher.match_all(all_store_items)

    meat_names = [item.name for item, _ in results["meats"]]
    assert "AAA Top Sirloin Steak" in meat_names
    assert "Boneless Chicken Breast" in meat_names
    assert "Breaded Chicken Strips" not in meat_names
    assert "Deli Ham Sliced" not in meat_names


def test_match_meats_override():
    """Test that override phrases prevent false avoidance."""
    matcher = ItemMatcher(PREFERENCES)
    items = [
        make_item("Beef Strip Loin Steak", 12.99),  # "strip" is in avoid, but "strip loin" is override
        make_item("Chicken Strips Breaded", 6.99),   # "strip" + "breaded" -> should be avoided
    ]

    all_store_items = {"store1": items}
    results = matcher.match_all(all_store_items)

    meat_names = [item.name for item, _ in results["meats"]]
    assert "Beef Strip Loin Steak" in meat_names
    assert "Chicken Strips Breaded" not in meat_names


def test_match_produce():
    """Test produce matching."""
    matcher = ItemMatcher(PREFERENCES)
    items = [
        make_item("Fresh Strawberries 1lb", 2.99),
        make_item("Frozen Strawberries 600g", 3.99),  # Frozen should be excluded
        make_item("Broccoli Crowns", 1.99),
        make_item("Strawberry Jam", 3.49),  # Jam should be excluded
    ]

    all_store_items = {"store1": items}
    results = matcher.match_all(all_store_items)

    fruit_names = [item.name for item, _ in results["produce_fruit"]]
    assert "Fresh Strawberries 1lb" in fruit_names
    assert "Frozen Strawberries 600g" not in fruit_names
    assert "Strawberry Jam" not in fruit_names

    veg_names = [item.name for item, _ in results["produce_veg"]]
    assert "Broccoli Crowns" in veg_names


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__} - {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test.__name__} - {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
