"""test_sandbox.py — 5 条，纯沙箱安全检查 + 基本执行能力测试。"""
import pytest
import sys, os

# 确保能 import 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox.executor import execute_in_sandbox, ExecutionResult, _static_check

class TestStaticCheck:
    """5 条 AST 静态安全检查测试。"""

    def test_1_os_remove_banned(self):
        """禁止 os.remove → 返回 '禁止使用 os.remove()'。"""
        code = """import os\nos.remove('test.txt')"""
        result = _static_check(code)
        assert result is not None
        assert "os.remove" in result

    def test_2_requests_import_banned(self):
        """禁止 import requests → 返回 '禁止导入模块: requests'。"""
        code = """import requests\nr = requests.get('http://example.com')"""
        result = _static_check(code)
        assert result is not None
        assert "requests" in result

    def test_3_normal_pandas_code_passes(self):
        """正常的 pandas 代码（无危险模块）→ 静态检查通过 → 返回 None。"""
        code = """
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
print(df.describe())
result = df['a'].sum()
"""
        result = _static_check(code)
        assert result is None, f"正常代码不应被拦截: {result}"

    def test_4_missing_module_passes_syntax(self):
        """import 不存在的库 → AST 能 parse（返回 None），执行时才抛 ModuleNotFoundError。"""
        # _static_check 只做 AST parse + 黑名单扫描，不检查模块是否存在
        code = """import nonexistent_lib_xyz123\nprint('hello')"""
        result = _static_check(code)
        assert result is None  # 语法合法，没进黑名单，_static_check 通过

    def test_5_result_auto_extract(self):
        """代码成功执行 + 有 result 变量 → 沙箱自动打印 __RESULT_START__ / __RESULT_END__ 标记。"""
        code = """
result = "销售额为 123456 元"
"""
        sr = execute_in_sandbox(code, timeout=10)
        assert sr.success is True
        assert "__RESULT_START__" in sr.output
        assert "__RESULT_END__" in sr.output
        assert "销售额为 123456" in sr.output

# ============ 运行方法 ============
# cd D:\Agent Project\data_analysis_agent
# python -m pytest tests/test_sandbox.py -v
# 预期：5 passed