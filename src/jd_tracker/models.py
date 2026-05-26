"""数据模型定义。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass
class CartItem:
    """购物车中的单个商品。"""

    sku_id: str
    name: str
    model: str = ""
    quantity: int = 1
    price: Decimal = Decimal("0")
    in_stock: bool = True
    snapshot_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["price"] = str(self.price)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CartItem:
        return cls(
            sku_id=d["sku_id"],
            name=d["name"],
            model=d.get("model", ""),
            quantity=d.get("quantity", 1),
            price=Decimal(d.get("price", "0")),
            in_stock=d.get("in_stock", True),
            snapshot_at=d.get("snapshot_at", ""),
        )

    @property
    def key(self) -> str:
        """唯一标识：sku_id。"""
        return self.sku_id


@dataclass
class ChangeRecord:
    """一条变化记录。"""

    class ChangeType:
        PRICE_CHANGED = "price_changed"
        QUANTITY_CHANGED = "quantity_changed"
        ITEM_ADDED = "item_added"
        ITEM_REMOVED = "item_removed"
        STOCK_CHANGED = "stock_changed"

    change_type: str
    sku_id: str
    name: str
    detail: str  # 人类可读的变化描述
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    old_quantity: int | None = None
    new_quantity: int | None = None

    def __str__(self) -> str:
        return f"[{self.change_type}] {self.name} ({self.sku_id}): {self.detail}"


@dataclass
class CartSnapshot:
    """一次购物车快照。"""

    items: list[CartItem] = field(default_factory=list)
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_index(self) -> dict[str, CartItem]:
        """按 sku_id 索引。"""
        return {item.sku_id: item for item in self.items}

    @classmethod
    def from_items(cls, items: list[CartItem]) -> CartSnapshot:
        return cls(items=items)

    def __len__(self) -> int:
        return len(self.items)
