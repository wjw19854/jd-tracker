"""购物车商品信息解析。

从 DOM 中提取商品列表（CartItem），支持多策略回退。
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation

from playwright.async_api import Page

from jd_tracker.models import CartItem

logger = logging.getLogger(__name__)


def _clean_price(raw: str) -> Decimal:
    """清洗价格字符串，转为 Decimal。

    处理：¥ 符号、千分位逗号、空格、促销标签等。
    """
    if not raw:
        return Decimal("0")
    cleaned = raw.replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "").strip()
    match = re.search(r"[\d.]+", cleaned)
    if not match:
        return Decimal("0")
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return Decimal("0")


async def _parse_from_js_state(page: Page) -> list[CartItem] | None:
    """策略1：从页面 JS 全局变量中提取购物车数据。

    先扫描 window 上所有属性名，找出包含 cart/sku 关键词的变量。
    """
    try:
        var_names_json = await page.evaluate("""
            () => {
                const candidates = [];
                for (const key of Object.keys(window)) {
                    try {
                        if (key.length > 2 && key.length < 60 && window[key] !== null && typeof window[key] === 'object') {
                            const kl = key.toLowerCase();
                            if (kl.includes('cart') || kl.includes('sku') || kl.includes('ware')
                                || kl.includes('item') || kl.includes('state') || kl.includes('nuxt')) {
                                candidates.push(key);
                            }
                        }
                    } catch(e) {}
                }
                const known = ['__jd_cart_data__', '__cartData', 'cartData', '__INITIAL_STATE__', '__NUXT__'];
                for (const k of known) {
                    if (!candidates.includes(k)) candidates.push(k);
                }
                return JSON.stringify(candidates.slice(0, 30));
            }
        """)
        candidates = json.loads(var_names_json)
        logger.debug("发现 %d 个候选 JS 变量: %s", len(candidates), candidates[:10])
    except Exception:
        candidates = [
            "__jd_cart_data__", "__cartData", "cartData",
            "__INITIAL_STATE__", "__NUXT__",
        ]

    for var_name in candidates:
        try:
            raw = await page.evaluate(f"""
                () => {{
                    try {{
                        if (window['{var_name}'] !== undefined && window['{var_name}'] !== null) {{
                            return JSON.stringify(window['{var_name}']);
                        }}
                    }} catch(e) {{}}
                    return null;
                }}
            """)
            if raw:
                data = json.loads(raw)
                items = _extract_items_from_js_object(data)
                if items:
                    logger.info("从 window.%s 中提取到 %d 个商品", var_name, len(items))
                    return items
        except Exception as e:
            logger.debug("从 window.%s 提取失败: %s", var_name, e)
            continue

    return None


def _extract_items_from_js_object(data: object) -> list[CartItem]:
    """从 JS 对象中递归提取商品信息。"""

    def _find_sku_lists(obj: object, depth: int = 0) -> list[list[dict]]:
        if depth > 5:
            return []
        if isinstance(obj, list):
            if len(obj) > 0 and all(isinstance(x, dict) for x in obj):
                sample = obj[0]
                if isinstance(sample, dict):
                    keys = {k.lower() for k in sample.keys()}
                    if "skuid" in keys or "sku_id" in keys or "id" in keys:
                        return [obj]
            results = []
            for item in obj:
                results.extend(_find_sku_lists(item, depth + 1))
            return results
        elif isinstance(obj, dict):
            results = []
            for v in obj.values():
                results.extend(_find_sku_lists(v, depth + 1))
            return results
        return []

    sku_lists = _find_sku_lists(data)
    items: list[CartItem] = []

    for sku_list in sku_lists:
        for entry in sku_list:
            if not isinstance(entry, dict):
                continue
            try:
                sku_id = str(_get_field(entry, "skuid", "sku_id", "id", "itemId", "wareId"))
                name = str(_get_field(entry, "name", "title", "wareName", "itemName"))
                model = str(_get_field(entry, "model", "colorSize", "spec", "specification"))
                qty = _get_field(entry, "quantity", "num", "count", "qty")
                price_raw = _get_field(entry, "price", "jdPrice", "realPrice", "oprice")

                if not sku_id or not name:
                    continue

                item = CartItem(
                    sku_id=sku_id,
                    name=name,
                    model=model or "",
                    quantity=int(qty) if qty else 1,
                    price=_clean_price(str(price_raw)) if price_raw else Decimal("0"),
                )
                items.append(item)
            except Exception:
                continue

    return items


def _get_field(d: dict, *keys: str) -> object:
    """从字典中获取第一个存在的字段（大小写不敏感）。"""
    for key in keys:
        if key in d:
            return d[key]
    lower_map = {k.lower(): v for k, v in d.items()}
    for key in keys:
        if key.lower() in lower_map:
            return lower_map[key.lower()]
    return None


async def _parse_from_dom(page: Page) -> list[CartItem]:
    """策略2：从 DOM 中逐行解析商品信息（旧版京东兼容）。"""
    items: list[CartItem] = []

    row_selectors = [
        ".cart-body .item-item",
        ".item-list .item",
        '[class*="cart-item"]',
        '[data-sku]',
    ]

    rows = []
    for selector in row_selectors:
        try:
            elements = page.locator(selector)
            count = await elements.count()
            if count > 0:
                logger.debug("DOM 选择器 '%s' 命中 %d 个元素", selector, count)
                rows = [elements.nth(i) for i in range(count)]
                break
        except Exception:
            continue

    if not rows:
        logger.warning("未找到购物车商品 DOM 元素")
        return items

    for row in rows:
        try:
            item = await _parse_single_row(row)
            if item and item.sku_id:
                items.append(item)
        except Exception as e:
            logger.debug("解析单个商品行失败: %s", e)
            continue

    return items


async def _parse_single_row(row) -> CartItem | None:
    """从单个 DOM 行解析一个 CartItem。"""
    sku_id = ""
    for attr in ["data-sku", "data-skuid", "data-id", "data-spu"]:
        try:
            val = await row.get_attribute(attr)
            if val:
                sku_id = val
                break
        except Exception:
            continue

    name = ""
    name_selectors = [
        ".item-name a",
        ".item-title a",
        '[class*="name"] a',
        '[class*="title"] a',
        ".p-name a",
        "a[href*='item.jd.com']",
    ]
    for sel in name_selectors:
        try:
            el = row.locator(sel).first
            if await el.count() > 0:
                name = (await el.inner_text()).strip()
                if name:
                    break
        except Exception:
            continue

    model = ""
    model_selectors = [
        ".item-model",
        ".item-sku",
        '[class*="model"]',
        '[class*="spec"]',
        '[class*="attr"]',
        ".p-extra",
    ]
    for sel in model_selectors:
        try:
            el = row.locator(sel).first
            if await el.count() > 0:
                model = (await el.inner_text()).strip()
                if model:
                    break
        except Exception:
            continue

    quantity = 1
    qty_selectors = [
        '.quantity input[type="text"]',
        '.quantity input',
        '[class*="quantity"] input',
        '.buy-num input',
        '.item-quantity input',
    ]
    for sel in qty_selectors:
        try:
            el = row.locator(sel).first
            if await el.count() > 0:
                val = await el.get_attribute("value") or await el.input_value()
                if val and val.strip().isdigit():
                    quantity = int(val.strip())
                    break
        except Exception:
            continue

    price = Decimal("0")
    price_selectors = [
        ".item-price .price",
        '[class*="price"]',
        ".p-price",
        ".item-total .price",
        '[class*="total"] .price',
    ]
    for sel in price_selectors:
        try:
            el = row.locator(sel).first
            if await el.count() > 0:
                raw = (await el.inner_text()).strip()
                price = _clean_price(raw)
                if price > 0:
                    break
        except Exception:
            continue

    if not sku_id or not name:
        return None

    return CartItem(
        sku_id=sku_id,
        name=name,
        model=model,
        quantity=quantity,
        price=price,
    )


async def _parse_via_js(page: Page) -> list[CartItem]:
    """策略3：用 JS 直接在页面内查找购物车 DOM。

    适配京东新版购物车（React + CSS Modules + data-skuuuid）。
    """
    try:
        raw = await page.evaluate("""() => {
    var items = [];
    var seen = {};

    function getSkuId(row) {
        var link = row.querySelector('a[href*="item.jd.com"]');
        if (link) {
            var m = link.href.match(/item\\.jd\\.com\\/(\\d+)\\.html/);
            if (m) return m[1];
        }
        var dcEl = row.querySelector('[data-click*="main_skuid"]');
        if (dcEl) {
            var dc = dcEl.getAttribute('data-click') || '';
            var m2 = dc.match(/"main_skuid"\\s*:\\s*"?(\\d+)"?/);
            if (m2) return m2[1];
        }
        var ds = row.getAttribute('data-sku');
        if (ds) return ds;
        return '';
    }

    function getName(row) {
        var link = row.querySelector('a[href*="item.jd.com"]');
        if (link) {
            var title = link.getAttribute('title') || '';
            if (title.trim()) return title.trim();
            return (link.textContent || '').trim();
        }
        return '';
    }

    function getModel(row) {
        var spans = row.querySelectorAll('[class*="extra-select"] span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].textContent || '').trim();
            if (t === '\u5546\u54c1' && i + 1 < spans.length) {
                return (spans[i + 1].textContent || '').trim();
            }
        }
        return '';
    }

    function getQty(row) {
        var inputs = row.querySelectorAll('input');
        for (var j = 0; j < inputs.length; j++) {
            var v = inputs[j].value || inputs[j].getAttribute('value') || '';
            var n = parseInt(v, 10);
            if (n > 0 && n < 1000) return n;
        }
        return 1;
    }

    function getPrice(row) {
        var priceEl = row.querySelector('[class*="price-normal"], [class*="price-container"]');
        var text = '';
        if (priceEl) text = (priceEl.textContent || '').trim();
        if (!text) text = (row.textContent || '').replace(/\\s+/g, ' ');
        var pm = text.match(/[\\uffe5\\u00a5]\\s*([\\d,]+\\.[\\d]+)/);
        if (pm) return pm[1].replace(/,/g, '');
        var pm2 = text.match(/([\\d,]+\\.[\\d]+)/);
        if (pm2) return pm2[1].replace(/,/g, '');
        return '';
    }

    function isOutOfStock(row) {
        var t = (row.textContent || '');
        if (t.indexOf('无货') >= 0 || t.indexOf('到货通知') >= 0) return true;
        if (t.indexOf('下架') >= 0 || t.indexOf('失效') >= 0) return true;
        if (t.indexOf('预约') >= 0 || t.indexOf('抢光了') >= 0) return true;
        if (row.querySelector('[class*="is-disabled"]')) return true;
        return false;
    }

    var rows = document.querySelectorAll('[class*="product-item"]');
    for (var r = 0; r < rows.length; r++) {
        try {
            var sku = getSkuId(rows[r]);
            var name = getName(rows[r]);
            if (!sku || !name || seen[sku]) continue;
            seen[sku] = 1;
            items.push({
                sku_id: sku,
                name: name,
                model: getModel(rows[r]),
                quantity: getQty(rows[r]),
                price_text: getPrice(rows[r]),
                in_stock: isOutOfStock(rows[r]) ? false : true
            });
        } catch(e) {}
    }

    if (items.length === 0) {
        var oldRows = document.querySelectorAll('[data-sku]');
        for (var o = 0; o < oldRows.length; o++) {
            try {
                var osku = oldRows[o].getAttribute('data-sku') || '';
                if (!osku || seen[osku]) continue;
                seen[osku] = 1;
                var olink = oldRows[o].querySelector('a[href*="item.jd.com"]');
                var oname = olink ? ((olink.getAttribute('title') || olink.textContent || '').trim()) : '';
                if (!oname) continue;
                items.push({
                    sku_id: osku,
                    name: oname,
                    model: '',
                    quantity: 1,
                    price_text: getPrice(oldRows[o]),
                    in_stock: isOutOfStock(oldRows[o]) ? false : true
                });
            } catch(e) {}
        }
    }

    return JSON.stringify(items);
}""")
        data = json.loads(raw)
        items: list[CartItem] = []
        for d in data:
            if isinstance(d, dict):
                items.append(CartItem(
                    sku_id=str(d.get("sku_id", "")),
                    name=str(d.get("name", "")),
                    model=str(d.get("model", "")),
                    quantity=int(d.get("quantity", 1)),
                    price=_clean_price(str(d.get("price_text", "0"))),
                ))
        if items:
            logger.info("JS DOM 提取到 %d 个商品", len(items))
        return items
    except Exception as e:
        logger.debug("JS DOM 解析失败: %s", e)
        return []


async def parse_cart_items(page: Page) -> list[CartItem]:
    """解析购物车商品列表。

    多策略级联：
    1. JS 全局变量提取（window 上的数据对象）
    2. JS DOM 提取（新版 React + 旧版 data-sku）
    3. Python DOM 解析（locator 选择器，旧版兼容）
    """
    items = await _parse_from_js_state(page)
    if items:
        return items

    logger.info("JS 变量提取失败，尝试 JS DOM 提取")
    items = await _parse_via_js(page)
    if items:
        return items

    logger.info("JS DOM 提取失败，回退到 Python DOM 解析")
    items = await _parse_from_dom(page)
    logger.info("Python DOM 解析完成，提取到 %d 个商品", len(items))
    return items
