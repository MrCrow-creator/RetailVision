import math
import random
from collections import Counter, defaultdict
from datetime import timedelta

from .config import RetailSettings
from .rules import (
    DISCOUNTS,
    LOCATIONS,
    PROMOTION_TYPES,
    STOCK_WEIGHTS,
    active,
    current_price,
    money,
    profile,
    sales_windows,
)
from .schema import TABLES, Promotion


def promotions(settings: RetailSettings, rng) -> list[dict]:
    result = []
    for index in range(settings.promotion_count):
        state = index % 10
        if state < 7:
            start = settings.as_of_date - timedelta(days=rng.randint(1, 21))
            end = settings.as_of_date + timedelta(days=rng.randint(7, 28))
        elif state < 9:
            end = settings.as_of_date - timedelta(days=rng.randint(1, 14))
            start = end - timedelta(days=rng.randint(14, 30))
        else:
            start = settings.as_of_date + timedelta(days=rng.randint(7, 21))
            end = start + timedelta(days=rng.randint(7, 28))
        result.append(
            {
                "promotion_id": f"PROMO_{index + 1:03d}",
                "promotion_name": f"RetailVision Synthetic Offer {index + 1:03d}",
                "promotion_type": rng.choice(PROMOTION_TYPES),
                "discount_percentage": rng.choice(DISCOUNTS),
                "start_date": start,
                "end_date": end,
            }
        )
    return result


def generate(products, settings: RetailSettings) -> dict[str, list[dict]]:
    settings.check_scale(len(products))
    rng = random.Random(settings.seed)
    products = sorted(products, key=lambda p: p.product_id)
    tables = {name: [] for name in TABLES}
    stores = tables["stores"]
    for index in range(settings.store_count):
        city, region = LOCATIONS[index]
        stores.append(
            {
                "store_id": f"STORE_{index + 1:03d}",
                "store_name": f"RetailVision Market {index + 1:02d}",
                "city": city,
                "region": region,
                "store_type": "Neighborhood Market" if index % 3 == 2 else "Supermarket",
            }
        )
    store_ids = [store["store_id"] for store in stores]
    footfall = {sid: rng.uniform(0.85, 1.20) for sid in store_ids}
    price_factor = {sid: rng.uniform(0.95, 1.05) for sid in store_ids}
    for index in range(settings.supplier_count):
        tables["suppliers"].append(
            {
                "supplier_id": f"SUP_{index + 1:03d}",
                "supplier_name": f"RetailVision Supply Network {index + 1:02d}",
                "region": LOCATIONS[index % len(LOCATIONS)][1],
            }
        )
    supplier_ids = [row["supplier_id"] for row in tables["suppliers"]]
    profiles, demand, prices = {}, {}, {}
    for product in products:
        pid = product.product_id
        group, _, (low, high), factor = profile(product)
        profiles[pid] = group
        prices[pid] = money(rng.randrange(low * 2, high * 2 + 1) / 2)
        tier = rng.choices(["slow", "normal", "fast"], weights=[20, 60, 20])[0]
        baseline = rng.uniform(*{"slow": (0, 15), "normal": (25, 75), "fast": (90, 180)}[tier])
        demand[pid] = baseline * factor
        tables["product_suppliers"].append(
            {"product_id": pid, "supplier_id": rng.choice(supplier_ids)}
        )

    # Every real product gets a placement. Remaining distinct product/store pairs are sampled.
    pairs = {
        (p.product_id, rng.choices(store_ids, weights=list(footfall.values()))[0]) for p in products
    }
    coverage = Counter(pid for pid, _ in pairs)
    candidates = [
        (p.product_id, sid)
        for p in products
        for sid in store_ids
        if (p.product_id, sid) not in pairs
    ]
    rng.shuffle(candidates)
    for pid, sid in candidates:
        if len(pairs) == settings.placement_count:
            break
        if coverage[pid] < min(settings.max_stores_per_product, settings.store_count):
            pairs.add((pid, sid))
            coverage[pid] += 1
    groups_by_store = {
        sid: Counter(profiles[pid] for pid, store in pairs if store == sid) for sid in store_ids
    }
    shelf_groups = defaultdict(list)
    for store_index, sid in enumerate(store_ids, 1):
        counts = groups_by_store[sid]
        groups = ["General Grocery"] + sorted(
            (g for g in counts if g != "General Grocery"), key=lambda g: (-counts[g], g)
        )[: settings.shelves_per_store - 1]
        allocation = Counter(groups)
        while len(groups) < settings.shelves_per_store:
            chosen = min(allocation, key=lambda g: (-counts[g] / (allocation[g] + 1), g))
            groups.append(chosen)
            allocation[chosen] += 1
        for shelf_index, group in enumerate(groups, 1):
            shelf = {
                "shelf_id": f"SHELF_{store_index:03d}_{shelf_index:02d}",
                "store_id": sid,
                "shelf_name": f"{group} Zone {shelf_index:02d}",
                "aisle": (shelf_index - 1) // 3 + 1,
                "category": group,
                "capacity": 1,
            }
            tables["shelves"].append(shelf)
            shelf_groups[(sid, group)].append(shelf["shelf_id"])
    positions = Counter()
    for pid, sid in sorted(pairs):
        options = shelf_groups.get((sid, profiles[pid])) or shelf_groups[(sid, "General Grocery")]
        shelf = min(options, key=lambda key: (positions[key], key))
        facings = rng.choices([1, 2, 3, 4], weights=[25, 45, 20, 10])[0]
        tables["placements"].append(
            {
                "placement_id": f"PLC_{sid}_{pid}",
                "product_id": pid,
                "store_id": sid,
                "shelf_id": shelf,
                "facings": facings,
                "shelf_position": positions[shelf] + 1,
            }
        )
        positions[shelf] += facings

    # Six deliberately constructed anchors (<0.1% at the default scale), with randomized identities.
    shuffled = list(tables["placements"])
    rng.shuffle(shuffled)
    anchors = {p["placement_id"]: case for p, case in zip(shuffled[:6], "ABCDEF", strict=True)}
    tables["promotions"] = promotions(settings, rng)
    campaign = {r["promotion_id"]: Promotion.model_validate(r) for r in tables["promotions"]}
    active_ids = [key for key, p in campaign.items() if active(p, settings.as_of_date)]
    assigned = [p for p in shuffled if anchors.get(p["placement_id"]) in {"D", "E"}]
    assigned_ids = {p["placement_id"] for p in assigned}
    rest = [p for p in shuffled if p["placement_id"] not in assigned_ids]
    assigned += rest[: round(settings.placement_count * settings.promotion_rate) - len(assigned)]
    campaign_ids = list(campaign)
    rng.shuffle(campaign_ids)
    assigned_promos = {}
    for index, placement in enumerate(assigned):
        key = placement["placement_id"]
        promo_id = (
            active_ids[index % len(active_ids)]
            if anchors.get(key) in {"D", "E"}
            else campaign_ids[index % len(campaign_ids)]
        )
        assigned_promos[key] = campaign[promo_id]
        tables["product_promotions"].append(
            {
                field: placement[field]
                for field in ("placement_id", "product_id", "store_id", "shelf_id")
            }
            | {"promotion_id": promo_id}
        )

    reserved_units = Counter()
    for placement in tables["placements"]:
        pid, sid, shelf = (placement[key] for key in ("product_id", "store_id", "shelf_id"))
        key = placement["placement_id"]
        case = anchors.get(key)
        promotion = assigned_promos.get(key)
        monthly = demand[pid] * footfall[sid] * (1 + 0.08 * (placement["facings"] - 1))
        sold7, sold30 = sales_windows(rng, monthly, promotion, settings.as_of_date)
        if case in {"A", "B", "E"}:
            sold30 = rng.randint(
                settings.high_sales_threshold + 10, settings.high_sales_threshold + 60
            )
            sold7 = round(sold30 * rng.uniform(0.18, 0.32))
        elif case == "C":
            sold30 = rng.randint(0, settings.low_sales_threshold)
            sold7 = round(sold30 * rng.uniform(0.15, 0.30))
        elif case == "F":
            sold7 = max(1, sold7)
            sold30 = max(sold30, sold7)
        tables["sales"].append(
            {"product_id": pid, "store_id": sid, "units_sold_7d": sold7, "units_sold_30d": sold30}
        )
        base = money(prices[pid] * money(price_factor[sid]))
        tables["prices"].append(
            {
                "product_id": pid,
                "store_id": sid,
                "base_price": base,
                "current_price": current_price(base, promotion, settings.as_of_date),
                "currency": "INR",
            }
        )
        state = rng.choices(list(STOCK_WEIGHTS), weights=list(STOCK_WEIGHTS.values()))[0]
        state = {"A": "low", "B": "healthy", "C": "healthy", "D": "low", "F": "out_of_stock"}.get(
            case, state
        )
        maximum = placement["facings"] * rng.randint(10, 24)
        reorder = max(5, round(maximum * rng.uniform(0.25, 0.45)))
        critical = max(1, reorder // 4)
        bounds = {
            "healthy": (reorder + 2, maximum),
            "low": (critical + 1, reorder - 1),
            "critical": (1, critical),
            "out_of_stock": (0, 0),
        }
        stock = rng.randint(*bounds[state])
        if case == "C":
            stock = max(stock, math.ceil(maximum * 0.8))
        tables["inventory"].append(
            {
                "inventory_id": f"INV_{sid}_{pid}",
                "placement_id": key,
                "product_id": pid,
                "store_id": sid,
                "shelf_id": shelf,
                "stock": stock,
                "reorder_level": reorder,
                "max_stock": maximum,
            }
        )
        reserved_units[shelf] += maximum
    for shelf in tables["shelves"]:
        shelf["capacity"] = max(
            100, math.ceil(reserved_units[shelf["shelf_id"]] * rng.uniform(1.10, 1.25))
        )
    return tables
