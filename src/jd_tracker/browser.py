"""Playwright 浏览器生命周期管理。

封装启动、stealth 配置（playwright-stealth）、storage_state 持久化、关闭清理。
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from jd_tracker.config import Config

logger = logging.getLogger(__name__)


class BrowserManager:
    """管理 Playwright 浏览器实例的全生命周期。"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> Page:
        """启动浏览器并返回 Page 对象。

        会尝试加载 storage_state 持久化登录态。通过 playwright-stealth 注入完整反检测脚本。
        """
        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self._config.headless,
            args=launch_args,
        )

        # 加载持久化登录态（如果存在）
        storage_state = None
        state_path = Path(self._config.storage_state_path)
        if state_path.exists():
            logger.info("加载持久化登录态: %s", state_path)
            storage_state = str(state_path)

        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            storage_state=storage_state,
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

        self._page = await self._context.new_page()
        await Stealth().apply_stealth_async(self._page)

        logger.info("浏览器已启动 (headless=%s, stealth=enabled)", self._config.headless)
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def save_storage_state(self) -> None:
        """保存当前登录态到 storage_state 文件。"""
        if self._context is None:
            return
        state_path = Path(self._config.storage_state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(state_path))
        logger.info("登录态已保存到 %s", state_path)

    async def close(self) -> None:
        """关闭浏览器并释放资源。"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("浏览器已关闭")
