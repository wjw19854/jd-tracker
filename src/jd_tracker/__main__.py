"""CLI 入口 —— 主流程编排。

用法:
    uv run jd-tracker                 # 运行一次购物车监控
    uv run jd-tracker --headless      # 无头模式（需要已登录）
    uv run jd-tracker --verbose       # 详细日志输出
    uv run jd-tracker --screenshot    # 在每个关键步骤保存截图用于调试
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from jd_tracker.browser import BrowserManager
from jd_tracker.cart import (
    detect_risk_control,
    dump_page_html,
    human_like_idle,
    navigate_to_cart,
    scroll_to_bottom,
    take_debug_screenshot,
    wait_for_cart_load,
    warmup_browser,
)
from jd_tracker.config import Config, load_config
from jd_tracker.login import ensure_login
from jd_tracker.monitor import compare_snapshots, print_summary, report_changes
from jd_tracker.parser import parse_cart_items
from jd_tracker.storage import load_snapshot, save_snapshot

logger = logging.getLogger("jd_tracker")


def setup_logging(config: Config, verbose: bool = False) -> None:
    """配置日志：同时输出到 stdout 和日志文件。"""
    level = logging.DEBUG if verbose else logging.INFO

    root_logger = logging.getLogger("jd_tracker")
    root_logger.setLevel(level)

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root_logger.addHandler(console)

    # 文件 handler
    try:
        config.ensure_dirs()
        file_handler = logging.FileHandler(config.log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_logger.addHandler(file_handler)
    except OSError as e:
        logger.warning("无法创建日志文件 %s: %s", config.log_path, e)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="jd-tracker",
        description="京东购物车价格监控工具",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行浏览器（需要已登录）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用 DEBUG 级别日志",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅抓取并显示当前购物车，不保存快照",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="在每个关键步骤保存截图到 logs/ 目录，用于调试",
    )
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help="保存购物车页面完整 HTML 到 logs/cart_page_dump.html，用于分析 DOM 结构",
    )
    return parser.parse_args(argv)


async def run(config: Config, screenshot: bool = False, dump_html: bool = False) -> int:
    """主流程。

    Returns:
        0 表示成功，非 0 表示失败。
    """
    browser = BrowserManager(config)

    try:
        # 1. 启动浏览器（始终启用 page.route 反检测）
        page = await browser.start(capture_network=True)

        # 2. 预热：先访问京东首页，降低机器人特征
        await warmup_browser(page, config)
        if screenshot:
            await take_debug_screenshot(page, config, "01_warmup")

        # 3. 导航到购物车
        if not await navigate_to_cart(page, config):
            return 1

        if screenshot:
            await take_debug_screenshot(page, config, "02_cart_page")

        # 4. 登录检测循环
        logged_in = await ensure_login(page, config)
        if not logged_in:
            await take_debug_screenshot(page, config, "03_login_failed")
            return 2

        # 5. 风控检测（登录成功后也可能触发风控，加入重试策略）
        for risk_attempt in range(1, config.risk_control_max_retries + 1):
            is_risk, kw = await detect_risk_control(page)
            if not is_risk:
                break  # 未触发风控，继续执行

            logger.warning("⚠️  检测到风控拦截 ('%s')，第 %d/%d 次尝试", kw, risk_attempt, config.risk_control_max_retries)
            await take_debug_screenshot(page, config, f"03_risk_control_{risk_attempt}")

            if risk_attempt < config.risk_control_max_retries:
                logger.info("等待 %.0f 秒后重试（模拟轻度浏览降低风控风险）...", config.risk_control_retry_delay_seconds)
                await human_like_idle(page, config.risk_control_retry_delay_seconds, config)
            else:
                logger.error("❌ 风控重试耗尽 ('%s')，无法继续", kw)
                logger.warning("触发原因可能是: 1) 请求频率过高 2) 浏览器指纹泄露 3) 短时间内多次运行")
                logger.warning("建议: 1) 降低运行频率 2) 使用有头模式 3) 更换 IP 4) 等待 10+ 分钟后重试")
                return 4

        if screenshot:
            await take_debug_screenshot(page, config, "03_logged_in")

        # 6. 保存登录态（供后续运行复用）
        await browser.save_storage_state()

        # 7. 等待购物车内容加载
        if not await wait_for_cart_load(page, config):
            if screenshot:
                await take_debug_screenshot(page, config, "04_load_timeout")
            return 3

        if screenshot:
            await take_debug_screenshot(page, config, "04_cart_loaded")

        # 7.5 缓慢滚动到底部，触发懒加载商品
        await scroll_to_bottom(page, config)
        if screenshot:
            await take_debug_screenshot(page, config, "05_scrolled")

        # 7.6 可选：保存完整 HTML 供离线分析
        if dump_html:
            await dump_page_html(page, config)

        # 8. 解析购物车商品
        current_items = await parse_cart_items(page)
        now = datetime.now(timezone.utc).isoformat()
        for item in current_items:
            item.snapshot_at = now

        logger.info("抓取完成: %d 个商品", len(current_items))

        # 9. 加载上次快照
        previous_items = load_snapshot(config.snapshot_path)

        # 10. 输出当前商品摘要
        print_summary(current_items)

        # 11. 对比差异 + 输出报告
        changes = compare_snapshots(previous_items, current_items)
        report_changes(changes, len(current_items))

        # 12. 保存当前快照
        save_snapshot(config.snapshot_path, current_items)

        return 0

    except KeyboardInterrupt:
        logger.info("用户中断")
        return 130
    except Exception as e:
        logger.exception("运行异常: %s", e)
        return 1
    finally:
        await browser.close()


def main(argv: list[str] | None = None) -> None:
    """程序入口点。"""
    args = parse_args(argv)

    config = load_config()
    if args.headless:
        config.headless = True

    setup_logging(config, verbose=args.verbose)

    logger.info("🚀 jd-tracker v0.2.1 启动")
    logger.info("配置: headless=%s, cart_url=%s", config.headless, config.cart_url)

    if args.dry_run:
        logger.info("模式: dry-run (不保存快照)")

    if args.screenshot:
        logger.info("调试模式: 每个步骤将保存截图到 %s/", config.log_dir)

    if args.dump_html:
        logger.info("将保存购物车页面 HTML 到 %s/", config.log_dir)

    exit_code = asyncio.run(run(config, screenshot=args.screenshot, dump_html=args.dump_html))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
