"""购物车页面导航、warmup 与风控检测。

包含随机抖动工具函数 `_jitter`，所有等待操作均带有 ±30% 随机偏移，
模拟人类不规律的浏览节奏。
"""

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


def _jitter(base_seconds: float, ratio: float = 0.3) -> float:
    """在 base ± (base * ratio) 范围内返回随机等待秒数。

    例如 base=3.0, ratio=0.3 → [2.1, 3.9]
    """
    return base_seconds * (1.0 + random.uniform(-ratio, ratio))


async def warmup_browser(page: Page, config: Config) -> None:
    """预热浏览器：访问京东首页并模拟人类浏览行为。

    操作序列：访问首页 → 随机延迟 → 向下滚动 → 随机延迟 →
    小幅回滚 → 随机延迟 → 鼠标移动到页面中央区域。
    """
    logger.info("预热访问京东首页...")
    try:
        # 访问首页
        await page.goto(
            "https://www.jd.com",
            wait_until="domcontentloaded",
            timeout=config.browser_timeout_ms,
        )

        # 模拟人类：慢慢滚动浏览
        delay = _jitter(3.0, config.jitter_ratio)
        await asyncio.sleep(delay)

        # 第一段滚动
        scroll_y = int(300 + random.random() * 400)
        await page.evaluate(f"window.scrollBy({{top: {scroll_y}, behavior: 'smooth'}})")
        await asyncio.sleep(_jitter(1.0, config.jitter_ratio))

        # 模拟鼠标移动到页面中央（触发 hover 效果）
        try:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            await page.mouse.move(
                vp["width"] * random.uniform(0.3, 0.7),
                vp["height"] * random.uniform(0.3, 0.6),
                steps=random.randint(5, 15),
            )
        except Exception:
            pass

        await asyncio.sleep(_jitter(0.8, config.jitter_ratio))

        # 第二段小幅回滚
        scroll_y2 = int(100 + random.random() * 200)
        await page.evaluate(f"window.scrollBy({{top: -{scroll_y2}, behavior: 'smooth'}})")
        await asyncio.sleep(_jitter(0.5, config.jitter_ratio))

        logger.info("首页预热完成 (URL: %s)", page.url)
    except Exception as e:
        logger.warning("首页预热失败（继续执行）: %s", e)


async def human_like_idle(page: Page, duration_seconds: float, config: Config) -> None:
    """模拟人类在页面上的空闲浏览行为。

    不会长时间无操作，而是间歇性地微调滚动位置、移动鼠标，
    以维持人类行为特征。在登录等待期间调用此函数。

    Args:
        page: Playwright Page 对象。
        duration_seconds: 总空闲时长（秒）。
        config: 全局配置。
    """
    logger.debug("开始模拟空闲浏览 (%.1fs)...", duration_seconds)
    elapsed = 0.0
    while elapsed < duration_seconds:
        # 每次操作间隔 3-8 秒
        chunk = _jitter(5.0, config.jitter_ratio)
        chunk = min(chunk, duration_seconds - elapsed)
        if chunk <= 0:
            break
        await asyncio.sleep(chunk)
        elapsed += chunk

        if elapsed >= duration_seconds:
            break

        # 轻度交互：微调滚动或移动鼠标
        try:
            action = random.random()
            vp = page.viewport_size or {"width": 1280, "height": 800}

            if action < 0.5:
                # 微小滚动
                delta = random.randint(-80, 80)
                await page.evaluate(f"window.scrollBy({{top: {delta}, behavior: 'smooth'}})")
            else:
                # 鼠标移动
                await page.mouse.move(
                    vp["width"] * random.uniform(0.2, 0.8),
                    vp["height"] * random.uniform(0.2, 0.8),
                    steps=random.randint(3, 10),
                )
        except Exception:
            pass

    logger.debug("空闲浏览结束")


async def navigate_to_cart(page: Page, config: Config) -> bool:
    """导航到购物车页面，包含重试和随机延迟。

    在请求之前加入随机等待，降低请求频率特征。
    """
    for attempt in range(1, config.network_retries + 1):
        try:
            # 请求前随机等待（模拟人类从首页点击到购物车的思考时间）
            if attempt == 1:
                pre_delay = _jitter(2.0, config.jitter_ratio)
                logger.debug("导航前等待 %.1fs", pre_delay)
                await asyncio.sleep(pre_delay)

            logger.info("正在导航到购物车: %s", config.cart_url)
            await page.goto(
                config.cart_url,
                wait_until="domcontentloaded",
                timeout=config.browser_timeout_ms,
            )

            # 页面加载后等待（让 JS 执行、图片加载）
            await asyncio.sleep(_jitter(3.0, config.jitter_ratio))

            try:
                await page.wait_for_load_state(
                    "networkidle",
                    timeout=config.cart_load_timeout_ms,
                )
            except Exception:
                logger.debug("networkidle 等待超时，继续执行")

            logger.info("购物车页面已加载 (URL: %s)", page.url)

            # 轻量滚动（触发懒加载监听）
            await page.evaluate("window.scrollBy(0, 200)")
            await asyncio.sleep(_jitter(0.5, config.jitter_ratio))

            return True
        except Exception as e:
            logger.warning(
                "导航到购物车失败 (第 %d/%d 次): %s",
                attempt, config.network_retries, e,
            )
            if attempt < config.network_retries:
                retry_delay = _jitter(config.network_retry_delay_seconds, config.jitter_ratio)
                await asyncio.sleep(retry_delay)
            else:
                logger.error("导航到购物车失败")
                return False
    return False


async def detect_risk_control(page: Page) -> tuple[bool, str]:
    """检测页面是否被风控拦截。

    Returns:
        (is_risk, keyword): 是否触发风控及匹配的关键词。
    """
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
    """保存调试截图到 logs/ 目录。"""
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
    """动态分段跳转，每步重新获取高度，覆盖虚拟列表所有区域。

    每次跳转后的等待时间带有随机抖动，降低机器人节奏特征。
    """
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
        await asyncio.sleep(_jitter(3.0, config.jitter_ratio))
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
        await asyncio.sleep(_jitter(2.0, config.jitter_ratio))
        logger.debug("反向 %d/%d, y=%d, height=%d", s, segments, target_y, total_height)

    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(_jitter(2.0, config.jitter_ratio))
    logger.info("分段跳转完成 (最大高度=%d)，已回到顶部", max_y)


async def dump_page_html(page: Page, config: Config) -> str | None:
    """保存当前页面 HTML 到文件供离线分析。"""
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
    """等待购物车容器渲染完成。"""
    logger.info("等待购物车内容加载...")
    selectors = [
        ".cart-body", "#cart-list", ".item-list",
        ".cart-empty", '[data-sku]',
    ]
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=3_000, state="attached")
            logger.debug("购物车容器已加载: %s", selector)
            return True
        except Exception:
            continue
    logger.warning("购物车容器选择器均未命中，但页面已到达购物车 URL，继续解析")
    return True
