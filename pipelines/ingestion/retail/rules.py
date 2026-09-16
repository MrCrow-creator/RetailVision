from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

# Exact existing OFF tag matches, in priority order. These are synthetic merchandising
# assumptions, not product-category replacements, real prices, or learned demand estimates.
# label, tags, INR range, relative demand
PROFILES = (
    ("Beverages", {"en:beverages"}, (20, 220), 1.20),
    ("Dairy", {"en:dairies", "en:dairy-products"}, (35, 350), 1.15),
    ("Fresh Produce", {"en:fresh-vegetables", "en:fresh-fruits"}, (20, 180), 1.25),
    ("Bakery", {"en:breads", "en:pastries", "en:cakes"}, (25, 280), 1.15),
    ("Confectionery", {"en:chocolates", "en:confectioneries"}, (20, 400), 1.00),
    ("Snacks", {"en:snacks", "en:biscuits", "en:crisps"}, (20, 280), 1.15),
    ("Cooking Oils", {"en:vegetable-oils", "en:olive-oils"}, (100, 850), 0.75),
    ("Condiments", {"en:condiments", "en:sauces", "en:spices"}, (25, 320), 0.80),
    ("Staples", {"en:cereals-and-their-products", "en:pulses"}, (30, 400), 1.10),
    ("General Grocery", set(), (30, 450), 1.00),
)

LOCATIONS = (
    ("Pune", "Maharashtra"),
    ("Mumbai", "Maharashtra"),
    ("Nashik", "Maharashtra"),
    ("Nagpur", "Maharashtra"),
    ("Bengaluru", "Karnataka"),
    ("Mysuru", "Karnataka"),
    ("Hyderabad", "Telangana"),
    ("Chennai", "Tamil Nadu"),
    ("Ahmedabad", "Gujarat"),
    ("Jaipur", "Rajasthan"),
)
STOCK_WEIGHTS = {"healthy": 65, "low": 24, "critical": 8, "out_of_stock": 3}
PROMOTION_TYPES = ("PERCENTAGE_DISCOUNT", "CLEARANCE", "SEASONAL")
DISCOUNTS = (5, 10, 15, 20, 25)


def profile(product):
    tags = set(product.category_normalized)
    return next((entry for entry in PROFILES if tags & entry[1]), PROFILES[-1])


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def active(promotion, as_of: date) -> bool:
    return promotion.start_date <= as_of <= promotion.end_date


def current_price(base: Decimal, promotion, as_of: date) -> Decimal:
    discount = promotion.discount_percentage if promotion and active(promotion, as_of) else 0
    return money(base * (Decimal(100) - Decimal(discount)) / Decimal(100))


def stock_class(stock: int, reorder_level: int) -> str:
    if stock == 0:
        return "out_of_stock"
    if stock >= reorder_level:
        return "healthy"
    if stock <= max(1, reorder_level // 4):
        return "critical"
    return "low"


def promoted_days(promotion, start: date, end: date) -> int:
    if not promotion:
        return 0
    return max(0, (min(promotion.end_date, end) - max(promotion.start_date, start)).days + 1)


def sales_windows(rng, monthly: float, promotion, as_of: date) -> tuple[int, int]:
    boost = 1 + (promotion.discount_percentage / 100 * rng.uniform(0.6, 1.4) if promotion else 0)

    def window(start, end, days):
        effective_days = days + promoted_days(promotion, start, end) * (boost - 1)
        return max(0, round(monthly * effective_days / 30 * rng.uniform(0.75, 1.25)))

    recent = window(as_of - timedelta(days=6), as_of, 7)
    earlier = window(as_of - timedelta(days=29), as_of - timedelta(days=7), 23)
    return recent, recent + earlier
