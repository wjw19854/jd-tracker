"""监控对比引擎单元测试。"""

from decimal import Decimal

from jd_tracker.models import CartItem, ChangeRecord
from jd_tracker.monitor import compare_snapshots


class TestCompareSnapshots:
    """对比引擎的各种场景。"""

    def test_no_changes(self):
        prev = [
            CartItem(sku_id="1", name="A", price=Decimal("10"), quantity=1),
            CartItem(sku_id="2", name="B", price=Decimal("20"), quantity=2),
        ]
        curr = [
            CartItem(sku_id="1", name="A", price=Decimal("10"), quantity=1),
            CartItem(sku_id="2", name="B", price=Decimal("20"), quantity=2),
        ]
        changes = compare_snapshots(prev, curr)
        assert changes == []

    def test_item_added(self):
        prev = [CartItem(sku_id="1", name="A", price=Decimal("10"))]
        curr = [
            CartItem(sku_id="1", name="A", price=Decimal("10")),
            CartItem(sku_id="2", name="B", price=Decimal("20")),
        ]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.ITEM_ADDED
        assert changes[0].sku_id == "2"
        assert changes[0].name == "B"

    def test_item_removed(self):
        prev = [
            CartItem(sku_id="1", name="A", price=Decimal("10")),
            CartItem(sku_id="2", name="B", price=Decimal("20")),
        ]
        curr = [CartItem(sku_id="1", name="A", price=Decimal("10"))]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.ITEM_REMOVED
        assert changes[0].sku_id == "2"
        assert changes[0].name == "B"

    def test_price_changed_up(self):
        prev = [CartItem(sku_id="1", name="A", price=Decimal("10.00"))]
        curr = [CartItem(sku_id="1", name="A", price=Decimal("15.00"))]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.PRICE_CHANGED
        assert changes[0].old_price == Decimal("10.00")
        assert changes[0].new_price == Decimal("15.00")
        assert "↑" in changes[0].detail

    def test_price_changed_down(self):
        prev = [CartItem(sku_id="1", name="A", price=Decimal("20.00"))]
        curr = [CartItem(sku_id="1", name="A", price=Decimal("15.00"))]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.PRICE_CHANGED
        assert changes[0].old_price == Decimal("20.00")
        assert changes[0].new_price == Decimal("15.00")
        assert "↓" in changes[0].detail

    def test_quantity_changed(self):
        prev = [CartItem(sku_id="1", name="A", quantity=1)]
        curr = [CartItem(sku_id="1", name="A", quantity=3)]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.QUANTITY_CHANGED
        assert changes[0].old_quantity == 1
        assert changes[0].new_quantity == 3

    def test_stock_changed_out_of_stock(self):
        prev = [CartItem(sku_id="1", name="A", in_stock=True)]
        curr = [CartItem(sku_id="1", name="A", in_stock=False)]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.STOCK_CHANGED
        assert "下架" in changes[0].detail or "无货" in changes[0].detail

    def test_stock_changed_back_in_stock(self):
        prev = [CartItem(sku_id="1", name="A", in_stock=False)]
        curr = [CartItem(sku_id="1", name="A", in_stock=True)]
        changes = compare_snapshots(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.STOCK_CHANGED
        assert "有货" in changes[0].detail

    def test_multiple_changes(self):
        prev = [
            CartItem(sku_id="1", name="A", price=Decimal("10"), quantity=1),
            CartItem(sku_id="3", name="C", price=Decimal("30"), in_stock=True),
        ]
        curr = [
            CartItem(sku_id="1", name="A", price=Decimal("12"), quantity=1),
            CartItem(sku_id="2", name="B", price=Decimal("20"), quantity=1),
        ]
        changes = compare_snapshots(prev, curr)
        # 1: price changed, 2: added, 3: removed
        assert len(changes) == 3
        types = {c.change_type for c in changes}
        assert "price_changed" in types
        assert "item_added" in types
        assert "item_removed" in types

    def test_empty_previous(self):
        curr = [CartItem(sku_id="1", name="A", price=Decimal("10"))]
        changes = compare_snapshots([], curr)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.ITEM_ADDED

    def test_empty_current(self):
        prev = [CartItem(sku_id="1", name="A", price=Decimal("10"))]
        changes = compare_snapshots(prev, [])
        assert len(changes) == 1
        assert changes[0].change_type == ChangeRecord.ChangeType.ITEM_REMOVED
