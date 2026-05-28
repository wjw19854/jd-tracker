# Changelog

All notable changes to this project will be documented in this file.

## [0.3.2] - 2026-05-28

- 调整docker时区为中国时区

## [0.3.1] - 2026-05-27

- 修正 docker compose 文件增加新环境变量选项及说明

## [0.3.0] - 2026-05-27

### 降价通知（PushPlus）

- 新增 `notifier.py`：`Notifier` 抽象基类 + `PushPlusNotifier` 实现 + `create_notifier` 工厂函数
- 检测到购物车价格下跌时，通过 PushPlus 推送微信通知
- 通知内容包含降价商品名称、型号、原价/现价、降幅金额和百分比
- 支持群组推送（`JD_TRACKER_NOTIFY_PUSHPLUS_TOPIC`）
- 框架预留 Webhook 扩展点（飞书/企业微信/钉钉群机器人）
- 零外部依赖，仅使用 Python 标准库 `urllib`

### 异常告警通知

- 四种异常场景自动推送告警：登录失败、风控拦截、购物车加载超时、购物车为空
- 每种异常每天最多发送 3 次（内存计数，进程重启后自动重置）
- 不启用通知时完全静默，不影响现有用户

### 新增配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `JD_TRACKER_NOTIFY_ENABLED` | `false` | 启用/关闭通知 |
| `JD_TRACKER_NOTIFY_PUSHPLUS_TOKEN` | (空) | PushPlus token |
| `JD_TRACKER_NOTIFY_PUSHPLUS_TOPIC` | (空) | PushPlus 群组编号 |
| `JD_TRACKER_NOTIFY_PRICE_DROP_ONLY` | `true` | 仅通知降价 |
| `JD_TRACKER_NOTIFY_WEBHOOK_URL` | (空) | Webhook URL（预留） |
| `JD_TRACKER_NOTIFY_WEBHOOK_TYPE` | (空) | Webhook 类型（预留） |

### 模型变更

- `ChangeRecord` 新增 `model` 字段（字符串，默认空），`monitor.py` 所有构造点同步更新

### 测试

- 新增 `tests/test_notifier.py`：9 个测试覆盖消息格式化、百分比精度、None/零值安全、JSON 结构验证

---

## [0.2.0] - 2026-05-27

### 反检测加固

针对京东风控触发验证码、购物车为空（Playwright Chromium 被后端识别）的问题，实施五层反检测加固。

#### 浏览器指纹随机化 (`browser.py`)
- 随机 UA 池：6 个真实 Chrome macOS UA（128-133），每次启动随机选用
- 随机 viewport：4 种常见 Mac 分辨率（1440x900, 1280x800, 1680x1050, 1366x768）
- 二次 webdriver 覆盖 + 增强 stealth JS（plugins/mimeTypes 假数据、WebGL 伪装、窗口尺寸匹配）
- `navigator.webdriver` 验证机制（None=undefined=覆盖成功，True=未覆盖）

#### 系统 Chrome (`browser.py` + `config.py`)
- 默认使用系统真实 Chrome（`channel="chrome"`），消除 Playwright 自带 Chromium 的指纹差异
- 系统 Chrome 不可用时自动回退到 Playwright 默认 Chromium
- CDP 连接备选方案（`JD_TRACKER_CDP_URL`）

#### 人类行为模拟 (`cart.py`)
- `warmup_browser` 增强：鼠标移动到页面中央 + 平滑滚动 + 小幅回滚
- 新增 `human_like_idle()`：间歇性微调滚动/移动鼠标，替代纯 `sleep`
- 登录等待和风控重试期间调用 `human_like_idle` 模拟轻度浏览

#### 时间随机化（全局）
- 新增 `_jitter(base, ratio)` 工具函数，所有 `asyncio.sleep` 替换为 ±30% 偏移
- 预热等待、购物车导航前后、滚动跳转等待、登录重试间隔全部随机化

#### HTTP 请求头修复 (`browser.py`)
- 移除了 `Accept-Encoding` 手动设置（让浏览器自动处理，避免解压冲突）
- 移除了 `Sec-CH-UA` 手动设置（让 Chromium 自行管理客户端提示头）
- 保留 `Accept`、`Accept-Language`、`Cache-Control`、`Upgrade-Insecure-Requests`

#### 风控重试策略 (`__main__.py` + `login.py` + `config.py`)
- 登录检测中触发风控：不再立即退出，等待后重试（默认 300s × 2 次）
- 登录后触发风控：不再立即退出，等待后重试
- 风控重试不消耗登录检测次数

#### CDP Fetch 反检测 (`browser.py` + `__main__.py`)
- `page.route("**/*")` 启用 CDP Fetch 域，改变底层网络栈，意外帮助绕过京东检测
- 始终启用（不再依赖 `--dump-html`），消除有/无参数的行为差异
- 网络日志降为 DEBUG 级别，`--verbose` 时可查看

#### 代码去重 (`login.py`)
- 删除 `login._detect_risk` 和重复的 `_RISK_KEYWORDS`
- 统一引用 `cart.detect_risk_control`

#### 配置变更 (`config.py`)
- `login_max_retries`: 5 → 30
- 新增 `risk_control_max_retries` (2)、`risk_control_retry_delay_seconds` (300)、`jitter_ratio` (0.3)
- 新增 `chrome_channel` (空=Chromium)、`cdp_url` (空)

#### 文档
- README.md 补充反检测加固说明、新增环境变量表
- .codewhale/instructions.md 更新开发笔记和已知问题
- 新增 CHANGELOG.md

---

## [0.2.1] - 2026-05-27

### Docker 部署

- 新增 `docker/Dockerfile`（基于 Playwright 官方 Python 镜像 `v1.60.0-noble`）
- 新增 `docker/docker-compose.yml`（数据卷挂载、restart 策略，卷映射到 compose 同级目录）
- 新增 `docker/entrypoint.sh`（定时循环 + `JD_TRACKER_INTERVAL` + `JD_TRACKER_ACTIVE_HOURS` 时间段控制）
- 新增 `docker/push.sh`（构建 + 打版本标签 + 推送到 Docker Hub）
- 新增 `docker/README.md`（服务器部署完整流程：scp 上传、首次 auth.json 导入、后续更新）

### 修复

- `chrome_channel` 默认回退为空字符串（Playwright 默认 Chromium）
  验证确认 `page.route` CDP Fetch 反检测在 Chromium 下同样有效，
  不再强制依赖系统 Chrome
- 网络日志降为 DEBUG 级别（避免正常模式刷屏）
- Dockerfile playwright 版本冲突修复（基础镜像 v1.55→v1.60）
- entrypoint.sh：修复 `bc` 缺失、`local` 语法错误，替换为纯 shell 算术
- docker-compose.yml：移除废弃的 `version` 字段

### 文档

- README.md 新增 Docker 部署章节
- .codewhale/instructions.md 补充 Docker 部署信息

---

## [0.1.0] - 2026-05-24

### 初始版本

- 购物车商品抓取（ID、名称、型号、数量、可成交价）
- 历史快照对比（价格波动、商品增减、数量变化、库存状态）
- 登录检测（多策略：URL 白名单 + 特征元素 + cookie）
- playwright-stealth 反检测 + 首页预热
- 风控自动识别（关键词匹配）
- 虚拟列表分段滚动覆盖 React 懒加载
- JSONL 快照持久化
- 结构化日志（控制台 + 文件）
- 多策略商品解析（JS 变量 → JS DOM → Python DOM 三级回退）
