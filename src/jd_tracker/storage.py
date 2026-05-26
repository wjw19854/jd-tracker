"""JSONL 文件读写 —— 购物车快照持久化。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from jd_tracker.models import CartItem

logger = logging.getLogger(__name__)


def load_snapshot(path: str) -> list[CartItem]:
    """从 JSONL 文件中加载购物车快照。

    每行一个 CartItem 的 JSON 序列化形式。

    Returns:
        商品列表，文件不存在或为空时返回空列表。
    """
    file_path = Path(path)
    if not file_path.exists():
        logger.info("快照文件不存在，首次运行: %s", path)
        return []

    items: list[CartItem] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    item = CartItem.from_dict(data)
                    items.append(item)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("快照文件第 %d 行解析失败: %s", line_no, e)
                    continue

        logger.info("已加载上次快照: %d 个商品", len(items))
    except OSError as e:
        logger.error("读取快照文件失败: %s", e)
        return []

    return items


def save_snapshot(path: str, items: list[CartItem]) -> bool:
    """将商品列表保存为 JSONL 文件。

    每行一个 CartItem，覆盖写入。

    Returns:
        True 表示保存成功。
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

        logger.info("已保存快照: %d 个商品 → %s", len(items), path)
        return True
    except OSError as e:
        logger.error("保存快照失败: %s", e)
        return False
