"""Price parsing, unit normalization, and text matching utilities."""

import re
from difflib import SequenceMatcher
from typing import Optional, Tuple


# --- Price Parsing ---

def parse_price(price_text: str) -> Tuple[Optional[float], str, int]:
    """
    Extract numeric price from flyer price text.

    Returns (price_per_unit, unit, quantity).
    unit is one of: "each", "per_lb", "per_kg", "per_100g", "per_item"
    quantity is how many you get (for "2 for $5" -> quantity=2, price=2.50)

    Returns (None, "", 1) if unparsable.
    """
    if not price_text:
        return None, "", 1

    text = price_text.strip().lower()

    # Remove common noise
    text = text.replace(",", "").replace("\n", " ").replace("\r", " ")

    # Pattern: "X for $Y.YY" or "X/$Y.YY"
    multi_match = re.search(r'(\d+)\s*(?:for|/)\s*\$(\d+\.?\d*)', text)
    if multi_match:
        qty = int(multi_match.group(1))
        total = float(multi_match.group(2))
        if qty > 0:
            return round(total / qty, 2), "each", qty

    # Pattern: "$X.XX/lb" or "$X.XX per lb"
    lb_match = re.search(r'\$(\d+\.?\d*)\s*(?:/|per)\s*lb', text)
    if lb_match:
        return float(lb_match.group(1)), "per_lb", 1

    # Pattern: "$X.XX/kg" or "$X.XX per kg"
    kg_match = re.search(r'\$(\d+\.?\d*)\s*(?:/|per)\s*kg', text)
    if kg_match:
        return float(kg_match.group(1)), "per_kg", 1

    # Pattern: "$X.XX/100g" or "$X.XX per 100g" or "$X.XX/100 g"
    g100_match = re.search(r'\$(\d+\.?\d*)\s*(?:/|per)\s*100\s*g', text)
    if g100_match:
        return float(g100_match.group(1)), "per_100g", 1

    # Pattern: "$X.XX ea" or "$X.XX each"
    ea_match = re.search(r'\$(\d+\.?\d*)\s*(?:ea\.?|each)', text)
    if ea_match:
        return float(ea_match.group(1)), "each", 1

    # Pattern: plain "$X.XX" (most common)
    plain_match = re.search(r'\$(\d+\.?\d*)', text)
    if plain_match:
        return float(plain_match.group(1)), "each", 1

    # Pattern: "X.XX" without dollar sign
    bare_match = re.search(r'(\d+\.\d{2})\b', text)
    if bare_match:
        return float(bare_match.group(1)), "each", 1

    return None, "", 1


def parse_discount_from_text(price_text: str) -> Optional[float]:
    """
    Try to extract a discount percentage or save amount from text.
    e.g., "SAVE $3.00", "50% off", "save 30%"

    Returns the discount as a dollar amount if found, None otherwise.
    """
    if not price_text:
        return None

    text = price_text.strip().lower()

    # "save $X.XX" or "save $X"
    save_match = re.search(r'save\s*\$(\d+\.?\d*)', text)
    if save_match:
        return float(save_match.group(1))

    # "X% off"
    pct_match = re.search(r'(\d+)\s*%\s*off', text)
    if pct_match:
        return None  # Can't convert % to $ without knowing original price

    return None


def normalize_price_per_lb(price: float, unit: str) -> Optional[float]:
    """Convert any price/unit to per-lb for comparison. Returns None if not convertible."""
    if unit == "per_lb":
        return price
    if unit == "per_kg":
        return round(price / 2.20462, 2)
    if unit == "per_100g":
        return round(price * 10 / 2.20462, 2)  # 1kg = 10 * 100g
    return None  # "each" items can't be converted to per_lb


# --- Text Matching ---

def clean_item_name(name: str) -> str:
    """
    Normalize item name for matching.
    Strips brand names, sizes, store-specific prefixes.
    """
    if not name:
        return ""

    text = name.lower().strip()

    # Remove common brand/store prefixes
    prefixes_to_strip = [
        r"pc\s+",
        r"president'?s?\s+choice\s+",
        r"no\s+name\s+",
        r"great\s+value\s+",
        r"our\s+finest\s+",
        r"compliments\s+",
        r"selection\s+",
        r"irresistibles\s+",
        r"maple\s+leaf\s+",
        r"schneiders?\s+",
        r"lilydale\s+",
        r"prime\s+",  # "Prime chicken breast" -> "chicken breast"
    ]
    for prefix in prefixes_to_strip:
        text = re.sub(r'^' + prefix, '', text)

    # Remove size/weight info
    text = re.sub(r'\d+\s*(?:g|kg|ml|l|lb|oz|ct|pk|pack)\b', '', text)
    text = re.sub(r'\d+\s*x\s*\d+', '', text)  # "6 x 100g"

    # Remove trailing punctuation and extra spaces
    text = re.sub(r'[,.\-/]+$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def fuzzy_match(query: str, candidate: str, threshold: float = 0.65) -> float:
    """
    Fuzzy string matching using SequenceMatcher (stdlib).
    Returns similarity ratio (0.0 to 1.0). Returns 0.0 if below threshold.
    """
    if not query or not candidate:
        return 0.0

    q = query.lower().strip()
    c = candidate.lower().strip()

    # Exact substring match is always a hit
    if q in c or c in q:
        return 1.0

    ratio = SequenceMatcher(None, q, c).ratio()
    return ratio if ratio >= threshold else 0.0


def keyword_match(keywords: list, text: str) -> Optional[str]:
    """
    Check if any keyword appears in text. Returns the matched keyword or None.
    Case-insensitive.
    """
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return kw
    return None


def negative_keyword_match(avoid_keywords: list, text: str) -> Optional[str]:
    """Check if any avoid-keyword appears in text. Returns matched keyword or None."""
    return keyword_match(avoid_keywords, text)


def format_price(price: Optional[float], unit: str = "each") -> str:
    """Format a price for display."""
    if price is None:
        return "Price N/A"
    if unit == "per_lb":
        return f"${price:.2f}/lb"
    if unit == "per_kg":
        return f"${price:.2f}/kg"
    if unit == "per_100g":
        return f"${price:.2f}/100g"
    return f"${price:.2f}"


def calculate_discount_percent(sale_price: float, regular_price: float) -> float:
    """Calculate discount percentage. Returns 0-100."""
    if regular_price <= 0 or sale_price <= 0:
        return 0.0
    if sale_price >= regular_price:
        return 0.0
    return round((1 - sale_price / regular_price) * 100, 1)


# --- Unit Price ---

def extract_weight_from_text(text: str) -> Optional[Tuple[float, str]]:
    """
    Extract package weight from item name + description text.

    Returns (numeric_value, unit_str) where unit_str is one of "g", "kg", "lb", "oz".
    Returns None if no weight found.
    """
    if not text:
        return None

    text = text.lower()

    # Skip weight patterns that are part of price info (e.g. "$3.99/kg")
    # We want package weights like "500g", "1.5kg", not price-per-weight units
    # Strategy: find all weight patterns, reject ones preceded by $ or /

    patterns = [
        # kg: "1.5kg", "2 kg"
        (r'(?<!\$)(?<!/)(\d+\.?\d*)\s*kg\b', "kg"),
        # grams: "500g", "100 g" — but NOT "g" in words like "garlic", "green", "grapes"
        (r'(?<!\$)(?<!/)(\d+\.?\d*)\s*g(?![a-z])', "g"),
        # lb: "2lb", "1.5 lb"
        (r'(?<!\$)(?<!/)(\d+\.?\d*)\s*lb\b', "lb"),
        # oz: "16oz", "12 oz"
        (r'(?<!\$)(?<!/)(\d+\.?\d*)\s*oz\b', "oz"),
    ]

    for pattern, unit in patterns:
        match = re.search(pattern, text)
        if match:
            value = float(match.group(1))
            if value <= 0:
                continue

            # Check for multipack prefix: "6 x 100g" -> 600g
            multipack = re.search(r'(\d+)\s*[xX×]\s*' + re.escape(match.group(0).strip()), text)
            if multipack:
                value *= int(multipack.group(1))

            return (value, unit)

    return None


# --- Count Extraction ---

TEXT_NUMBER_MAP = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "eighteen": 18, "twenty": 20,
    "twenty-four": 24, "twenty four": 24, "thirty": 30,
}


def _text_to_number(text: str) -> Optional[int]:
    """Convert text number words to int. Returns None if not a number word."""
    return TEXT_NUMBER_MAP.get(text.lower().strip())


def extract_count_from_text(text: str) -> Optional[Tuple[int, str]]:
    """
    Extract item count from item name or description text.

    Looks for patterns like:
      - "PKG OF 5 OR 6"    -> (5, "5-6 pk")
      - "BAG OF 6"         -> (6, "6 pk")
      - "PACK OF 8"        -> (8, "8 pk")
      - "package of five"  -> (5, "5 pk")
      - "12 pk"            -> (12, "12 pk")
      - "6 ct"             -> (6, "6 ct")

    For ranges (5 OR 6), returns the lower number (conservative estimate).

    Returns (count, display_label) or None.
    """
    if not text:
        return None

    text_lower = text.lower()

    # Build pattern for text numbers
    text_num_pattern = "|".join(re.escape(k) for k in TEXT_NUMBER_MAP.keys())

    # Pattern 1: "pkg/pack/package/bag/box/case/bundle of N or N" (range)
    range_match = re.search(
        r'(?:pkg|pack(?:age)?|bag|box|case|bundle|pouch)\s+of\s+'
        r'(\d+|' + text_num_pattern + r')'
        r'\s+(?:or|to|-)\s+'
        r'(\d+|' + text_num_pattern + r')',
        text_lower
    )
    if range_match:
        low_raw, high_raw = range_match.group(1), range_match.group(2)
        low = int(low_raw) if low_raw.isdigit() else _text_to_number(low_raw)
        high = int(high_raw) if high_raw.isdigit() else _text_to_number(high_raw)
        if low and high and low > 0:
            count = min(low, high)
            return (count, f"{min(low, high)}-{max(low, high)} pk")
        elif low and low > 0:
            return (low, f"{low} pk")

    # Pattern 2: "pkg/pack/package/bag/box/case/bundle of N"
    count_match = re.search(
        r'(?:pkg|pack(?:age)?|bag|box|case|bundle|pouch)\s+of\s+'
        r'(\d+|' + text_num_pattern + r')',
        text_lower
    )
    if count_match:
        raw = count_match.group(1)
        count = int(raw) if raw.isdigit() else _text_to_number(raw)
        if count and count > 0:
            return (count, f"{count} pk")

    # Pattern 3: "N pk", "N ct", "N count", "N pack"
    pk_match = re.search(r'(\d+)\s*(?:pk|ct|count|pack)\b', text_lower)
    if pk_match:
        count = int(pk_match.group(1))
        if 1 < count <= 100:
            return (count, f"{count} pk")

    return None


def compute_unit_price(item) -> 'UnitPrice':
    """
    Compute unit prices for a FlyerItem.

    Returns a UnitPrice with price_per_kg, price_per_lb, price_per_unit, and a display string.
    Shows both weight-based and per-unit prices when possible.
    """
    from src.models import UnitPrice

    if item.price is None:
        return UnitPrice()

    price_per_kg = None
    price_per_lb = None
    price_per_unit = item.price
    price_per_item = None
    item_count = None
    count_label = None
    display_weight = None

    # Case 1: price text already encodes a weight unit (e.g. "$9.99/kg")
    if item.unit == "per_kg":
        price_per_kg = item.price
        price_per_lb = round(item.price / 2.20462, 2)
    elif item.unit == "per_lb":
        price_per_lb = item.price
        price_per_kg = round(item.price * 2.20462, 2)
    elif item.unit == "per_100g":
        price_per_kg = round(item.price * 10, 2)
        price_per_lb = round(price_per_kg / 2.20462, 2)
    else:
        # Case 2: try to extract weight from item name + description
        description = item.raw_data.get("description", "") if item.raw_data else ""
        pre_price = item.raw_data.get("pre_price_text", "") if item.raw_data else ""
        combined_text = f"{item.name} {description} {pre_price}"
        weight_info = extract_weight_from_text(combined_text)

        if weight_info:
            value, unit = weight_info
            # Convert to kg
            conversions = {"kg": 1.0, "g": 0.001, "lb": 0.453592, "oz": 0.0283495}
            weight_kg = value * conversions[unit]

            if weight_kg > 0:
                price_per_kg = round(item.price / weight_kg, 2)
                price_per_lb = round(price_per_kg / 2.20462, 2)
                display_weight = f"{value:g}{unit}"
        else:
            # Case 3: try to extract count for countable items (pkg of 6, etc.)
            count_info = extract_count_from_text(combined_text)
            if count_info:
                item_count, count_label = count_info
                price_per_item = round(item.price / item_count, 2)

    # Build display string
    parts = []
    if price_per_kg is not None:
        parts.append(f"${price_per_kg:.2f}/kg (${price_per_lb:.2f}/lb)")
    if price_per_item is not None:
        parts.append(f"${price_per_item:.2f}/ea")
    if price_per_unit is not None and price_per_kg is not None and item.unit not in ("per_kg", "per_lb", "per_100g"):
        # Show both weight price and package price
        parts.append(f"${price_per_unit:.2f}/pkg")
    elif price_per_unit is not None and price_per_kg is None and price_per_item is None:
        parts.append(f"${price_per_unit:.2f}/unit")

    display_str = " · ".join(parts) if parts else "Price N/A"

    return UnitPrice(
        price_per_kg=price_per_kg,
        price_per_lb=price_per_lb,
        price_per_unit=price_per_unit,
        price_per_item=price_per_item,
        item_count=item_count,
        count_label=count_label,
        display_weight=display_weight,
        display_str=display_str,
    )
