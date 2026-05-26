"""数据模型单元测试。"""

from decimal import Decimal

from jd_tracker.models import CartItem, ChangeRecord, CartSnapshot


class TestCartItem:
    def test_create_minimal(self):
        item = CartItem(sku_id="123", name="测试商品")
        assert item.sku_id == "123"
        assert item.name == "测试商品"
        assert item.model == ""
        assert item.quantity == 1
        assert item.price == Decimal("0")
        assert item.in_stock is True
        assert item.snapshot_at == ""

    def test_to_dict_and_from_dict(self):
        original = CartItem(
            sku_id="100012345678",
            name="iPhone 15 Pro",
            model="256GB 原色",
            quantity=2,
            price=Decimal("8999.00"),
            in_stock=True,
            snapshot_at="2026-05-26T14:30:00+08:00",
        )
        d = original.to_dict()
        restored = CartItem.from_dict(d)
        assert restored.sku_id == original.sku_id
        assert restored.name == original.name
        assert restored.model == original.model
        assert restored.quantity == original.quantity
        assert restored.price == original.price
        assert restored.in_stock == original.in_stock
        assert restored.snapshot_at == original.snapshot_at

    def test_from_dict_defaults(self):
        d = {"sku_id": "456", "name": "耳机"}
        item = CartItem.from_dict(d)
        assert item.model == ""
        assert item.quantity == 1
        assert item.price == Decimal("0")
        assert item.in_stock is True

    def test_key(self):
        item = CartItem(sku_id="abc123", name="test")
        assert item.key == "abc123"


class TestCartSnapshot:
    def test_empty_snapshot(self):
        snap = CartSnapshot()
        assert len(snap) == 0
        assert snap.to_index() == {}

    def test_to_index(self):
        items = [
            CartItem(sku_id="1", name="A"),
            CartItem(sku_id="2", name="B"),
        ]
        snap = CartSnapshot(items=items)
        index = snap.to_index()
        assert len(index) == 2
        assert index["1"].name == "A"
        assert index["2"].name == "B"

    def test_from_items(self):
        items = [CartItem(sku_id="x", name="X")]
        snap = CartSnapshot.from_items(items)
        assert len(snap) == 1
        assert snap.items[0].sku_id == "x"
