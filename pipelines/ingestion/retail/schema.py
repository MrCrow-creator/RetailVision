from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]
Money = Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=2, allow_inf_nan=False)]


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Store(Row):
    store_id: Text
    store_name: Text
    city: Text
    region: Text
    store_type: Literal["Supermarket", "Neighborhood Market"]


class Shelf(Row):
    shelf_id: Text
    store_id: Text
    shelf_name: Text
    aisle: Positive
    category: Text
    capacity: Positive  # Total unit capacity of this synthetic shelf/merchandising zone.


class Placement(Row):
    placement_id: Text
    product_id: Text
    store_id: Text
    shelf_id: Text
    facings: Annotated[int, Field(ge=1, le=4)]
    shelf_position: Positive  # First facing slot; interval length equals facings.


class Inventory(Row):
    inventory_id: Text
    placement_id: Text
    product_id: Text
    store_id: Text
    shelf_id: Text
    stock: Count
    reorder_level: Positive
    max_stock: Positive

    @model_validator(mode="after")
    def stock_limits(self):
        if self.stock > self.max_stock or self.reorder_level >= self.max_stock:
            raise ValueError("Expected stock <= max_stock and reorder_level < max_stock")
        return self


class Sales(Row):
    product_id: Text
    store_id: Text
    units_sold_7d: Count
    units_sold_30d: Count

    @model_validator(mode="after")
    def windows(self):
        if self.units_sold_7d > self.units_sold_30d:
            raise ValueError("7-day sales cannot exceed 30-day sales")
        return self


class Price(Row):
    product_id: Text
    store_id: Text
    base_price: Money
    current_price: Money
    currency: Literal["INR"]


class Supplier(Row):
    supplier_id: Text
    supplier_name: Text
    region: Text


class ProductSupplier(Row):
    product_id: Text
    supplier_id: Text


class Promotion(Row):
    promotion_id: Text
    promotion_name: Text
    promotion_type: Literal["PERCENTAGE_DISCOUNT", "CLEARANCE", "SEASONAL"]
    discount_percentage: Annotated[int, Field(gt=0, le=35)]
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates(self):
        if self.start_date >= self.end_date:
            raise ValueError("Promotion start_date must precede end_date")
        return self


class ProductPromotion(Row):
    placement_id: Text
    product_id: Text
    store_id: Text
    shelf_id: Text
    promotion_id: Text


TABLES = {
    "stores": Store,
    "shelves": Shelf,
    "placements": Placement,
    "inventory": Inventory,
    "sales": Sales,
    "prices": Price,
    "suppliers": Supplier,
    "product_suppliers": ProductSupplier,
    "promotions": Promotion,
    "product_promotions": ProductPromotion,
}
KEYS = {
    "stores": ("store_id",),
    "shelves": ("shelf_id",),
    "placements": ("placement_id",),
    "inventory": ("inventory_id",),
    "sales": ("product_id", "store_id"),
    "prices": ("product_id", "store_id"),
    "suppliers": ("supplier_id",),
    "product_suppliers": ("product_id",),
    "promotions": ("promotion_id",),
    "product_promotions": ("placement_id",),
}
