"""Data classes shared across all modules."""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


@dataclass
class FlyerItem:
    name: str
    price: Optional[float]
    price_text: str
    unit: str
    merchant: str
    flyer_id: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    category: str = ""
    image_url: str = ""
    raw_data: dict = field(default_factory=dict)


@dataclass
class UnitPrice:
    price_per_kg: Optional[float] = None
    price_per_lb: Optional[float] = None
    price_per_unit: Optional[float] = None
    price_per_item: Optional[float] = None      # per-item price for countable items (e.g., $0.80/avocado)
    item_count: Optional[int] = None             # number of items in package (e.g., 5)
    count_label: Optional[str] = None            # display label (e.g., "5-6 pk")
    display_weight: Optional[str] = None
    display_str: str = "Price N/A"


@dataclass
class RankedItem:
    item: FlyerItem
    category: str                          # "meat", "carbs", "vegetables", "fruit", "dairy", "other"
    unit_price: UnitPrice
    matched_staple: Optional[str] = None   # staple name if matched
    matched_tier_item: Optional[str] = None  # tier entry name if matched
    tier: Optional[int] = None             # 1, 2, 3 or None

    @property
    def sort_key(self) -> tuple:
        tier_val = self.tier if self.tier is not None else 999
        price_val = (
            self.unit_price.price_per_kg
            or self.unit_price.price_per_lb
            or self.unit_price.price_per_unit
            or 999.0
        )
        return (tier_val, price_val)

    @property
    def store(self) -> str:
        return self.item.merchant

    @property
    def name(self) -> str:
        return self.item.name

    @property
    def price_text(self) -> str:
        return self.item.price_text

    @property
    def is_staple(self) -> bool:
        return self.matched_staple is not None

    @property
    def is_tiered(self) -> bool:
        return self.tier is not None


@dataclass
class PipelineResults:
    staples: dict = field(default_factory=dict)        # staple_name -> [RankedItem]
    tier_results: dict = field(default_factory=dict)   # category -> [RankedItem]
    run_date: date = field(default_factory=date.today)
    errors: list = field(default_factory=list)
