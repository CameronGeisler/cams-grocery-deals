"""
Report generator: mobile-first HTML report (primary) and console summary.

The HTML report is designed for phone viewing — collapsible sections,
large touch targets, readable fonts, self-contained (no external CSS/JS).
"""

import os
import html
import logging
from collections import OrderedDict
from datetime import date, datetime
from src.models import PipelineResults, RankedItem

logger = logging.getLogger(__name__)


class ReportGenerator:
    STORE_COLORS = {
        "Real Canadian Superstore": "#f57c00",
        "No Frills": "#ffeb3b",
        "FreshCo": "#66bb6a",
        "Walmart": "#42a5f5",
        "Shoppers Drug Mart": "#ef5350",
        "Costco": "#ab47bc",
    }

    def __init__(self, tier_lists: dict = None):
        # Extract tier labels from config for display
        self.tier_labels = {}
        if tier_lists:
            for category, tiers in tier_lists.items():
                for tier_group in (tiers or []):
                    tier_num = tier_group.get("tier", 1)
                    label = tier_group.get("label", f"Tier {tier_num}")
                    self.tier_labels[(category, tier_num)] = label

    def generate_html_report(self, results: PipelineResults, output_path: str):
        """Generate a mobile-first HTML report file."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        parts = []
        parts.append(self._html_header(results.run_date))

        # Staples section (open by default)
        parts.append(self._staples_section(results))

        # Tier list sections (collapsed by default)
        for category, label in [("meat", "Meat"), ("carbs", "Carbs"), ("vegetables", "Vegetables"), ("fruit", "Fruit")]:
            items = results.tier_results.get(category, [])
            tier_groups = self._get_tier_groups(category, results)
            parts.append(self._tier_section(label, category, items, tier_groups))

        # Errors
        if results.errors:
            parts.append('<details><summary>Warnings</summary>')
            for err in results.errors:
                parts.append(f'<div class="item"><div class="not-on-sale">{html.escape(str(err))}</div></div>')
            parts.append('</details>')

        parts.append(self._html_footer())

        html_content = "\n".join(parts)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"HTML report saved to {output_path}")

    def _get_tier_groups(self, category: str, results: PipelineResults) -> dict:
        """Get tier labels from the tier_results data."""
        groups = {}
        for item in results.tier_results.get(category, []):
            tier = item.tier or 0
            if tier not in groups:
                groups[tier] = []
            groups[tier].append(item)
        return groups

    def _deal_card(self, ri: RankedItem, show_staple_badge: bool = True) -> str:
        """Render a single deal card for a RankedItem."""
        parts = ['<div class="deal-card">']

        # Product image from flyer (if available)
        if ri.item.image_url:
            img_url = html.escape(ri.item.image_url)
            parts.append(f'<img class="card-img" src="{img_url}" alt="" loading="lazy">')

        # Product name (full flyer item name — includes brand and size)
        product_name = html.escape(ri.name)
        parts.append(f'<div class="card-product">{product_name}</div>')

        # Package price (prominent) + weight/count badges
        price_display = html.escape(ri.item.price_text) if ri.item.price_text else "Price N/A"
        weight_badge = ""
        if ri.unit_price.display_weight:
            weight_badge = f' <span class="card-weight">{html.escape(ri.unit_price.display_weight)}</span>'
        count_badge = ""
        if ri.unit_price.count_label:
            count_badge = f' <span class="card-count">{html.escape(ri.unit_price.count_label)}</span>'
        parts.append(f'<div class="card-price">{price_display}{weight_badge}{count_badge}</div>')

        # Unit price (smaller, for comparison)
        unit_parts = []
        if ri.unit_price.price_per_kg is not None:
            unit_parts.append(f"${ri.unit_price.price_per_kg:.2f}/kg")
        if ri.unit_price.price_per_lb is not None:
            unit_parts.append(f"${ri.unit_price.price_per_lb:.2f}/lb")
        if ri.unit_price.price_per_item is not None:
            unit_parts.append(f"${ri.unit_price.price_per_item:.2f}/ea")
        if unit_parts:
            unit_str = " &middot; ".join(unit_parts)
            parts.append(f'<div class="card-unit-price">{unit_str}</div>')

        # Store name (color-coded)
        store_html = html.escape(ri.store)
        store_color = self.STORE_COLORS.get(ri.store, "#999")
        if show_staple_badge and ri.is_staple:
            store_html += ' <span class="staple-badge">staple</span>'
        parts.append(f'<div class="card-store" style="color:{store_color}">{store_html}</div>')

        parts.append('</div>')
        return "\n".join(parts)

    def _staples_section(self, results: PipelineResults) -> str:
        """Build the Weekly Staples section HTML with horizontal deal cards."""
        parts = ['<details open>', '<summary>Weekly Staples</summary>']

        for staple_name, matches in results.staples.items():
            if not matches:
                parts.append(
                    f'<div class="item">'
                    f'<div class="item-name not-on-sale">{html.escape(staple_name)} &mdash; not on sale this week</div>'
                    f'</div>'
                )
                continue

            parts.append('<div class="item-group">')
            parts.append(f'<div class="item-group-name">{html.escape(staple_name)}</div>')

            parts.append('<div class="card-row">')
            for ri in matches:
                parts.append(self._deal_card(ri, show_staple_badge=False))
            parts.append('</div>')

            parts.append('</div>')

        parts.append('</details>')
        return "\n".join(parts)

    def _tier_section(self, label: str, category: str, items: list, tier_groups: dict) -> str:
        """Build a tier list category section HTML with grouped horizontal cards."""
        parts = [f'<details>', f'<summary>{html.escape(label)}</summary>']

        if not items:
            parts.append('<div class="item"><div class="not-on-sale">Nothing on sale this week</div></div>')
            parts.append('</details>')
            return "\n".join(parts)

        for tier_num in (1, 2, 3, 4):
            tier_items = tier_groups.get(tier_num, [])

            # Skip empty tiers entirely
            if not tier_items:
                continue

            # Tier subheading with label from config
            tier_label = self.tier_labels.get((category, tier_num), f"Tier {tier_num}")
            parts.append(f'<div class="tier-header">{html.escape(tier_label)}</div>')

            # Group items by matched_tier_item, preserving first-seen order
            grouped = OrderedDict()
            for ri in tier_items:
                key = ri.matched_tier_item or ri.name
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(ri)

            for group_name, group_items in grouped.items():
                parts.append('<div class="item-group">')
                parts.append(f'<div class="item-group-name">{html.escape(group_name)}</div>')

                parts.append('<div class="card-row">')
                for ri in group_items:
                    parts.append(self._deal_card(ri))
                parts.append('</div>')

                parts.append('</div>')

        parts.append('</details>')
        return "\n".join(parts)

    def _html_header(self, run_date: date) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cam's Grocery Deals</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 12px; background: #121212;
    color: #e0e0e0; font-size: 16px; line-height: 1.4;
    -webkit-text-size-adjust: 100%;
  }}
  h1 {{ font-size: 1.3rem; text-align: center; margin: 8px 0 4px; color: #f0f0f0; }}
  .date {{ text-align: center; color: #b0b0b0; margin-bottom: 16px; font-size: 0.9rem; }}

  /* Collapsible sections */
  details {{
    background: #1e1e1e; border-radius: 10px; margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    overflow: hidden;
  }}
  summary {{
    padding: 14px 16px; font-weight: 600; font-size: 1.1rem;
    cursor: pointer; list-style: none; color: #f0f0f0;
    display: flex; justify-content: space-between; align-items: center;
    -webkit-tap-highlight-color: rgba(255,255,255,0.05);
    user-select: none;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::after {{ content: "\\25B8"; font-size: 0.9rem; color: #999; transition: transform 0.15s; }}
  details[open] summary::after {{ transform: rotate(90deg); }}

  /* Legacy items (not-on-sale, warnings) */
  .item {{ padding: 10px 16px; border-top: 1px solid #2a2a2a; }}
  .item-name {{ font-weight: 600; font-size: 0.95rem; }}
  .not-on-sale {{ color: #999; font-style: italic; }}

  /* Tier subheadings */
  .tier-header {{
    padding: 8px 16px; font-size: 0.85rem; color: #c0c0c0;
    text-transform: uppercase; letter-spacing: 0.03em;
    border-top: 1px solid #2a2a2a; background: #181818;
    font-weight: 600;
  }}

  /* Staple badge */
  .staple-badge {{
    background: #1b3a1b; color: #66bb6a;
    padding: 1px 6px; border-radius: 4px;
    font-size: 0.75rem; font-weight: 500;
    vertical-align: middle;
  }}

  /* ---- Grouped items with card scroll ---- */
  .item-group {{
    padding: 8px 16px 12px;
    border-top: 1px solid #2a2a2a;
  }}
  .item-group-name {{
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 6px;
    color: #e0e0e0;
  }}
  .card-row {{
    display: flex;
    overflow-x: auto;
    gap: 10px;
    padding-bottom: 4px;
    -webkit-overflow-scrolling: touch;
    scroll-snap-type: x proximity;
  }}
  .card-row::-webkit-scrollbar {{
    height: 4px;
  }}
  .card-row::-webkit-scrollbar-thumb {{
    background: #444;
    border-radius: 2px;
  }}

  /* ---- Deal card ---- */
  .deal-card {{
    flex: 0 0 auto;
    width: 200px;
    min-width: 200px;
    background: #252525;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 10px 12px;
    scroll-snap-align: start;
  }}
  .deal-card:first-child {{
    border-left: 3px solid #4caf50;
  }}
  .card-img {{
    width: 100%;
    height: 180px;
    object-fit: contain;
    border-radius: 4px;
    margin-bottom: 6px;
    background: #1a1a1a;
    cursor: zoom-in;
  }}
  .card-product {{
    font-size: 0.82rem;
    color: #d0d0d0;
    line-height: 1.3;
    margin-bottom: 6px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .card-price {{
    font-weight: 700;
    font-size: 1.1rem;
    color: #66bb6a;
  }}
  .card-unit-price {{
    font-size: 0.85rem;
    color: #b0b0b0;
    margin-top: 1px;
  }}
  .card-store {{
    font-size: 0.85rem;
    color: #b0b0b0;
    margin-top: 4px;
  }}
  .card-weight {{
    display: inline-block;
    background: #1a2a3a;
    color: #90caf9;
    font-size: 0.75rem;
    padding: 1px 5px;
    border-radius: 3px;
    margin-left: 4px;
    vertical-align: middle;
  }}
  .card-count {{
    display: inline-block;
    background: #2a1a3a;
    color: #ce93d8;
    font-size: 0.75rem;
    padding: 1px 5px;
    border-radius: 3px;
    margin-left: 4px;
    vertical-align: middle;
  }}

  /* Lightbox */
  #lightbox {{
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.92); z-index: 999;
    justify-content: center; align-items: center;
    cursor: zoom-out;
  }}
  #lightbox.active {{ display: flex; }}
  #lightbox img {{
    max-width: 95vw; max-height: 90vh;
    object-fit: contain; border-radius: 8px;
  }}

  /* Footer */
  .footer {{ text-align: center; color: #888; font-size: 0.8rem; padding: 16px 0 8px; }}
</style>
</head>
<body>
<h1>Cam's Grocery Deals</h1>
<p class="date">Updated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
"""

    def _html_footer(self) -> str:
        return """
<div class="footer">Generated by Grocery Planner</div>
<div id="lightbox"><img src="" alt=""></div>
<script>
(function(){
  var lb = document.getElementById('lightbox');
  var lbImg = lb.querySelector('img');
  document.querySelectorAll('.card-img').forEach(function(img){
    img.addEventListener('click', function(){
      lbImg.src = img.src;
      lb.classList.add('active');
    });
  });
  lb.addEventListener('click', function(){ lb.classList.remove('active'); });
})();
</script>
</body>
</html>"""
