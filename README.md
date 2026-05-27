# jd-tracker

京东购物车价格监控工具。使用 Playwright 自动化浏览器，抓取购物车商品列表，对比历史快照检测价格波动和商品变化。

## 功能

- 🛒 自动抓取京东购物车商品列表（ID、名称、型号、数量、可成交价）
- 📊 对比历史快照，检测价格波动、商品增减、数量变化
- 🏪 识别无货/预约/下架/失效等不可购买状态
- 🔐 智能登录检测，未登录时提示用户手动登录并等待重试
- 🛡️ 多层反检测加固（随机 UA、viewport 随机化、webdriver 覆盖、人类行为模拟、请求头伪装）
- 🧠 登录等待期间模拟轻度浏览，防止长时间无操作触发风控
- 🔄 风控检测后自动等待重试，而非立即退出
- 📜 分段跳转滚动覆盖虚拟列表，确保懒加载商品全部渲染
- 💾 JSONL 文件持久化快照数据
- 📝 结构化日志输出（控制台 + 文件）

## 反检测加固

v0.2.0 起引入五层反检测策略，降低京东风控触发概率：

| 层级 | 措施 | 位置 |
|------|------|------|
| 浏览器指纹 | 随机 UA 池（6 个真实 Chrome macOS UA）、随机 viewport（4 种常见分辨率）、webdriver 二次覆盖验证 | `browser.py` |
| 行为模拟 | 预热阶段鼠标移动 + 平滑滚动、登录等待期间间歇性轻量交互 | `cart.py` → `human_like_idle()` |
| 时间随机化 | 所有等待操作加 ±30% 随机抖动（`_jitter`），登录重试间隔随机化 | `cart.py`, `login.py` |
| HTTP 头伪装 | 补全 Accept / Sec-CH-UA / Sec-CH-UA-Platform / Upgrade-Insecure-Requests | `browser.py` |
| 风控响应 | 检测到验证码后等待重试（默认 2 次 × 120s），期间模拟轻度浏览 | `__main__.py` |

## 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- Playwright 浏览器

## 安装

```bash
# 克隆项目
git clone <repo-url> jd-tracker
cd jd-tracker

# 使用 uv 安装依赖
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium
```

## 使用方法

### 基本用法

```bash
# 运行一次购物车监控（有头模式，会在桌面打开浏览器窗口）
uv run jd-tracker
```

### 命令行选项

```
usage: jd-tracker [-h] [--headless] [--verbose] [--dry-run] [--screenshot] [--dump-html]

京东购物车价格监控工具

options:
  --headless    无头模式运行浏览器（需要已通过 storage_state 持久化登录态）
  --verbose, -v 启用 DEBUG 级别日志
  --dry-run     仅抓取并显示当前购物车，不保存快照
  --screenshot   在每个关键步骤保存截图到 logs/ 目录，用于调试
  --dump-html    保存购物车页面完整 HTML 到 logs/cart_page_dump.html，用于分析 DOM 结构
```

### 环境变量

所有配置都可以通过环境变量覆盖（前缀 `JD_TRACKER_`）：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `JD_TRACKER_HEADLESS` | `false` | 无头模式 |
| `JD_TRACKER_CHROME_CHANNEL` | (空) | 浏览器 channel（`chrome`=系统 Chrome，空=默认 Chromium） |
| `JD_TRACKER_CDP_URL` | (空) | CDP 连接地址（如 `http://localhost:9222`），非空时优先使用 |
| `JD_TRACKER_CART_URL` | `https://cart.jd.com/cart_index` | 购物车 URL |
| `JD_TRACKER_STORAGE_STATE` | `data/auth.json` | 登录态持久化文件 |
| `JD_TRACKER_LOGIN_MAX_RETRIES` | `30` | 登录检测最大重试次数 |
| `JD_TRACKER_LOGIN_WAIT_SECONDS` | `30` | 登录等待间隔（秒） |
| `JD_TRACKER_RISK_CONTROL_MAX_RETRIES` | `2` | 风控检测后重试次数 |
| `JD_TRACKER_RISK_CONTROL_RETRY_DELAY_SECONDS` | `300` | 风控重试等待间隔（秒） |
| `JD_TRACKER_JITTER_RATIO` | `0.3` | 随机抖动比例（0=无抖动，0.5=±50%） |
| `JD_TRACKER_DATA_DIR` | `data/` | 数据目录 |
| `JD_TRACKER_LOG_DIR` | `logs/` | 日志目录 |
| `JD_TRACKER_NETWORK_RETRIES` | `2` | 网络请求重试次数 |

### 定时运行（cron）

```bash
# 每 30 分钟运行一次（建议间隔不低于 15 分钟以降低风控风险）
*/30 * * * * cd /path/to/jd-tracker && uv run jd-tracker --headless >> logs/cron.log 2>&1
```

## 数据文件

- `data/cart_snapshot.jsonl` — 最新购物车快照（JSON Lines 格式，每行一个商品）
- `data/auth.json` — Playwright storage_state（登录态持久化，可供 --headless 模式复用）
- `logs/jd_tracker.log` — 运行日志
- `logs/cart_page_dump.html` — `--dump-html` 时保存的页面 HTML
- `logs/dom_analysis.json` — DOM 分析工具的输出
- `logs/screenshot_*.png` — `--screenshot` 时保存的调试截图

## 变化检测规则

| 变化类型 | 检测方式 |
|----------|----------|
| 价格波动 | 相同 `sku_id`，`price` 变化 |
| 商品新增 | 上次快照不存在的 `sku_id` |
| 商品移除 | 当前快照不存在的 `sku_id` |
| 数量变化 | 相同 `sku_id`，`quantity` 变化 |
| 下架/无货 | `in_stock` 从 `true` → `false` |
| 恢复有货 | `in_stock` 从 `false` → `true` |

## 运行测试

```bash
uv run pytest
```

## 调试工具

```bash
# DOM 分析：运行后输出页面结构到 logs/dom_analysis.json + logs/cart_page_dump.html
uv run python tools/debug_dom.py
```

## 项目结构

```
jd-tracker/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── src/jd_tracker/
│   ├── __init__.py
│   ├── __main__.py         # CLI 入口 + 主流程编排（含风控重试策略）
│   ├── config.py           # 配置管理（dataclass + 环境变量覆盖 + 反检测参数）
│   ├── models.py           # 数据模型（CartItem, ChangeRecord, CartSnapshot）
│   ├── browser.py          # Playwright 浏览器管理 + 多层反检测（UA/viewport/webdriver/HTTP头）
│   ├── login.py            # 登录检测（多策略 + 风控识别 + 随机延迟重试）
│   ├── cart.py             # 购物车导航、预热、行为模拟（human_like_idle）、虚拟列表分段滚动
│   ├── parser.py           # 商品解析（JS 变量 → JS DOM → Python DOM 三级回退）
│   ├── storage.py          # JSONL 文件读写
│   └── monitor.py          # 快照对比引擎 + 变化报告
├── tests/
│   ├── test_models.py      # 数据模型序列化
│   ├── test_storage.py     # JSONL 读写容错
│   ├── test_monitor.py     # 12 种对比场景
│   └── test_parser_js.py   # 嵌入 JS 语法验证（括号平衡 + Node.js --check）
├── tools/
│   └── debug_dom.py        # DOM 结构分析调试脚本
├── data/                   # 运行时数据（gitignore）
└── logs/                   # 日志文件（gitignore）
```

## 无头模式运行（headless）

```
uv run jd-tracker --headless
```

无头模式运行的前提是已经有头模式登录了京东账号，且登录态持久化到了 `data/auth.json` 文件中。

如果要在服务器托管运行，需要先将 `data/auth.json` 文件复制到 `data/` 目录下，即可在无头模式下运行。

## Docker 部署

项目包含完整的 Docker 配置，支持一键部署到服务器。详细说明见 [`docker/README.md`](docker/README.md)。

### 快速启动

```bash
# 1. 本地有头模式登录一次，获取 auth.json
uv run jd-tracker

# 2. 构建并启动
cd docker
docker compose up -d

# 3. 查看日志
docker compose logs -f
```

### 构建并推送 Docker 镜像

```bash
docker build -t yourusername/jd-tracker:latest -f docker/Dockerfile .
docker push yourusername/jd-tracker:latest
```

配置项通过 `docker-compose.yml` 中的环境变量设置（前缀 `JD_TRACKER_`），详见上方环境变量表。

