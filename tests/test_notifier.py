"""通知器单元测试。"""

from decimal import Decimal

import pytest

from jd_tracker.models import ChangeRecord
from jd_tracker.notifier import PushPlusNotifier


def _make_change(
    sku_id: str = "1",
    name: str = "测试商品",
    model: str = "",
    old_price: str | None = "100",
    new_price: str | None = "80",
) -> ChangeRecord:
    """快速构造降价 ChangeRecord。"""
    return ChangeRecord(
        change_type="price_changed",
        sku_id=sku_id,
        name=name,
        model=model,
        detail=f"价格波动: ¥{old_price} → ¥{new_price}",
        old_price=Decimal(old_price) if old_price is not None else None,
        new_price=Decimal(new_price) if new_price is not None else None,
    )


class TestPushPlusFormat:
    """PushPlus 消息格式化测试。"""

    def test_single_drop(self):
        """单件商品降价：含金额和百分比。"""
        n = PushPlusNotifier(token="t")
        changes = [_make_change(name="iPhone", old_price="100", new_price="80")]
        msg = n._format_message(changes)
        assert "iPhone" in msg
        assert "100" in msg
        assert "80" in msg
        assert "↓¥20" in msg
        assert "-20.0%" in msg

    def test_multiple_drops(self):
        """多件商品降价：每件独立展示。"""
        n = PushPlusNotifier(token="t")
        changes = [
            _make_change(sku_id="1", name="商品A", old_price="200", new_price="150"),
            _make_change(sku_id="2", name="商品B", old_price="1000", new_price="850"),
        ]
        msg = n._format_message(changes)
        assert "2 件商品降价" in msg
        assert "商品A" in msg
        assert "-25.0%" in msg
        assert "商品B" in msg
        assert "-15.0%" in msg

    def test_with_model(self):
        """含型号的商品正确显示。"""
        n = PushPlusNotifier(token="t")
        changes = [
            _make_change(name="iPhone", model="256GB 黑色", old_price="8999", new_price="8499"),
        ]
        msg = n._format_message(changes)
        assert "256GB 黑色" in msg

    def test_empty_list(self):
        """空列表不崩溃。"""
        n = PushPlusNotifier(token="t")
        msg = n._format_message([])
        assert msg == ""

    def test_none_prices_skipped(self):
        """old_price/new_price 为 None 时安全跳过。"""
        n = PushPlusNotifier(token="t")
        changes = [
            _make_change(name="异常商品", old_price=None, new_price="80"),
        ]
        msg = n._format_message(changes)
        assert "异常商品" not in msg  # 被跳过
        assert msg == ""  # 无有效记录时返回空

    def test_zero_old_price_skipped(self):
        """原价为 0 的商品跳过（避免除零）。"""
        n = PushPlusNotifier(token="t")
        changes = [
            _make_change(name="零元商品", old_price="0", new_price="0"),
        ]
        msg = n._format_message(changes)
        assert "零元商品" not in msg

    def test_percentage_precision(self):
        """百分比保留一位小数。"""
        n = PushPlusNotifier(token="t")
        # 100 → 33: diff=67, pct=67.0%
        changes = [_make_change(old_price="100", new_price="33")]
        msg = n._format_message(changes)
        assert "-67.0%" in msg

        # 30 → 10: diff=20, pct=66.7% (四舍五入)
        changes2 = [_make_change(old_price="30", new_price="10")]
        msg2 = n._format_message(changes2)
        assert "-66.7%" in msg2

    def test_request_body_structure(self):
        """验证 HTTP 请求体 JSON 结构。"""
        import json

        n = PushPlusNotifier(token="abc123")
        changes = [_make_change(name="测试", old_price="50", new_price="30")]
        msg = n._format_message(changes)

        payload = {
            "token": n._token,
            "title": f"📉 京东降价：{len(changes)} 件商品",
            "content": msg,
            "template": "markdown",
        }
        body = json.dumps(payload, ensure_ascii=False)
        data = json.loads(body)

        assert data["token"] == "abc123"
        assert data["template"] == "markdown"
        assert "测试" in data["content"]
        assert "📉" in data["title"]


class TestPushPlusSend:
    """PushPlus send() 方法测试（不实际发 HTTP）。"""

    def test_send_empty_changes_returns_true(self):
        """空变化列表直接返回 True，不发 HTTP。"""
        n = PushPlusNotifier(token="t")
        import asyncio

        result = asyncio.run(n.send([]))
        assert result is True
