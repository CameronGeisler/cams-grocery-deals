"""Tests for deal scoring logic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import FlyerItem, DealRating
from src.deal_scorer import DealScorer


PRICE_THRESHOLDS = {
    "meats": {
        "top_sirloin": {
            "keywords": ["top sirloin"],
            "regular_price": 14.99,
            "good_price": 8.99,
            "great_price": 6.99,
        },
        "chicken_breast": {
            "keywords": ["chicken breast"],
            "regular_price": 7.49,
            "good_price": 4.99,
            "great_price": 3.49,
        },
    },
    "produce": {
        "strawberries": {
            "keywords": ["strawberries"],
            "regular_price": 4.99,
            "good_price": 2.99,
            "great_price": 1.99,
        },
    },
    "generic": {
        "minimum_discount_percent": 20,
        "good_deal_percent": 30,
        "great_deal_percent": 45,
    },
}

STORES = {
    "superstore": {
        "display_name": "Superstore",
        "flipp_merchant_names": ["Superstore"],
        "loyalty_program": "PC Optimum",
        "loyalty_earn_rate": 0.015,
    },
}


def make_item(name, price, merchant="Superstore", unit="per_lb"):
    return FlyerItem(
        name=name, price=price, price_text=f"${price}/lb",
        unit=unit, merchant=merchant, flyer_id="test"
    )


def test_exceptional_meat_deal():
    """A top sirloin at $5.99/lb when regular is $14.99 should be exceptional."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    item = make_item("AAA Top Sirloin Steak", 5.99)
    deal = scorer.score_deal(item, "meat", "top sirloin")

    assert deal.rating in (DealRating.EXCEPTIONAL, DealRating.GREAT)
    assert deal.score >= 40
    assert deal.discount_percent is not None
    assert deal.discount_percent > 50


def test_good_meat_deal():
    """A top sirloin at $8.99/lb should be a good deal."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    item = make_item("Top Sirloin Steak", 8.99)
    deal = scorer.score_deal(item, "meat", "top sirloin")

    assert deal.rating in (DealRating.GOOD, DealRating.GREAT)
    assert deal.score >= 25


def test_not_a_deal():
    """A top sirloin at regular price should not be flagged."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    item = make_item("Top Sirloin Steak", 14.99)
    deal = scorer.score_deal(item, "meat", "top sirloin")

    assert deal.rating in (DealRating.NOT_A_DEAL, DealRating.OKAY)
    assert deal.score < 30


def test_quality_bonus():
    """Grass-fed should get quality bonus points."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    regular = make_item("Top Sirloin Steak", 7.99)
    grassfed = make_item("Grass-Fed Top Sirloin Steak", 7.99)

    deal_regular = scorer.score_deal(regular, "meat", "top sirloin")
    deal_grassfed = scorer.score_deal(grassfed, "meat", "top sirloin")

    assert deal_grassfed.score > deal_regular.score


def test_produce_scoring():
    """Test produce deal scoring."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    item = make_item("Fresh Strawberries 1lb", 1.99, unit="each")
    deal = scorer.score_deal(item, "produce_fruit", "strawberries")

    assert deal.rating in (DealRating.GREAT, DealRating.EXCEPTIONAL)
    assert deal.discount_percent is not None


def test_loyalty_bonus():
    """Items from stores with loyalty programs should get bonus points."""
    scorer = DealScorer(PRICE_THRESHOLDS, STORES)
    item_loyalty = make_item("Chicken Breast", 4.99, "Superstore")
    item_no_loyalty = make_item("Chicken Breast", 4.99, "Unknown Store")

    deal_loyalty = scorer.score_deal(item_loyalty, "meat", "chicken breast")
    deal_no_loyalty = scorer.score_deal(item_no_loyalty, "meat", "chicken breast")

    assert deal_loyalty.score >= deal_no_loyalty.score


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
