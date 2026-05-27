"""Playwright 浏览器生命周期管理。

封装启动、stealth 配置、storage_state 持久化、关闭清理。
优先使用系统 Chrome（消除 Chromium 指纹差异），支持 CDP 连接备选。
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from jd_tracker.config import Config

logger = logging.getLogger(__name__)

# 真实 Chrome macOS UA 池（按版本降序，覆盖近 6 个主版本）
_USER_AGENT_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# 常见 Mac 分辨率
_VIEWPORT_POOL = [
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1680, "height": 1050},
    {"width": 1366, "height": 768},
]

# webdriver 二次覆盖 + 增强 stealth（在 playwright-stealth 之后注入）
_ENHANCED_STEALTH_JS = """
() => {
    // 1. navigator.webdriver 覆盖
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // 2. navigator.plugins 假数据（真实 Chrome 的典型插件列表）
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
            ];
            plugins.item = (i) => plugins[i] || null;
            plugins.namedItem = (n) => plugins.find(p => p.name === n) || null;
            plugins.refresh = () => {};
            return plugins;
        },
    });

    // 3. navigator.mimeTypes 假数据
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const mimeTypes = [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ];
            mimeTypes.item = (i) => mimeTypes[i] || null;
            mimeTypes.namedItem = (n) => mimeTypes.find(m => m.type === n) || null;
            return mimeTypes;
        },
    });

    // 4. WebGL 指纹伪装
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';       // UNMASKED_VENDOR_WEBGL
        if (p === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
        return getParameter.call(this, p);
    };
    const getParameter2d = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter2d.call(this, p);
    };

    // 5. window.outerWidth/Height 匹配 inner（避免 headless 下不一致）
    Object.defineProperty(window, 'outerWidth', {
        get: () => window.innerWidth,
    });
    Object.defineProperty(window, 'outerHeight', {
        get: () => window.innerHeight + 80,  // 模拟浏览器 chrome
    });

    // 6. screen 属性匹配 viewport
    if (screen.width < 1024) {
        Object.defineProperty(screen, 'width', { get: () => window.innerWidth });
        Object.defineProperty(screen, 'height', { get: () => window.innerHeight });
    }

    // 7. permissions 覆盖（保留 playwright-stealth 行为，二次覆盖确保生效）
    try {
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: 'prompt', onchange: null }) :
                originalQuery(parameters)
        );
    } catch(e) {}

    // 8. 移除自动化痕迹
    delete window.__phantomas;
    delete window.__webdriver_evaluate;
    delete window.__selenium_evaluate;
    delete window.__webdriver_script_function;
    delete window.__webdriver_script_func;
    delete window.__webdriver_script_fn;
    delete window.__fxdriver_evaluate;
    delete window.__driver_evaluate;
    delete window.__webdriver_unwrapped;
    delete window.__webdriver_script_fn;
    delete window.__webdriver_script_func;
    delete window.__webdriver_script_function;
}
"""


class BrowserManager:
    """管理 Playwright 浏览器实例的全生命周期。"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._user_agent: str = random.choice(_USER_AGENT_POOL)
        self._viewport: dict = random.choice(_VIEWPORT_POOL)

    async def start(self, capture_network: bool = False) -> Page:
        """启动浏览器并返回 Page 对象。

        优先使用系统 Chrome（通过 channel="chrome"），消除 Playwright
        自带 Chromium 的指纹差异（缺少字体/Codec/Widevine/WebGL 等）。
        如果 channel 启动失败，回退到 Playwright 默认 Chromium。
        若配置了 CDP URL，则直接连接到已打开的 Chrome。

        Args:
            capture_network: 是否拦截并记录网络请求（调试用）。
        """
        self._playwright = await async_playwright().start()

        # --- CDP 连接模式（备选方案 E） ---
        if self._config.cdp_url:
            logger.info("通过 CDP 连接到已打开的 Chrome: %s", self._config.cdp_url)
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._config.cdp_url,
            )
            # CDP 模式下使用已有 context 和 page
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
            else:
                self._context = await self._browser.new_context()
                self._page = await self._context.new_page()
            logger.info("CDP 连接成功 (pages=%d)", len(self._context.pages))
            return self._page

        # --- 启动模式（方案 A：优先系统 Chrome） ---
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--disable-browser-side-navigation",
        ]

        channel = self._config.chrome_channel or None

        if channel:
            try:
                logger.info("尝试使用系统 Chrome (channel=%s)...", channel)
                self._browser = await self._playwright.chromium.launch(
                    headless=self._config.headless,
                    channel=channel,
                    args=launch_args,
                )
                logger.info("✅ 已使用系统 Chrome")
            except Exception as e:
                logger.warning(
                    "系统 Chrome 启动失败 (%s)，回退到 Playwright 默认 Chromium", e,
                )
                channel = None

        if self._browser is None:
            self._browser = await self._playwright.chromium.launch(
                headless=self._config.headless,
                args=launch_args,
            )

        # 加载持久化登录态
        storage_state = None
        state_path = Path(self._config.storage_state_path)
        if state_path.exists():
            logger.info("加载持久化登录态: %s", state_path)
            storage_state = str(state_path)

        logger.debug(
            "浏览器指纹: UA=%s, viewport=%dx%d",
            self._user_agent[:50] + "...",
            self._viewport["width"],
            self._viewport["height"],
        )

        # 方案 B：移除 Accept-Encoding 手动设置（让浏览器自己处理）
        self._context = await self._browser.new_context(
            viewport=self._viewport,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=self._user_agent,
            storage_state=storage_state,
            extra_http_headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;"
                    "q=0.8,application/signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        self._page = await self._context.new_page()

        # playwright-stealth 注入
        await Stealth().apply_stealth_async(self._page)

        # 方案 C：增强 stealth JS 注入
        try:
            await self._page.evaluate(_ENHANCED_STEALTH_JS)
            logger.debug("增强 stealth JS 已注入")
        except Exception as e:
            logger.debug("增强 stealth JS 注入失败（非致命）: %s", e)

        # 验证 navigator.webdriver（None=JS undefined=正常覆盖，True=未覆盖）
        try:
            wd = await self._page.evaluate("navigator.webdriver")
            if wd is True:
                logger.warning("⚠️  navigator.webdriver=true，可能被检测！")
            elif wd is None:
                logger.debug("navigator.webdriver=undefined ✓ 覆盖成功")
            else:
                logger.debug("navigator.webdriver=%s", wd)
        except Exception:
            pass

        # 方案 D：网络诊断（拦截购物车 API）
        if capture_network:
            await self._setup_network_diagnostics()

        logger.info(
            "浏览器已启动 (headless=%s, channel=%s, stealth=enabled)",
            self._config.headless,
            channel or "chromium",
        )
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def _setup_network_diagnostics(self) -> None:
        """拦截购物车相关 API 请求，记录到日志供离线分析。"""
        logged_urls: set = set()

        async def log_request(route):
            url = route.request.url
            if url not in logged_urls:
                logged_urls.add(url)
                logger.debug("[NET] → %s %s", route.request.method, url[:120])
            await route.continue_()

        async def log_response(response):
            url = response.url
            if any(kw in url for kw in ["cart", "sku", "ware", "item", "price"]):
                try:
                    body = await response.text()
                    preview = body[:300] if body else "(empty)"
                    logger.debug(
                        "[NET] ← %s %s status=%d body_preview=%s",
                        response.request.method,
                        url[:100],
                        response.status,
                        preview,
                    )
                except Exception:
                    logger.debug(
                        "[NET] ← %s %s status=%d",
                        response.request.method,
                        url[:100],
                        response.status,
                    )

        await self._page.route("**/*", log_request)
        self._page.on("response", log_response)

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
