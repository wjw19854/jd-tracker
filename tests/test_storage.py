"""存储模块单元测试。"""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from jd_tracker.models import CartItem
from jd_tracker.storage import load_snapshot, save_snapshot


class TestSnapshotIO:
    def test_save_and_load(self, tmp_path: Path):
        path = str(tmp_path / "test_snapshot.jsonl")

        items = [
            CartItem(sku_id="1", name="A", price=Decimal("10.50"), quantity=1),
            CartItem(sku_id="2", name="B", price=Decimal("20.00"), quantity=2),
        ]

        assert save_snapshot(path, items) is True
        assert os.path.exists(path)

        loaded = load_snapshot(path)
        assert len(loaded) == 2
        assert loaded[0].sku_id == "1"
        assert loaded[0].price == Decimal("10.50")
        assert loaded[1].sku_id == "2"
        assert loaded[1].quantity == 2

    def test_load_nonexistent(self, tmp_path: Path):
        path = str(tmp_path / "nonexistent.jsonl")
        loaded = load_snapshot(path)
        assert loaded == []

    def test_load_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        loaded = load_snapshot(str(path))
        assert loaded == []

    def test_load_invalid_lines(self, tmp_path: Path):
        path = tmp_path / "partial.jsonl"
        path.write_text(
            '{"sku_id":"1","name":"valid","price":"10"}\n'
            'invalid json\n'
            '{"sku_id":"3","name":"also valid","price":"30"}\n'
        )
        loaded = load_snapshot(str(path))
        assert len(loaded) == 2
        assert loaded[0].sku_id == "1"
        assert loaded[1].sku_id == "3"

    def test_overwrite_snapshot(self, tmp_path: Path):
        path = str(tmp_path / "overwrite.jsonl")

        old_items = [CartItem(sku_id="old", name="Old")]
        save_snapshot(path, old_items)

        new_items = [CartItem(sku_id="new", name="New")]
        save_snapshot(path, new_items)

        loaded = load_snapshot(path)
        assert len(loaded) == 1
        assert loaded[0].sku_id == "new"
