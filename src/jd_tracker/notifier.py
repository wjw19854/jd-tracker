"""通知器 —— 降价提醒推送。

支持：
- PushPlus（微信推送服务）
- 预留 Webhook 扩展点（飞书 / 企业微信 / 钉钉群机器人）
"""

from __future__ import annotations

import json
import logging
import urllib.request
from abc import ABC, abstractmethod
from decimal import Decimal

from jd_tracker.config import Config
from jd_tracker.models import ChangeRecord

logger = logging.getLogger(__name__)


class Notifier(ABC):
    """通知器抽象基类。

    子类实现 send() 方法，负责将变化记录格式化为平台特定的消息并发送。
    """

    @abstractmethod
    async def send(self, changes: list[ChangeRecord]) -> bool:
        """发送变化通知。

        Args:
            changes: 已过滤的变化记录列表（调用侧负责过滤）。

        Returns:
            True 表示发送成功（或无需发送），False 表示发送失败。
        """
        ...


class PushPlusNotifier(Notifier):
    """PushPlus 通知器。

    通过 PushPlus 服务将降价信息推送到微信。

    使用方式：
        1. 访问 https://www.pushplus.plus/ 微信扫码关注公众号
        2. 获取 token
        3. 设置环境变量 JD_TRACKER_NOTIFY_PUSHPLUS_TOKEN=<your_token>
    """

    API_URL = "http://www.pushplus.plus/send"

    def __init__(self, token: str, topic: str = "") -> None:
        self._token = token
        self._topic = topic

    async def send_alert(self, title: str, message: str) -> bool:
        """发送通用告警通知（不依赖变化记录）。

        Args:
            title: 通知标题。
            message: 通知正文（支持 Markdown）。

        Returns:
            True 表示发送成功，False 表示发送失败。
        """
        return await self._post(title, message)

    async def send(self, changes: list[ChangeRecord]) -> bool:
        """格式化降价信息并通过 PushPlus 发送。"""
        if not changes:
            return True

        title = f"📉 京东降价：{len(changes)} 件商品"
        content = self._format_message(changes)
        return await self._post(title, content)

    def _format_message(self, changes: list[ChangeRecord]) -> str:
        """将降价记录格式化为 Markdown 消息。

        消息包含降价金额和降幅百分比（如 ↓¥500 / -5.6%）。
        """
        lines: list[str] = ["## 📉 京东购物车降价提醒", ""]

        valid_count = 0
        for item in changes:
            if item.old_price is None or item.new_price is None:
                continue
            if item.old_price <= Decimal("0"):
                continue

            valid_count += 1
            diff = item.old_price - item.new_price
            pct = diff / item.old_price * 100

            lines.append(f"### 🔻 {item.name}")
            if item.model:
                lines.append(f"*{item.model}*")
            lines.append(
                f"> 原价 ¥{item.old_price} → 现价 ¥{item.new_price} "
                f"（↓¥{diff} / -{pct:.1f}%）"
            )
            lines.append("")

        if valid_count == 0:
            return ""

        lines.append("---")
        lines.append(f"共 {valid_count} 件商品降价，快去看看！")
        return "\n".join(lines)

    async def _post(self, title: str, content: str) -> bool:
        """发送 HTTP POST 到 PushPlus API。"""
        import asyncio

        body: dict = {
            "token": self._token,
            "title": title,
            "content": content,
            "template": "markdown",
        }
        if self._topic:
            body["topic"] = self._topic

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 200:
                logger.info("📤 降价通知已发送 (PushPlus)")
                return True
            else:
                logger.warning("PushPlus 返回非预期结果: %s", result)
                return False
        except Exception as e:
            logger.warning("PushPlus 通知发送失败: %s", e)
            return False


def create_notifier(config: Config) -> Notifier | None:
    """根据配置创建通知器实例。

    优先级：
        1. PushPlus token
        2. Webhook URL（预留扩展点）

    Returns:
        通知器实例，或 None（通知未启用或未配置渠道）。
    """
    if not config.notify_enabled:
        return None

    if config.notify_pushplus_token:
        return PushPlusNotifier(config.notify_pushplus_token, config.notify_pushplus_topic)

    # 预留：Webhook 扩展点
    # if config.notify_webhook_url:
    #     return WebhookNotifier(config.notify_webhook_url, config.notify_webhook_type)

    logger.warning("通知已启用但未配置任何通知渠道")
    return None
