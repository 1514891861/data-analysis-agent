import os
from agents.state import AgentState
from agents.tools import save_report_md, store_history
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME


def _get_llm():
    if not hasattr(_get_llm, "_cached"):
        import time
        t0 = time.time()
        print("  [加载] 初始化 LLM 客户端 (首次较慢，请稍候)...")
        from langchain_openai import ChatOpenAI
        _get_llm._cached = ChatOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL_NAME,
            temperature=0
        )
        print(f"  [完成] LLM 客户端就绪 ({time.time()-t0:.1f}s)")
    return _get_llm._cached


def reporter_node(state: AgentState) -> dict:
    """汇总所有分析结果，生成最终报告"""
    print("\n[reporter 节点] 开始生成报告...")

    llm = _get_llm()

    # 收集所有信息
    execution_result = state.get("execution_result", "无执行结果")
    error_message = state.get("error_message", "")
    chart_paths = state.get("chart_paths", [])
    data_summary = state.get("data_summary", "")
    analysis_plan = state.get("analysis_plan", "")
    user_query = state.get("user_query", "")
    approved = state.get("approved", False)
    retry_count = state.get("retry_count", 0)

    # 构建图表信息
    chart_info = ""
    if chart_paths:
        chart_info = "生成的图表文件：\n"
        for p in chart_paths:
            chart_info += f"  - {p}\n"
    else:
        chart_info = "未生成图表。"

    # 构建执行状态描述
    if error_message:
        exec_status = f"执行失败，错误信息: {error_message}"
    elif execution_result and execution_result != "无执行结果":
        exec_status = f"执行成功，结果: {execution_result}"
    else:
        exec_status = "未执行或无结果"

    print("\n🔄 [reporter 节点] 正在调用 LLM 生成报告...")

    prompt = f"""你是一个数据分析报告撰写专家。请根据以下信息，撰写一份结构清晰、内容详实的分析报告。

【用户需求】
{user_query}

【执行状态】
{exec_status}
审核状态: {"通过" if approved else "未通过"}
修复次数: {retry_count}

【数据概览】
{data_summary}

【分析计划】
{analysis_plan}

【代码执行结果】
{execution_result}

【图表信息】
{chart_info}

请严格按照以下 Markdown 模板输出报告：

# 数据分析报告

## 一、执行状态
- 执行是否成功
- 如果失败，错误原因和已尝试的修复次数

## 二、数据概览
- 数据规模（行数、列数）
- 各列的数据类型、缺失情况
- 数据质量简要评价

## 三、分析计划
- 本次分析的目标和思路

## 四、分析发现
- 按步骤列出分析过程中的关键数据发现
- 每个发现必须用具体数据支撑（数值、百分比等）
- 不要空泛描述，要言之有物

## 五、可视化图表
- 列出所有生成的图表及其说明
- 说明每张图表展示了什么信息

## 六、结论与建议
- 基于数据发现给出 2-3 条核心结论
- 给出可操作的建议

报告要求：
- 使用中文
- 结论必须有数据支撑，不要空泛描述
- 不要编造数据中没有的信息
- 如果执行失败，如实说明情况，不要编造分析结果
"""
    response = llm.invoke(prompt)
    report = response.content

    # 保存报告到文件
    report_path = save_report_md(report)

    print(f"\n[reporter 节点] 报告已保存到: {report_path}")
    print("\n" + "=" * 50)
    print(report)
    print("=" * 50)

    # ========== RAG：把本次成功的分析存入历史库 ==========
    if approved and not error_message:
        store_history(
            user_query=user_query,
            analysis_code=state.get("analysis_code", ""),
            report=report,
            execution_result=execution_result,
            chart_paths=chart_paths,
        )

    return {"report": report, "report_path": report_path}