from collections import Counter, defaultdict
from decimal import Decimal

from pydantic import ValidationError

from .config import RetailSettings
from .rules import active, current_price, money, profile, stock_class
from .schema import KEYS, TABLES


class RetailValidationError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__("Synthetic retail validation failed; no invalid references were removed")


def key(row, fields):
    return tuple(getattr(row, field) for field in fields)


def validate(tables: dict, products, settings: RetailSettings) -> dict:
    errors = []
    counts = Counter(
        {
            f"invalid_{kind}_references": 0
            for kind in ("product", "store", "shelf", "placement", "supplier", "promotion")
        }
    )

    def problem(code, table, reference, message):
        errors.append(
            {"code": code, "table": table, "reference": str(reference), "message": message}
        )

    if set(tables) != set(TABLES):
        raise RetailValidationError({"valid": False, "errors": [{"code": "table_set_mismatch"}]})
    typed = {}
    for name, model in TABLES.items():
        typed[name] = []
        seen = set()
        for index, row in enumerate(tables[name], 2):
            try:
                parsed = model.model_validate(row)
                identity = key(parsed, KEYS[name])
                if identity in seen:
                    problem("duplicate_key", name, identity, "Duplicate primary key")
                seen.add(identity)
                typed[name].append(parsed)
            except ValidationError as error:
                for issue in error.errors(include_input=False, include_context=False):
                    problem(
                        "invalid_value",
                        name,
                        f"CSV row {index}",
                        f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}",
                    )
    product_ids = {p.product_id for p in products}
    store_ids = {row.store_id for row in typed["stores"]}
    shelves = {row.shelf_id: row for row in typed["shelves"]}
    placements = {row.placement_id: row for row in typed["placements"]}
    supplier_ids = {row.supplier_id for row in typed["suppliers"]}
    promotions = {row.promotion_id: row for row in typed["promotions"]}
    targets = {
        "product_id": (product_ids, "product"),
        "store_id": (store_ids, "store"),
        "shelf_id": (shelves, "shelf"),
        "placement_id": (placements, "placement"),
        "supplier_id": (supplier_ids, "supplier"),
        "promotion_id": (promotions, "promotion"),
    }
    primary = {
        "stores": "store_id",
        "shelves": "shelf_id",
        "placements": "placement_id",
        "suppliers": "supplier_id",
        "promotions": "promotion_id",
    }
    for name, rows in typed.items():
        for row in rows:
            for field, (valid_keys, kind) in targets.items():
                if field in type(row).model_fields and primary.get(name) != field:
                    value = getattr(row, field)
                    if value not in valid_keys:
                        counts[f"invalid_{kind}_references"] += 1
                        problem(f"invalid_{kind}_reference", name, value, f"Unknown {field}")
            if hasattr(row, "shelf_id") and row.shelf_id in shelves:
                if row.store_id != shelves[row.shelf_id].store_id:
                    problem(
                        "shelf_store_mismatch", name, row.shelf_id, "Shelf belongs to another store"
                    )
            if name in {"inventory", "product_promotions"} and row.placement_id in placements:
                if key(row, ("product_id", "store_id", "shelf_id")) != key(
                    placements[row.placement_id], ("product_id", "store_id", "shelf_id")
                ):
                    problem(
                        "placement_mismatch",
                        name,
                        row.placement_id,
                        "Product/store/shelf tuple disagrees",
                    )

    placement_pairs = [key(p, ("product_id", "store_id")) for p in typed["placements"]]
    pairs = set(placement_pairs)
    if len(pairs) != len(placement_pairs):
        problem(
            "duplicate_product_store",
            "placements",
            "product_id/store_id",
            "Only one shelf per product/store",
        )
    for name in ("sales", "prices"):
        actual = {key(row, ("product_id", "store_id")) for row in typed[name]}
        if actual != pairs:
            problem(
                "placement_coverage",
                name,
                sorted(actual ^ pairs),
                "Must match placed product/store pairs exactly",
            )
    assigned = {row.product_id for row in typed["product_suppliers"]}
    if assigned != product_ids:
        problem(
            "supplier_coverage",
            "product_suppliers",
            sorted(assigned ^ product_ids),
            "One primary supplier required for every real product",
        )
    placed = {row.product_id for row in typed["placements"]}
    if placed != product_ids:
        problem(
            "product_coverage",
            "placements",
            sorted(placed ^ product_ids),
            "Every input product must be placed",
        )
    inventory_placements = [row.placement_id for row in typed["inventory"]]
    if set(inventory_placements) != set(placements) or len(inventory_placements) != len(
        set(inventory_placements)
    ):
        problem(
            "inventory_coverage",
            "inventory",
            "placement_id",
            "Exactly one inventory row per placement required",
        )
    max_units = Counter()
    slots = defaultdict(list)
    for inv in typed["inventory"]:
        max_units[inv.shelf_id] += inv.max_stock
    for placement in typed["placements"]:
        slots[placement.shelf_id].append((placement.shelf_position, placement.facings))
    for shelf_id, shelf in shelves.items():
        if max_units[shelf_id] > shelf.capacity:
            problem(
                "capacity_exceeded",
                "shelves",
                shelf_id,
                "Sum of reserved max_stock exceeds shelf unit capacity",
            )
        end = 0
        for start, facings in sorted(slots[shelf_id]):
            if start <= end:
                problem(
                    "overlapping_facings",
                    "placements",
                    shelf_id,
                    "Shelf position intervals overlap",
                )
            end = start + facings - 1

    active_assignments = {}
    all_assignments = {}
    for row in typed["product_promotions"]:
        promo = promotions.get(row.promotion_id)
        all_assignments[(row.product_id, row.store_id)] = promo
        if promo and active(promo, settings.as_of_date):
            active_assignments[(row.product_id, row.store_id)] = promo
    by_product = {p.product_id: p for p in products}
    for price in typed["prices"]:
        pair = price.product_id, price.store_id
        if price.current_price != current_price(
            price.base_price, all_assignments.get(pair), settings.as_of_date
        ):
            problem(
                "price_discount_mismatch",
                "prices",
                pair,
                "Current price does not match active percentage discount",
            )
        if price.product_id in by_product:
            _, _, (low, high), _ = profile(by_product[price.product_id])
            if (
                not money(low * Decimal("0.95"))
                <= price.base_price
                <= money(high * Decimal("1.05"))
            ):
                problem(
                    "price_out_of_profile",
                    "prices",
                    pair,
                    "Base price outside declared synthetic category range",
                )
    expected_counts = {
        "stores": settings.store_count,
        "shelves": settings.store_count * settings.shelves_per_store,
        "placements": settings.placement_count,
        "inventory": settings.placement_count,
        "sales": settings.placement_count,
        "prices": settings.placement_count,
        "suppliers": settings.supplier_count,
        "product_suppliers": len(products),
        "promotions": settings.promotion_count,
        "product_promotions": round(settings.placement_count * settings.promotion_rate),
    }
    for name, expected in expected_counts.items():
        if len(typed[name]) != expected:
            problem("row_count_mismatch", name, len(typed[name]), f"Expected {expected} rows")
    for sid in store_ids:
        if sum(s.store_id == sid for s in shelves.values()) != settings.shelves_per_store:
            problem("shelf_count_mismatch", "shelves", sid, "Unexpected shelves per store")
    for pid, count in Counter(p.product_id for p in typed["placements"]).items():
        if count > settings.max_stores_per_product:
            problem("excess_product_coverage", "placements", pid, "Too many stores for product")
    integrity = {"valid": not errors, **counts, "errors": errors}
    if errors:
        raise RetailValidationError(integrity)

    sales = {(row.product_id, row.store_id): row for row in typed["sales"]}
    distribution = Counter({s: 0 for s in ("healthy", "low", "critical", "out_of_stock")})
    scenario = Counter({case: 0 for case in "ABCDEF"})
    examples = {case: [] for case in "ABCDEF"}
    for inv in typed["inventory"]:
        pair = inv.product_id, inv.store_id
        sold = sales[pair]
        low, high = (
            inv.stock < inv.reorder_level,
            sold.units_sold_30d >= settings.high_sales_threshold,
        )
        healthy = not low
        is_promo = pair in active_assignments
        conditions = {
            "A": high and low,
            "B": high and healthy,
            "C": sold.units_sold_30d <= settings.low_sales_threshold
            and inv.stock >= 0.75 * inv.max_stock,
            "D": is_promo and low,
            "E": is_promo and high,
            "F": inv.stock == 0 and sold.units_sold_7d > 0,
        }
        distribution[stock_class(inv.stock, inv.reorder_level)] += 1
        for case, found in conditions.items():
            if found:
                scenario[case] += 1
                if len(examples[case]) < 5:
                    examples[case].append(inv.placement_id)
    if any(value == 0 for value in scenario.values()):
        raise RetailValidationError(
            {
                **integrity,
                "valid": False,
                "errors": [{"code": "missing_scenario", "scenario_counts": dict(scenario)}],
            }
        )
    sold30 = [row.units_sold_30d for row in typed["sales"]]
    count = len(placements)
    return {
        "counts": {name: len(rows) for name, rows in typed.items()},
        "integrity": integrity,
        "inventory_distribution": {
            name: {"count": n, "percentage": round(100 * n / count, 2)}
            for name, n in distribution.items()
        },
        "low_stock_count": sum(n for name, n in distribution.items() if name != "healthy"),
        "critical_stock_count": distribution["critical"],
        "out_of_stock_count": distribution["out_of_stock"],
        "sales_distribution": {
            "window_days": 30,
            "minimum": min(sold30),
            "maximum": max(sold30),
            "average": round(sum(sold30) / len(sold30), 2),
            "high_sales_product_store_count": sum(
                n >= settings.high_sales_threshold for n in sold30
            ),
            "low_sales_product_store_count": sum(n <= settings.low_sales_threshold for n in sold30),
            "high_sales_distinct_products": len(
                {
                    row.product_id
                    for row in typed["sales"]
                    if row.units_sold_30d >= settings.high_sales_threshold
                }
            ),
            "low_sales_distinct_products": len(
                {
                    row.product_id
                    for row in typed["sales"]
                    if row.units_sold_30d <= settings.low_sales_threshold
                }
            ),
            "high_sales_threshold": settings.high_sales_threshold,
            "low_sales_threshold": settings.low_sales_threshold,
        },
        "promotion_distribution": {
            "total": len(promotions),
            "active": sum(active(p, settings.as_of_date) for p in promotions.values()),
            "expired": sum(p.end_date < settings.as_of_date for p in promotions.values()),
            "scheduled": sum(p.start_date > settings.as_of_date for p in promotions.values()),
            "assigned_placements": len(all_assignments),
            "active_promoted_placements": len(active_assignments),
            "assigned_placement_percentage": round(100 * len(all_assignments) / count, 2),
            "active_placement_percentage": round(100 * len(active_assignments) / count, 2),
            "distinct_products_assigned": len({pid for pid, _ in all_assignments}),
            "distinct_product_percentage": round(
                100 * len({pid for pid, _ in all_assignments}) / len(products), 2
            ),
        },
        "scenario_counts": dict(scenario),
        "scenario_examples": examples,
        "placements_per_store": dict(
            sorted(Counter(p.store_id for p in placements.values()).items())
        ),
        "product_store_coverage": dict(
            sorted(Counter(Counter(p.product_id for p in placements.values()).values()).items())
        ),
        "shelf_category_distribution": dict(
            sorted(Counter(s.category for s in shelves.values()).items())
        ),
    }
