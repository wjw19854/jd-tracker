"""配置管理。

支持通过环境变量覆盖默认配置，前缀 JD_TRACKER_。
例如：JD_TRACKER_HEADLESS=true 会覆盖 headless 字段。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    """返回项目根目录（pyproject.toml 所在目录）。"""
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class Config:
    """全局配置。"""

    # --- 浏览器 ---
    headless: bool = field(
        default_factory=lambda: _env_bool("JD_TRACKER_HEADLESS", False)
    )
    # 浏览器 channel：chrome（系统 Chrome）| ""（Playwright 默认 Chromium）
    chrome_channel: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_CHROME_CHANNEL", "")
    )
    # CDP 连接地址（如 http://localhost:9222），非空时优先使用 CDP 连接
    cdp_url: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_CDP_URL", "")
    )
    browser_timeout_ms: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_BROWSER_TIMEOUT_MS", 30_000)
    )
    # Playwright storage_state 文件路径（持久化登录态）
    storage_state_path: str = field(
        default_factory=lambda: os.environ.get(
            "JD_TRACKER_STORAGE_STATE", str(_project_root() / "data" / "auth.json")
        )
    )

    # --- 登录 ---
    login_max_retries: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_LOGIN_MAX_RETRIES", 30)
    )
    login_wait_seconds: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_LOGIN_WAIT_SECONDS", 30)
    )

    # --- 购物车 ---
    cart_url: str = field(
        default_factory=lambda: os.environ.get(
            "JD_TRACKER_CART_URL", "https://cart.jd.com/cart_index"
        )
    )
    cart_load_timeout_ms: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_CART_LOAD_TIMEOUT_MS", 30_000)
    )
    cart_parse_timeout_ms: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_CART_PARSE_TIMEOUT_MS", 10_000)
    )

    # --- 数据 ---
    data_dir: str = field(
        default_factory=lambda: os.environ.get(
            "JD_TRACKER_DATA_DIR", str(_project_root() / "data")
        )
    )
    log_dir: str = field(
        default_factory=lambda: os.environ.get(
            "JD_TRACKER_LOG_DIR", str(_project_root() / "logs")
        )
    )

    # --- 网络重试 ---
    network_retries: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_NETWORK_RETRIES", 2)
    )
    network_retry_delay_seconds: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_NETWORK_RETRY_DELAY_SECONDS", 5)
    )

    # --- 风控重试 ---
    risk_control_max_retries: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_RISK_CONTROL_MAX_RETRIES", 2)
    )
    risk_control_retry_delay_seconds: int = field(
        default_factory=lambda: _env_int("JD_TRACKER_RISK_CONTROL_RETRY_DELAY_SECONDS", 300)
    )

    # --- 随机抖动 ---
    jitter_ratio: float = field(
        default_factory=lambda: _env_float("JD_TRACKER_JITTER_RATIO", 0.3)
    )

    # --- 通知（v0.3.0）---
    notify_enabled: bool = field(
        default_factory=lambda: _env_bool("JD_TRACKER_NOTIFY_ENABLED", False)
    )
    notify_pushplus_token: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_NOTIFY_PUSHPLUS_TOKEN", "")
    )
    notify_pushplus_topic: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_NOTIFY_PUSHPLUS_TOPIC", "")
    )
    notify_price_drop_only: bool = field(
        default_factory=lambda: _env_bool("JD_TRACKER_NOTIFY_PRICE_DROP_ONLY", True)
    )
    # 预留：webhook 扩展点
    notify_webhook_url: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_NOTIFY_WEBHOOK_URL", "")
    )
    notify_webhook_type: str = field(
        default_factory=lambda: os.environ.get("JD_TRACKER_NOTIFY_WEBHOOK_TYPE", "")
    )

    @property
    def snapshot_path(self) -> str:
        """购物车快照文件路径。"""
        return str(Path(self.data_dir) / "cart_snapshot.jsonl")

    @property
    def log_path(self) -> str:
        """日志文件路径。"""
        return str(Path(self.log_dir) / "jd_tracker.log")

    def ensure_dirs(self) -> None:
        """确保数据目录和日志目录存在。"""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def load_config() -> Config:
    """加载配置（从默认值 + 环境变量）。"""
    return Config()
