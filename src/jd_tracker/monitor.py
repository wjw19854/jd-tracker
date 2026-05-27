"""快照对比引擎 —— 检测价格/数量/商品变化。"""

from __future__ import annotations

import logging
from decimal import Decimal

from jd_tracker.models import CartItem, CartSnapshot, ChangeRecord

logger = logging.getLogger(__name__)


def compare_snapshots(
    previous: list[CartItem],
    current: list[CartItem],
) -> list[ChangeRecord]:
    """对比两个快照，返回变化记录列表。

    Args:
        previous: 上一次购物车快照。
        current: 当前购物车快照。

    Returns:
        变化记录列表，按变化类型分组。
    """
    changes: list[ChangeRecord] = []

    prev_index = {item.sku_id: item for item in previous}
    curr_index = {item.sku_id: item for item in current}

    prev_ids = set(prev_index.keys())
    curr_ids = set(curr_index.keys())

    # 1. 新增商品
    added_ids = curr_ids - prev_ids
    for sku_id in sorted(added_ids):
        item = curr_index[sku_id]
        changes.append(ChangeRecord(
            change_type=ChangeRecord.ChangeType.ITEM_ADDED,
            sku_id=sku_id,
            name=item.name,
            model=item.model,
            detail=f"新增商品 (价格: ¥{item.price}, 数量: {item.quantity})",
            new_price=item.price,
            new_quantity=item.quantity,
        ))

    # 2. 移除商品
    removed_ids = prev_ids - curr_ids
    for sku_id in sorted(removed_ids):
        item = prev_index[sku_id]
        changes.append(ChangeRecord(
            change_type=ChangeRecord.ChangeType.ITEM_REMOVED,
            sku_id=sku_id,
            name=item.name,
            model=item.model,
            detail=f"商品已移除 (原价格: ¥{item.price}, 原数量: {item.quantity})",
            old_price=item.price,
            old_quantity=item.quantity,
        ))

    # 3. 对比共同存在的商品
    common_ids = prev_ids & curr_ids
    for sku_id in sorted(common_ids):
        prev_item = prev_index[sku_id]
        curr_item = curr_index[sku_id]

        # 3a. 价格变化
        if prev_item.price != curr_item.price:
            diff = curr_item.price - prev_item.price
            sign = "↓" if diff < 0 else "↑"
            changes.append(ChangeRecord(
                change_type=ChangeRecord.ChangeType.PRICE_CHANGED,
                sku_id=sku_id,
                name=curr_item.name,
                model=curr_item.model,
                detail=(
                    f"价格波动: ¥{prev_item.price} → ¥{curr_item.price} "
                    f"({sign}¥{abs(diff)})"
                ),
                old_price=prev_item.price,
                new_price=curr_item.price,
            ))

        # 3b. 数量变化
        if prev_item.quantity != curr_item.quantity:
            diff = curr_item.quantity - prev_item.quantity
            sign = "+" if diff > 0 else ""
            changes.append(ChangeRecord(
                change_type=ChangeRecord.ChangeType.QUANTITY_CHANGED,
                sku_id=sku_id,
                name=curr_item.name,
                model=curr_item.model,
                detail=f"数量变化: {prev_item.quantity} → {curr_item.quantity} ({sign}{diff})",
                old_quantity=prev_item.quantity,
                new_quantity=curr_item.quantity,
            ))

        # 3c. 库存状态变化
        if prev_item.in_stock != curr_item.in_stock:
            if not curr_item.in_stock:
                changes.append(ChangeRecord(
                    change_type=ChangeRecord.ChangeType.STOCK_CHANGED,
                    sku_id=sku_id,
                    name=curr_item.name,
                    model=curr_item.model,
                    detail="商品已下架/无货",
                ))
            else:
                changes.append(ChangeRecord(
                    change_type=ChangeRecord.ChangeType.STOCK_CHANGED,
                    sku_id=sku_id,
                    name=curr_item.name,
                    model=curr_item.model,
                    detail="商品已恢复有货",
                ))

    return changes


def report_changes(
    changes: list[ChangeRecord],
    current_count: int,
) -> None:
    """输出变化报告到日志。

    Args:
        changes: 变化记录列表。
        current_count: 当前购物车商品总数。
    """
    if not changes:
        logger.info("📋 购物车无变化，共 %d 件商品", current_count)
        # 仍然输出当前商品摘要
        return

    logger.info("=" * 60)
    logger.info("📋 购物车变化报告（当前共 %d 件商品）", current_count)
    logger.info("=" * 60)

    # 按类型分组输出
    # 新增
    added = [c for c in changes if c.change_type == ChangeRecord.ChangeType.ITEM_ADDED]
    if added:
        logger.info("--- 新增商品 (%d) ---", len(added))
        for c in added:
            logger.info("  🆕 %s", c)

    # 移除
    removed = [c for c in changes if c.change_type == ChangeRecord.ChangeType.ITEM_REMOVED]
    if removed:
        logger.info("--- 移除商品 (%d) ---", len(removed))
        for c in removed:
            logger.info("  🗑️  %s", c)

    # 价格
    price_changes = [c for c in changes if c.change_type == ChangeRecord.ChangeType.PRICE_CHANGED]
    if price_changes:
        logger.info("--- 价格波动 (%d) ---", len(price_changes))
        for c in price_changes:
            logger.info("  💰 %s", c)

    # 数量
    qty_changes = [c for c in changes if c.change_type == ChangeRecord.ChangeType.QUANTITY_CHANGED]
    if qty_changes:
        logger.info("--- 数量变化 (%d) ---", len(qty_changes))
        for c in qty_changes:
            logger.info("  📦 %s", c)

    # 库存
    stock_changes = [c for c in changes if c.change_type == ChangeRecord.ChangeType.STOCK_CHANGED]
    if stock_changes:
        logger.info("--- 库存状态 (%d) ---", len(stock_changes))
        for c in stock_changes:
            logger.info("  🏪 %s", c)

    logger.info("=" * 60)


def print_summary(items: list[CartItem]) -> None:
    """输出当前购物车商品摘要。"""
    if not items:
        logger.info("🛒 购物车为空")
        return

    logger.info("🛒 当前购物车商品:")
    for item in items:
        logger.info(
            "  [%s] %s | %s | ×%d | ¥%s",
            item.sku_id,
            item.name,
            item.model or "-",
            item.quantity,
            item.price,
        )
