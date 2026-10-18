"""
reviewer.py —— 代码审核节点

改造：从"纯文本审核"到"ReAct 循环 + 代码执行验证"

改造前：
    response = llm.invoke(prompt)  # 1轮 LLM，只看文本
    approved = "APPROVED" in response.content

改造后（ReAct 循环，最多 2 轮）：
    llm_with_tools = llm.bind_tools([run_code_tool])
    for i in range(MAX_ITERATIONS):
        resp = llm_with_tools.invoke(messages)
        if not resp.tool_calls:
            break  # 纯文本 → 最终审核结论
        # LLM 要调 run_code_tool → 执行沙箱 → 把结果塞回 messages → 继续
"""

import os
from agents.state import AgentState
from agents.tools import execute_code_tool

from langchain_core.tools import tool
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, SANDBOX_TIMEOUT
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# ========== 1. 把 execute_code_tool 包装成 LLM 可调用的 @tool ==========
# 和 coder.py 里完全一样——因为 execute_code_tool 是通用业务逻辑，
# 我们只需要 @tool 装饰器把它变成 LLM 能识别的 tool
@tool
def run_code_tool(code: str, data_path: str = "", timeout: int = 30) -> str:
    """
    在安全沙箱中执行 Python 数据处理代码，返回执行结果或错误信息。

    你应该在以下情况调用此工具：
    - 审核代码前想验证是否能跑通（强烈建议调一次）
    - 代码执行报错了，帮 repair 定位具体错误
    - 想确认 result 变量是否被正确赋值
    - 想确认图表保存路径是否正确

    Args:
        code: 你想执行的纯 Python 代码（不要带 ```python 标记）
        data_path: CSV 数据文件路径（系统会传，你通常不用自己填）
        timeout: 最大执行秒数，默认 30 秒
    """
    return execute_code_tool(code, data_path, timeout)

def _get_llm(temperature=0):
    """延迟并缓存 LLM 实例（和原来一样，复用）"""
    cache_key = f"_cached_t{temperature}"
    if not hasattr(_get_llm, cache_key):
        import time
        t0 = time.time()
        print("  [加载] 初始化 LLM 客户端 (首次较慢，请稍候)...")
        from langchain_openai import ChatOpenAI
        setattr(_get_llm, cache_key, ChatOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL_NAME,
            temperature=temperature
        ))
        print(f"  [完成] LLM 客户端就绪 ({time.time()-t0:.1f}s)")
    return getattr(_get_llm, cache_key)

def _parse_approval(text: str) -> bool:
    """从 LLM 的审核结论里判断 APPROVED 还是 REJECTED"""
    lines = text.strip().split("\n")
    # 找最后一行有明确结论的
    for line in reversed(lines):
        line_upper = line.strip().upper()
        if "APPROVED" in line_upper:
            return "REJECTED" not in line_upper
        if "REJECTED" in line_upper:
            return False
    # 兜底：全文搜索
    if "REJECTED" in text.upper():
        return False
    return True

def reviewer_node(state: AgentState) -> dict:
    print("\n🔄 [reviewer 节点] 正在审核代码（tool-calling 模式）...")

    llm = _get_llm(temperature=0)
    
    # ✅ 关键：把 run_code_tool 绑定到 LLM
    llm_with_tools = llm.bind_tools([run_code_tool])

    # 存起来，稍后 tool_call 里用
    data_path = state.get("data_path", "")

    # ========== 2. 构造 prompt ==========
    # 和原来的 prompt 基本一样，但额外强调了"建议跑一遍"
    system_prompt = """你是一个严格但公正的代码审核专家。请审核以下数据分析代码。

你有一个可用的工具 run_code_tool，可以把待审核的代码在安全沙箱里跑一遍，
看看有没有运行时报错。**强烈建议审核前先跑一次**，这样能发现：
- pandas 版本兼容问题（如 resample('M') 在 3.x 要改成 'ME'）
- matplotlib 路径劫持是否生效
- result 变量是否被正确赋值
- 图表是否真的保存成功

=== 审核要点 ===

1. **语法正确性**：代码是否有 Python 语法错误？运行是否会崩溃？
2. **功能完整性**：能否完成分析计划的每一项要求？
3. **安全性**：有没有删除文件、执行系统命令等危险操作？

=== 硬性规则 ===

- df 变量已由外部提供，不需要 pd.read_csv()，如果代码里出现了 pd.read_csv() → REJECTED
- import matplotlib; matplotlib.use('Agg') 必须在 import matplotlib.pyplot 之前
- os / pandas / matplotlib 已由系统自动导入，重复 import → 小问题，不拒绝
- 代码中不能出现自然语言（如 "Wait..."、"Here is the code..."）
- result 必须是动态计算的 f-string，不能是硬编码文字

=== 输出格式 ===

在最后一行必须明确输出：
- APPROVED（通过）
- REJECTED + 原因（不通过）

不要因为代码风格不够优雅而拒绝，只要核心功能正确就应该通过。
"""

    human_content = (
        f"【数据概览】\n{state['data_summary']}\n\n"
        f"【分析计划】\n{state['analysis_plan']}\n\n"
        f"【待审核代码】\n{state['analysis_code']}\n\n"
        f"【数据文件路径】\n{data_path}\n\n"
        f"请先调用 run_code_tool 跑一遍这段代码（如果还没跑过的话），"
        f"然后给出审核结论。"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    # ========== 3. ReAct 循环 ==========
    MAX_ITERATIONS = 2  # reviewer 最多 2 轮（比 coder 少，因为 reviewer 主要是看，不是生成）
    final_review = ""

    for i in range(MAX_ITERATIONS):
        print(f"  [reviewer ReAct] 第 {i+1} 轮 LLM 调用...")
        response = llm_with_tools.invoke(messages)

        # ===== 判断：LLM 是输出了审核结论，还是要调工具？=====
        if not response.tool_calls:
            # 没有 tool_call → LLM 输出了最终审核结论 → 循环结束
            final_review = response.content or ""
            approved = _parse_approval(final_review)
            print(f"  [reviewer ReAct] ✅ LLM 输出了审核结论（第 {i+1} 轮）")
            break

        # LLM 要调工具 → 执行所有 tool_call
        print(f"  [reviewer ReAct] LLM 决定调 {len(response.tool_calls)} 个工具（跑代码验证）")
        messages.append(response)

        for tc in response.tool_calls:
            print(f"    → run_code_tool(code长度={len(tc['args'].get('code', ''))})")
            
            # 🔑 关键：注入 data_path（和 coder 一样，不信任 LLM 传的）
            tc_args = dict(tc["args"])
            if not tc_args.get("data_path") and data_path:
                tc_args["data_path"] = data_path
            tc_args[ "timeout" ] = SANDBOX_TIMEOUT
            
            # 执行工具
            tool_result = run_code_tool.invoke(tc_args)
            
            # 把结果塞回 messages
            messages.append(ToolMessage(
                content=str(tool_result),
                tool_call_id=tc["id"],
            ))
    else:
        # MAX_ITERATIONS 用完了 → 兜底：最后一条消息里找结论
        print(f"  [reviewer ReAct] ⚠️ 达到最大迭代次数，用最后输出兜底")
        final_review = response.content or ""
        approved = _parse_approval(final_review)

    # 如果 LLM 一直没输出明确结论（只调了工具没给审核），兜底 approve
    if not final_review:
        final_review = "(LLM 未输出审核意见，兜底通过)"
        approved = True

    print(f"\n[reviewer 节点] 代码审核完成")
    print(f"审核结论: {'通过 ✅' if approved else '未通过 ❌'}")
    print(f"完整审核意见:\n{final_review}")

    return {"review_result": final_review, "approved": approved}