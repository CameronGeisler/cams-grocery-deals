"""Tests for price parsing - the trickiest part of the system."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import (
    parse_price, clean_item_name, fuzzy_match, keyword_match,
    calculate_discount_percent, normalize_price_per_lb, format_price,
)


def test_parse_price_plain():
    """Test plain dollar amounts."""
    assert parse_price("$5.99") == (5.99, "each", 1)
    assert parse_price("$12.99") == (12.99, "each", 1)
    assert parse_price("$0.99") == (0.99, "each", 1)


def test_parse_price_per_lb():
    """Test per-pound prices."""
    price, unit, qty = parse_price("$5.99/lb")
    assert price == 5.99
    assert unit == "per_lb"

    price, unit, qty = parse_price("$12.99 per lb")
    assert price == 12.99
    assert unit == "per_lb"


def test_parse_price_per_kg():
    """Test per-kilogram prices."""
    price, unit, qty = parse_price("$13.21/kg")
    assert price == 13.21
    assert unit == "per_kg"


def test_parse_price_multi_buy():
    """Test multi-buy prices like '2 for $5'."""
    price, unit, qty = parse_price("2 for $5.00")
    assert price == 2.50
    assert qty == 2

    price, unit, qty = parse_price("3/$10.00")
    assert abs(price - 3.33) < 0.01
    assert qty == 3


def test_parse_price_each():
    """Test 'each' prices."""
    price, unit, qty = parse_price("$2.49 ea")
    assert price == 2.49

    price, unit, qty = parse_price("$3.99 each")
    assert price == 3.99


def test_parse_price_none():
    """Test unparsable prices."""
    assert parse_price("") == (None, "", 1)
    assert parse_price(None) == (None, "", 1)
    assert parse_price("SAVE") == (None, "", 1)


def test_parse_price_save():
    """Test SAVE $X format - should still extract the price."""
    price, unit, qty = parse_price("SAVE $3.00")
    assert price == 3.0


def test_clean_item_name():
    """Test item name cleaning."""
    assert clean_item_name("PC Free Run Large Eggs, 12 ct") == "free run large eggs,"
    assert "chicken breast" in clean_item_name("Maple Leaf Prime Chicken Breast")
    assert "milk" in clean_item_name("Great Value 2% Milk 4L")


def test_fuzzy_match():
    """Test fuzzy string matching."""
    # Exact substring should always match
    assert fuzzy_match("chicken", "boneless chicken breast") > 0
    assert fuzzy_match("sirloin", "top sirloin steak") > 0

    # Should not match dissimilar strings
    assert fuzzy_match("chicken", "beef tenderloin") == 0

    # Similar strings should match
    assert fuzzy_match("strawberries", "strawberry") > 0


def test_keyword_match():
    """Test keyword matching."""
    cuts = ["top sirloin", "ribeye", "chicken breast"]
    assert keyword_match(cuts, "AAA Top Sirloin Steak") == "top sirloin"
    assert keyword_match(cuts, "Boneless Chicken Breast") == "chicken breast"
    assert keyword_match(cuts, "Pork Chops") is None


def test_calculate_discount():
    """Test discount percentage calculation."""
    assert calculate_discount_percent(5.99, 12.99) > 50
    assert calculate_discount_percent(12.99, 12.99) == 0
    assert calculate_discount_percent(15.00, 12.99) == 0  # Price above regular


def test_normalize_per_lb():
    """Test price normalization to per-lb."""
    # per_lb should pass through
    assert normalize_price_per_lb(5.99, "per_lb") == 5.99

    # per_kg should convert
    result = normalize_price_per_lb(13.21, "per_kg")
    assert result is not None
    assert abs(result - 5.99) < 0.1  # ~$5.99/lb

    # 'each' can't convert
    assert normalize_price_per_lb(5.99, "each") is None


def test_format_price():
    """Test price formatting."""
    assert format_price(5.99, "per_lb") == "$5.99/lb"
    assert format_price(3.49, "each") == "$3.49"
    assert format_price(None) == "Price N/A"


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
