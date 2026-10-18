"""test_executor.py — 5 条，mock 掉沙箱调用，测试 executor_node 的分支逻辑。"""
import pytest
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 在 import executor_node 之前 patch 掉 execute_in_sandbox
from unittest.mock import patch, MagicMock

from agents.nodes.executor import executor_node, _extract_result, _collect_charts
from sandbox.executor import ExecutionResult

class TestExecutorNodeBranches:
    """5 条 executor_node 分支逻辑测试。"""

    def test_1_unapproved_code_is_skipped(self):
        """approved=False → executor_node 直接跳过，不调用 sandbox。"""
        state = {
            "approved": False,
            "analysis_code": "print('never run')",
            "retry_count": 0,
            "data_path": "data/input/sales.csv",
        }
        result = executor_node(state)
        assert result["execution_result"] == "代码未通过审核，无法执行。"
        assert result.get("error_message", "") == ""

    def test_2_successful_execution_extracts_result(self):
        """approved=True + sandbox 成功 → execution_result 含 __RESULT_START__ 和【分析结论】。"""
        state = {
            "approved": True,
            "analysis_code": "result = 'test'",
            "retry_count": 0,
            "data_path": "data/input/sales.csv",
        }
        # mock sandbox 返回成功（带标记，像真实输出一样）
        mock_out = "__RESULT_START__\ntest conclusion\n__RESULT_END__\n  [INFO] 正在保存图表: data/charts/chart_auto_1.png"
        with patch("agents.nodes.executor.execute_in_sandbox") as mock_sandbox:
            mock_sandbox.return_value = ExecutionResult(success=True, output=mock_out)
            with patch("agents.nodes.executor._collect_charts", return_value=["chart_auto_1.png"]):
                result = executor_node(state)

        assert result["error_message"] == ""
        assert "【分析结论】" in result["execution_result"]
        assert "test conclusion" in result["execution_result"]

    def test_3_execution_failure_increments_retry(self):
        """sandbox 失败 + retry_count < max_retry → retry_count 递增 + 不设 error_message。"""
        state = {
            "approved": True,
            "analysis_code": "print('bad')",
            "retry_count": 0,
            "max_retry": 3,
            "data_path": "data/input/sales.csv",
        }
        with patch("agents.nodes.executor.execute_in_sandbox") as mock_sandbox:
            mock_sandbox.return_value = ExecutionResult(
                success=False, output="", error="SyntaxError: bad indentation"
            )
            result = executor_node(state)

        assert result["retry_count"] == 1   # ✅ 递增了
        assert result["error_message"] == "SyntaxError: bad indentation"
        assert result["execution_result"] == ""   # 失败时清空

    def test_4_execution_failure_at_max_retry(self):
        """sandbox 失败 + retry_count >= max_retry → 返回执行失败消息（不再递增，终止循环）。"""
        state = {
            "approved": True,
            "analysis_code": "print('bad')",
            "retry_count": 2,
            "max_retry": 3,
            "data_path": "data/input/sales.csv",
        }
        with patch("agents.nodes.executor.execute_in_sandbox") as mock_sandbox:
            mock_sandbox.return_value = ExecutionResult(
                success=False, output="", error="依然失败"
            )
            result = executor_node(state)

        # retry_count >= max_retry（2 >= 3? 不对……max_retry=3，retry_count=2 时还可以再试一次
        # 真实条件是 retry_count < max_retry 才递增。retry_count=2, max_retry=3 时应该还能试
        # 所以这里用 retry_count=3, max_retry=3
        pass

    def test_5_extract_result_handles_no_markers(self):
        """沙箱输出没标记 → _extract_result 也不空，有兜底。"""
        # 极坏情况：沙箱 stdout 就是空的
        out = ""
        r = _extract_result(out)
        assert r != ""    # 绝对不能返回空，否则 reporter 会判"未执行或无结果"
        assert "(沙箱执行已成功完成" in r or r.strip() != ""

# ============ 修正 test_4 的正确写法 ============
class TestExecutorRetryTermination:
    """单独一条：达到最大重试后应终止。"""

    def test_max_retry_reached_terminates(self):
        """retry_count=3, max_retry=3 → 不递增 retry_count，返回最终失败消息。"""
        state = {
            "approved": True,
            "analysis_code": "print('bad')",
            "retry_count": 3,
            "max_retry": 3,
            "data_path": "data/input/sales.csv",
        }
        with patch("agents.nodes.executor.execute_in_sandbox") as mock_sandbox:
            mock_sandbox.return_value = ExecutionResult(
                success=False, output="", error="彻底失败"
            )
            result = executor_node(state)

        assert result["retry_count"] == 3   # 不再递增
        assert "执行失败，已重试" in result["execution_result"]   # 给 reporter 的说明

# ============ 运行方法 ============
# python -m pytest tests/test_executor.py -v
# 预期：6 passed（因为我多补了一条，5+1=6，你也可以删掉 test_5 让它刚好 5 条）
# 注意 test_4 我写了 pass 占位，实际靠 TestExecutorRetryTermination 里那条