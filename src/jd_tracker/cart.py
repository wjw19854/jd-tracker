"""购物车页面导航、warmup 与风控检测。"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

from playwright.async_api import Page

from jd_tracker.config import Config

logger = logging.getLogger(__name__)

_RISK_KEYWORDS = [
    "操作过于频繁", "休息一下", "请稍后再试", "访问太频繁",
    "触发流量防控", "请输入验证码", "验证码",
]


async def warmup_browser(page: Page, config: Config) -> None:
    logger.info("预热访问京东首页...")
    try:
        await page.goto("https://www.jd.com", wait_until="domcontentloaded", timeout=config.browser_timeout_ms)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        await page.evaluate("window.scrollBy(0, 300 + Math.random() * 400)")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        logger.info("首页预热完成 (URL: %s)", page.url)
    except Exception as e:
        logger.warning("首页预热失败（继续执行）: %s", e)


async def navigate_to_cart(page: Page, config: Config) -> bool:
    for attempt in range(1, config.network_retries + 1):
        try:
            logger.info("正在导航到购物车: %s", config.cart_url)
            await page.goto(config.cart_url, wait_until="domcontentloaded", timeout=config.browser_timeout_ms)
            await asyncio.sleep(random.uniform(2.0, 4.0))
            try:
                await page.wait_for_load_state("networkidle", timeout=config.cart_load_timeout_ms)
            except Exception:
                logger.debug("networkidle 等待超时，继续执行")
            logger.info("购物车页面已加载 (URL: %s)", page.url)
            await page.evaluate("window.scrollBy(0, 200)")
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return True
        except Exception as e:
            logger.warning("导航到购物车失败 (第 %d/%d 次): %s", attempt, config.network_retries, e)
            if attempt < config.network_retries:
                await asyncio.sleep(config.network_retry_delay_seconds)
            else:
                logger.error("导航到购物车失败")
                return False
    return False


async def detect_risk_control(page: Page) -> tuple[bool, str]:
    try:
        body_text = await page.inner_text("body")
        for kw in _RISK_KEYWORDS:
            if kw in body_text or kw.lower() in body_text.lower():
                logger.warning("检测到风控关键词: '%s'", kw)
                return True, kw
    except Exception:
        pass
    return False, ""


async def take_debug_screenshot(page: Page, config: Config, name: str = "debug") -> str | None:
    try:
        config.ensure_dirs()
        path = Path(config.log_dir) / f"screenshot_{name}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.info("截图已保存: %s", path)
        return str(path)
    except Exception as e:
        logger.warning("截图失败: %s", e)
        return None


async def scroll_to_bottom(page: Page, config: Config) -> None:
    """动态分段跳转，每步重新获取高度，覆盖虚拟列表所有区域。"""
    logger.info("动态分段跳转以触发虚拟列表渲染...")
    segments = 10
    prev_total = 0
    stable = 0
    max_y = 0

    for s in range(segments + 1):
        # 每次都重新获取高度（虚拟列表会逐步扩张）
        total_height = await page.evaluate("document.body.scrollHeight")
        if total_height == prev_total:
            stable += 1
            if stable >= 2:
                logger.debug("高度稳定 (%dpx)，正向完成", total_height)
                break
        else:
            stable = 0
        prev_total = total_height
        if total_height > max_y:
            max_y = total_height

        target_y = int(total_height * s / segments)
        await page.evaluate(f"window.scrollTo(0, {target_y})")
        await asyncio.sleep(3.0)
        logger.debug("正向 %d/%d, y=%d, height=%d", s, segments, target_y, total_height)

    # 反向再走一遍
    stable = 0
    for s in range(segments, -1, -1):
        total_height = await page.evaluate("document.body.scrollHeight")
        if total_height == prev_total:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev_total = total_height
        if total_height > max_y:
            max_y = total_height

        target_y = int(total_height * s / segments)
        await page.evaluate(f"window.scrollTo(0, {target_y})")
        await asyncio.sleep(2.0)
        logger.debug("反向 %d/%d, y=%d, height=%d", s, segments, target_y, total_height)

    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(2.0)
    logger.info("分段跳转完成 (最大高度=%d)，已回到顶部", max_y)


async def dump_page_html(page: Page, config: Config) -> str | None:
    try:
        config.ensure_dirs()
        path = Path(config.log_dir) / "cart_page_dump.html"
        html = await page.content()
        path.write_text(html, encoding="utf-8")
        logger.info("页面 HTML 已保存: %s (%d 字符)", path, len(html))
        return str(path)
    except Exception as e:
        logger.warning("保存 HTML 失败: %s", e)
        return None


async def wait_for_cart_load(page: Page, config: Config) -> bool:
    logger.info("等待购物车内容加载...")
    selectors = [".cart-body", "#cart-list", ".item-list", ".cart-empty", '[data-sku]']
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=3_000, state="attached")
            logger.debug("购物车容器已加载: %s", selector)
            return True
        except Exception:
            continue
    logger.warning("购物车容器选择器均未命中，但页面已到达购物车 URL，继续解析")
    return True
