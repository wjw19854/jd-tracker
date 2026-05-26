"""验证 parser.py 中嵌入的 JavaScript 代码语法正确。"""

from __future__ import annotations

import ast
import re
import subprocess
import textwrap
from pathlib import Path


def _extract_js_blocks(source: str) -> list[tuple[str, int, str]]:
    """从 Python 源码中提取所有 page.evaluate() 调用中的 JS 代码块。

    Returns:
        [(label, start_line_number, js_code), ...]
    """
    tree = ast.parse(source)
    blocks = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            # 匹配 page.evaluate(...) 调用
            if isinstance(node.func, ast.Attribute) and node.func.attr == "evaluate":
                if node.args:
                    arg = node.args[0]
                    # 只处理字符串字面量（忽略 f-string 等）
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        label = f"line {arg.lineno}"
                        blocks.append((label, arg.lineno, arg.value))
            self.generic_visit(node)

    Visitor().visit(tree)
    return blocks


def _check_braces(js_code: str) -> tuple[bool, str]:
    """检查 JS 代码的 {}、()、[] 是否平衡。"""
    stack: list[str] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    in_string = False
    string_char = ""
    in_regex = False
    in_single_comment = False
    in_multi_comment = False

    for i, ch in enumerate(js_code):
        # 处理注释
        if not in_string and not in_regex:
            if ch == "/" and i + 1 < len(js_code):
                if js_code[i + 1] == "/" and not in_multi_comment:
                    in_single_comment = True
                    continue
                if js_code[i + 1] == "*" and not in_single_comment:
                    in_multi_comment = True
                    continue

        if in_single_comment:
            if ch == "\n":
                in_single_comment = False
            continue

        if in_multi_comment:
            if ch == "*" and i + 1 < len(js_code) and js_code[i + 1] == "/":
                in_multi_comment = False
            continue

        # 处理字符串
        if not in_regex and ch in ('"', "'", "`") and (i == 0 or js_code[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char:
                in_string = False

        if in_string or in_regex:
            continue

        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values():
            if not stack:
                return False, f"多余的 '{ch}' (位置 {i})"
            expected = stack.pop()
            if expected != ch:
                return False, f"期望 '{expected}' 但遇到 '{ch}' (位置 {i})"

    if stack:
        return False, f"未闭合的 {stack}"
    return True, "OK"


def _check_js_syntax(js_code: str, label: str) -> None:
    """Helper：检查一段 JS 代码的语法。"""
    # 如果是箭头函数包装的，提取内部
    code = js_code.strip()

    # 包裹成可被 node 解析的语句
    wrapped = f"const __fn = {code};\n"

    # 括号检查
    ok, msg = _check_braces(code)
    if not ok:
        raise AssertionError(f"{label}: 括号不平衡 - {msg}")


class TestParserJsBraces:
    """验证 parser.py 中所有 JS 代码的括号平衡。"""

    def _get_source(self) -> str:
        path = Path(__file__).parent.parent / "src" / "jd_tracker" / "parser.py"
        return path.read_text(encoding="utf-8")

    def test_all_js_blocks_balanced(self):
        source = self._get_source()
        blocks = _extract_js_blocks(source)
        assert len(blocks) > 0, "未找到任何 page.evaluate() 调用"

        for label, lineno, js in blocks:
            ok, msg = _check_braces(js)
            assert ok, f"{label}: 括号不平衡 - {msg}"

    def test_via_js_function_syntax(self):
        """核心测试：_parse_via_js 中的 JS 代码在 Node.js 中语法正确。"""
        source = self._get_source()
        blocks = _extract_js_blocks(source)

        # 找到最长的 JS 块（通常是 _parse_via_js）
        via_js_code = None
        for label, lineno, js in blocks:
            if "product-item" in js or "data-sku" in js:
                via_js_code = js
                break

        if via_js_code is None:
            # 没找到特征字符串，取最长的
            via_js_code = max(blocks, key=lambda b: len(b[2]))[2] if blocks else None

        assert via_js_code is not None, "未找到 _parse_via_js 的 JS 代码"

        # 括号检查
        ok, msg = _check_braces(via_js_code)
        assert ok, f"括号不平衡: {msg}"

        # Node.js 语法检查（可选，依赖 Node 环境）
        wrapped = f"const __fn = {via_js_code};\n"
        try:
            result = subprocess.run(
                ["node", "--check", "--input-type=module"],
                input=wrapped,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"Node.js 语法检查失败:\n{result.stderr[:500]}"
                )
        except FileNotFoundError:
            pass  # 无 Node.js 环境，跳过


class TestJsBraceChecker:
    """括号检查器本身的单元测试。"""

    def test_balanced_simple(self):
        ok, _ = _check_braces("function f() { return 1; }")
        assert ok

    def test_unbalanced_missing_close(self):
        ok, msg = _check_braces("function f() { return 1;")
        assert not ok

    def test_unbalanced_extra_close(self):
        ok, msg = _check_braces("function f() { return 1; }}")
        assert not ok

    def test_strings_ignored(self):
        ok, _ = _check_braces('const x = "{" + "}";')
        assert ok

    def test_regex_ignored(self):
        ok, _ = _check_braces("const r = /{3}/;")
        assert ok

    def test_nested(self):
        ok, _ = _check_braces("if (a) { if (b) { return [1, {x: 2}]; } }")
        assert ok

    def test_single_line_comment_ignored(self):
        ok, _ = _check_braces("// { this is not a brace\nfunction f() { return 1; }")
        assert ok

    def test_multi_line_comment_ignored(self):
        ok, _ = _check_braces("/* { not a brace */ function f() { return 1; }")
        assert ok
