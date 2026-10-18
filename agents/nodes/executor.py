import os
from agents.state import AgentState
from agents.tools import (
    run_sandbox_code, build_sandbox_context,
    cleanup_charts, cleanup_root_charts, collect_charts, extract_result_tag,
)


def executor_node(state: AgentState) -> dict:
    """执行审核通过的代码，生成图表和结论"""
    if not state.get("approved", False):
        print("\n[executor 节点] 代码未通过审核，跳过执行")
        return {"execution_result": "代码未通过审核，无法执行。"}

    print("\n[executor 节点] 开始执行代码...")

    # 清理旧图表
    cleanup_charts()
    print("  [OK] 已清理 data/charts 中的旧图表")
    cleanup_root_charts()

    # 组装沙箱代码并执行
    sandbox_code = build_sandbox_context(state.get("data_path", "")) + "\n\n" + state["analysis_code"]
    result = run_sandbox_code(sandbox_code)

    if result.success:
        print("\n[executor 节点] 执行成功！")
        print(result.output)

        cleanup_root_charts()
        chart_paths = collect_charts()
        final_result = extract_result_tag(result.output)

        return {
            "execution_result": final_result,
            "chart_paths": chart_paths,
            "error_message": "",
        }
    else:
        error_msg = result.error or "执行超时或发生未知错误"
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retry", 3)

        if retry_count < max_retries:
            print(f"\n⚠️ [executor 节点] 执行失败（第 {retry_count + 1}/{max_retries} 次）")
            print(f"   错误: {error_msg}")
            return {
                "execution_result": "",
                "error_message": error_msg,
            }
        else:
            print(f"\n❌ [executor 节点] 已达最大重试次数 ({max_retries})，修复失败")
            return {
                "execution_result": f"执行失败，已重试 {max_retries} 次仍无法修复。\n最后错误: {error_msg}",
                "error_message": error_msg,
                "retry_count": retry_count,
            }