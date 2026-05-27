"""登录检测与等待手动登录的重试循环。

在等待期间通过 human_like_idle 维持人类行为特征，
降低长时间无操作触发风控的风险。
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page

from jd_tracker.cart import detect_risk_control, human_like_idle
from jd_tracker.config import Config

logger = logging.getLogger(__name__)

# 用于判断是否已登录的特征
_LOGIN_INDICATORS = [
    'text="我的京东"',
    'text="退出"',
    '[class*="nickname"]',
    '[class*="user-name"]',
    '[class*="userName"]',
    '[data-stat*="nickname"]',
    'a:has-text("去结算")',
    'button:has-text("结算")',
]


async def _is_logged_in(page: Page) -> bool:
    """判断当前是否已登录京东。

    采用多种策略：URL 白名单 + 登录特征元素检测。
    """
    url = page.url.lower()

    # 策略1：URL 被重定向到登录页
    if "passport.jd.com" in url:
        logger.debug("URL 在登录页: %s", url)
        return False

    # 策略2：页面包含明显的登录按钮
    login_btn = page.locator('text="你好，请登录"').first
    if await login_btn.count() > 0:
        logger.debug("检测到'你好，请登录'文案")
        return False

    # 策略3：检查是否存在已登录指示器
    for selector in _LOGIN_INDICATORS:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                logger.debug("已登录指示器命中: %s", selector)
                return True
        except Exception:
            continue

    # 策略4：检查关键 cookie
    cookies = await page.context.cookies()
    cookie_names = {c["name"] for c in cookies}
    if "pt_pin" in cookie_names and "pt_key" in cookie_names:
        logger.debug("检测到登录 cookie (pt_pin + pt_key)")
        return True

    # 默认：无法确定
    logger.debug("无法确定登录状态，假定未登录")
    return False


async def ensure_login(page: Page, config: Config) -> bool:
    """确保用户已登录。

    检测登录状态，未登录时提示并等待用户手动登录。
    最多重试 config.login_max_retries 次。
    等待期间通过 human_like_idle 模拟轻度浏览行为，防止风控。
    检测到风控时不会立即退出，而是等待后重试（最多 risk_control_max_retries 次）。

    Returns:
        True 表示已登录，False 表示重试耗尽或风控重试耗尽。
    """
    import random

    risk_retries = 0

    for attempt in range(1, config.login_max_retries + 1):
        # 先检测风控
        is_risk, kw = await detect_risk_control(page)
        if is_risk:
            if risk_retries < config.risk_control_max_retries:
                risk_retries += 1
                logger.warning(
                    "⚠️  登录检测中触发风控 ('%s')，第 %d/%d 次，"
                    "等待 %.0f 秒后重试...",
                    kw,
                    risk_retries,
                    config.risk_control_max_retries,
                    config.risk_control_retry_delay_seconds,
                )
                await human_like_idle(page, config.risk_control_retry_delay_seconds, config)
                continue  # 不消耗登录重试次数，直接重新检测
            else:
                logger.error("❌ 风控重试耗尽 ('%s')，已重试 %d 次", kw, risk_retries)
                return False

        logged_in = await _is_logged_in(page)

        if logged_in:
            logger.info("✅ 已登录京东 (第 %d 次检测)", attempt)
            return True

        if attempt < config.login_max_retries:
            # 带随机抖动的等待时间
            jittered_wait = config.login_wait_seconds * (1.0 + random.uniform(-config.jitter_ratio, config.jitter_ratio))
            logger.warning(
                "⚠️  未检测到登录状态 (第 %d/%d 次)，请在浏览器窗口中手动登录。"
                "等待 %.0f 秒后重新检测...",
                attempt,
                config.login_max_retries,
                jittered_wait,
            )

            # 等待期间模拟低强度浏览，替代纯 sleep
            await human_like_idle(page, jittered_wait, config)
        else:
            logger.error(
                "❌ 登录检测失败，已重试 %d 次，退出。",
                config.login_max_retries,
            )

    return False
