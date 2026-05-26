#!/usr/bin/env python3
"""交互式 DOM 调试工具。

运行后自动打开浏览器、导航到购物车、登录、滚动到底部，
然后将页面 DOM 结构信息 dump 到 logs/ 目录供离线分析。

用法:
    cd jd-tracker
    PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers PYTHONPATH=src .venv/bin/python tools/debug_dom.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# 确保 src 在 Python path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jd_tracker.browser import BrowserManager
from jd_tracker.cart import navigate_to_cart, scroll_to_bottom, warmup_browser
from jd_tracker.config import load_config
from jd_tracker.login import ensure_login

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("debug_dom")


async def main() -> None:
    config = load_config()
    config.ensure_dirs()

    browser = BrowserManager(config)
    dump_path = Path(config.log_dir) / "dom_analysis.json"

    try:
        # 1. 启动浏览器
        logger.info("启动浏览器...")
        page = await browser.start()

        # 2. 预热 + 导航
        await warmup_browser(page, config)
        if not await navigate_to_cart(page, config):
            logger.error("导航失败")
            return

        # 3. 登录检测
        logged_in = await ensure_login(page, config)
        if not logged_in:
            logger.error("登录失败")
            return

        # 4. 保存登录态
        await browser.save_storage_state()

        # 5. 滚动到底部
        await scroll_to_bottom(page, config)

        # 6. 收集 DOM 信息
        logger.info("收集 DOM 信息...")
        result = {}

        # 6a. 页面基本信息
        result["url"] = page.url
        result["title"] = await page.title()

        # 6b. body class
        result["body_class"] = await page.evaluate("document.body.className")

        # 6c. window 上有哪些变量名（含 cart/sku/item/ware/state）
        result["window_keys"] = await page.evaluate("""
            () => {
                const keys = [];
                for (const key of Object.keys(window)) {
                    try {
                        if (key.length > 2 && key.length < 60 && window[key] !== null) {
                            const kl = key.toLowerCase();
                            if (kl.includes('cart') || kl.includes('sku') || kl.includes('ware')
                                || kl.includes('item') || kl.includes('state') || kl.includes('nuxt')
                                || kl.includes('data') || kl.includes('order') || kl.includes('product')) {
                                const t = typeof window[key];
                                keys.push(key + ' [' + t + ']');
                            }
                        }
                    } catch(e) {}
                }
                return keys.sort();
            }
        """)

        # 6d. 所有 data-sku 元素的数量和第一个的 outerHTML 片段
        sku_info = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('[data-sku]');
                const result = {
                    count: rows.length,
                    samples: []
                };
                // 取前 3 个 sample
                for (let i = 0; i < Math.min(rows.length, 3); i++) {
                    const row = rows[i];
                    const sku = row.getAttribute('data-sku') || '';
                    const html = row.outerHTML.substring(0, 2000);  // 截断
                    result.samples.push({ sku, html });
                }
                return result;
            }
        """)
        result["data_sku"] = sku_info

        # 6e. 页面中有多少链接指向 item.jd.com
        result["item_links_count"] = await page.evaluate(
            'document.querySelectorAll(\'a[href*="item.jd.com"]\').length'
        )

        # 6f. 搜索页面中所有可能包含价格的元素
        result["price_elements"] = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('[class*="price"], .p-price, .item-total');
                const samples = [];
                for (let i = 0; i < Math.min(els.length, 5); i++) {
                    const el = els[i];
                    samples.push({
                        tag: el.tagName,
                        class: el.className,
                        text: (el.textContent || '').trim().substring(0, 200)
                    });
                }
                return { count: els.length, samples };
            }
        """)

        # 7. 写入结果
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("DOM 分析已保存: %s", dump_path)

        # 8. 同时保存完整 HTML
        html_path = Path(config.log_dir) / "cart_page_dump.html"
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        logger.info("页面 HTML 已保存: %s (%d 字符)", html_path, len(html))

    except Exception as e:
        logger.exception("调试异常: %s", e)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
