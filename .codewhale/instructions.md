# 开发笔记

> 此文件供 CodeWhale / 后续开发者阅读，用户可忽略。

## 当前状态

项目已可用，核心流程稳定：
- 登录 → 预热 → 购物车 → 风控检测 → 虚拟列表分段滚动 → JS 解析 → 快照对比

## 已知待改进

### 1. headless 模式在 macOS sandbox 下 crash (SIGSEGV)
- 当前 workaround：用户本地使用有头模式
- 原因：sandbox 限制了 Chromium headless shell 的内存访问
- 后续：CI 环境或 Linux 下 headless 可正常工作

### 2. 虚拟列表滚动可能不完整
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

## uv 缓存问题

当前 sandbox 环境下 `uv run` 因 `~/.cache/uv/sdists-v9/.git` 权限失败。
用户本地可直接 `uv run jd-tracker`。
开发时 workaround：`PYTHONPATH=src .venv/bin/python -m jd_tracker`
