# 开发笔记

> 此文件供 CodeWhale / 后续开发者阅读，用户可忽略。

## 当前状态

项目已可用，核心流程稳定：
- 登录 → 预热 → 购物车 → 风控检测 → 虚拟列表分段滚动 → JS 解析 → 快照对比

## v0.2.0 反检测加固（2026-05-27）

针对京东风控触发验证码的问题，实施了五层反检测加固：

### 1. 浏览器指纹随机化（browser.py）
- **随机 UA 池**：6 个真实 Chrome macOS UA（128-133），每次启动随机选用
- **随机 viewport**：4 种常见 Mac 分辨率（1440x900, 1280x800, 1680x1050, 1366x768）
- **二次 webdriver 覆盖**：在 playwright-stealth 之后注入额外 JS，覆盖 `navigator.webdriver`、`permissions.query` 等 API
- **验证机制**：启动后立即读取 `navigator.webdriver` 确认覆盖成功，失败时输出 WARNING

### 2. 人类行为模拟（cart.py）
- **预热增强**：首页访问后增加鼠标移动到页面中央（steps=5-15）、平滑滚动 + 小幅回滚
- **`human_like_idle()`**：在登录等待和风控重试期间替代纯 `sleep`，间歇性地微调滚动 ±80px 或移动鼠标
- **操作间隔随机化**：每次空闲操作间隔 3-8 秒（带 ±30% 抖动）

### 3. 时间随机化（全局）
- **`_jitter(base, ratio)`** 工具函数：所有 `asyncio.sleep` 替换为 `_jitter`，默认 ±30% 偏移
- 预热等待、购物车导航前后、滚动跳转等待、登录重试间隔全部随机化

### 4. HTTP 请求头增强（browser.py）
- 补全真实浏览器头：`Accept`、`Accept-Encoding`、`Cache-Control`
- 动态构造 `Sec-CH-UA` / `Sec-CH-UA-Platform` / `Sec-CH-UA-Mobile`
- `Upgrade-Insecure-Requests`

### 5. 风控重试策略（__main__.py + config.py）
- 检测到验证码后不再立即退出，而是等待 120s（可配置）后重试
- 重试次数默认 2 次（`JD_TRACKER_RISK_CONTROL_MAX_RETRIES`）
- 等待期间调用 `human_like_idle` 模拟轻度浏览

### 6. 代码去重（login.py）
- 删除 `login._detect_risk` 和重复的 `_RISK_KEYWORDS`
- 统一引用 `cart.detect_risk_control`

### 新增配置项
| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `JD_TRACKER_RISK_CONTROL_MAX_RETRIES` | `2` | 风控检测后重试次数 |
| `JD_TRACKER_RISK_CONTROL_RETRY_DELAY_SECONDS` | `300` | 风控重试等待间隔 |
| `JD_TRACKER_JITTER_RATIO` | `0.3` | 随机抖动比例 |
| `JD_TRACKER_CHROME_CHANNEL` | (空) | 浏览器 channel（`chrome`=系统 Chrome，空=默认 Chromium） |
| `JD_TRACKER_CDP_URL` | (空) | CDP 连接地址，非空时优先使用（备选方案） |
| `JD_TRACKER_LOGIN_MAX_RETRIES` | `30` | 登录检测最大重试次数（v0.2.0 从 5 上调） |

## 已知待改进

### 1. headless 模式在 macOS sandbox 下 crash (SIGSEGV)
- 当前 workaround：用户本地使用有头模式
- 原因：sandbox 限制了 Chromium headless shell 的内存访问
- 后续：CI 环境或 Linux 下 headless 可正常工作

### 2. 系统 Chrome navigator.webdriver 检测逻辑（已修复 v0.2.0）
- JS `undefined` → Python `None`，之前误报 WARNING，已修正判断逻辑

### 2.5 page.route 反检测效果（v0.2.1）
- `page.route("**/*")` 启用 CDP Fetch 域，改变底层网络栈，意外帮助绕过京东检测
- 现已始终启用，不再依赖 `--dump-html` 参数
- 网络日志降为 DEBUG 级别

### 3. 虚拟列表滚动可能不完整
- 京东购物车使用 React 虚拟列表，当前用分段跳转（10 段 + 反向）覆盖
- 如果商品超过 ~200 件可能需要增加段数
- 日志中 `最大高度` 可以指示是否正确到达底部

### 3. 无货检测依赖 DOM 文本关键词
- 当前检测：`无货`、`到货通知`、`下架`、`失效`、`预约`、`抢光了`、`is-disabled` class
- 京东可能更换文案，需要持续维护

### 4. CSS Modules hash 后缀可能变化
- 新版京东购物车 class 名类似 `_product-item_88ueb_1`，其中 `88ueb` 是 CSS Modules hash
- 当前用 `[class*="product-item"]` 属性选择器匹配，相对稳定但如果京东换了组件命名规则需要更新
- `_parse_via_js` 中的 JS 函数已考虑了新旧版兼容

### 5. `wait_for_cart_load` 不阻塞但也不准确
- 目前所有选择器都 miss 京东新版购物车，直接靠 URL 判断
- 未来可以基于实际 DOM 特征（如 `.cartNum` 中的数字）来确认

## 解析策略

parser.py 三级回退：
1. **JS 全局变量** — 扫描 `window` 上含 cart/sku 关键词的变量，递归提取
2. **JS DOM 提取** — `[class*="product-item"]` 容器 + 链接/标题/价格正则
3. **Python DOM** — Playwright locator 选择器（旧版京东兼容）

## 测试覆盖

| 文件 | 内容 |
|------|------|
| `test_models.py` | CartItem 序列化/反序列化、CartSnapshot 索引 |
| `test_storage.py` | JSONL 读写、容错、覆盖 |
| `test_monitor.py` | 12 种变化场景（增/删/价涨/价跌/量变/库存/组合/边界） |
| `test_parser_js.py` | 提取所有 page.evaluate 中的 JS，验证括号平衡 + Node.js 语法检查 |

## Docker 部署（v0.2.1）

- 使用 Playwright 官方 Python 镜像 (`mcr.microsoft.com/playwright/python:v1.55.0-noble`)
- 镜像已包含 Chromium + 系统依赖，不再需要系统 Chrome
- `docker/Dockerfile`：构建镜像，安装 playwright-stealth
- `docker/docker-compose.yml`：数据卷挂载、环境变量、restart 策略
- `docker/entrypoint.sh`：定时循环脚本，支持 `JD_TRACKER_INTERVAL` 配置
- 首次使用需在有头模式下获取 `auth.json`，然后复制到服务器挂载的 `data/` 目录

## uv 缓存问题

当前 sandbox 环境下 `uv run` 因 `~/.cache/uv/sdists-v9/.git` 权限失败。
用户本地可直接 `uv run jd-tracker`。
开发时 workaround：`PYTHONPATH=src .venv/bin/python -m jd_tracker`
