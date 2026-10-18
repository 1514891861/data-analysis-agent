"""
planner.py —— 分析计划制定节点

========== Step 3 改造：从"无脑查 RAG"到"LLM 自主决策的 mini ReAct agent" ==========

【改造前】
    hits = search_history(...)   # 无条件查 RAG
    if hits: rag_context = ...
    response = llm.invoke(prompt)

【改造后】
    search_tool = @tool(search_history)   # 把函数包装成 LLM 可调用的工具
    llm_with_tools = llm.bind_tools([search_tool])  # 告诉 LLM "你有这个工具"
    # ReAct 循环：
    #   while True:
    #       resp = llm_with_tools.invoke(messages)
    #       if not resp.tool_calls: break   # LLM 输出了纯文本 → 结束
    #       # LLM 要调工具 → 执行 → 把结果塞回 messages → 继续循环
=================================================================================
"""

import os
from agents.state import AgentState
from agents.tools import search_history
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME,LLM_TEMPERATURE

# LangChain 核心类型
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage


def _get_llm():
    """延迟并缓存 LLM 实例"""
    if not hasattr(_get_llm, "_cached"):
        import time
        t0 = time.time()
        print("  [加载] 初始化 LLM 客户端 (首次较慢，请稍候)...")
        from langchain_openai import ChatOpenAI
        _get_llm._cached = ChatOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL_NAME,
            temperature=LLM_TEMPERATURE
        )
        print(f"  [完成] LLM 客户端就绪 ({time.time()-t0:.1f}s)")
    return _get_llm._cached


# =============================================================
# Step 3 核心：把 search_history 包装成 LLM 可调用的 tool
# =============================================================

@tool
def search_history_tool(query: str, top_k: int = 3) -> str:
    """
    检索历史成功案例库，返回相似的分析代码和报告摘要。

    LLM 何时该调用此工具？
    - 用户的分析需求比较复杂（如"预测XX趋势"、"综合分析"）
    - 用户的需求与过往成功案例高度相似
    - 你需要参考以前的成功经验来制定更好的分析计划

    何时不该调用？
    - 用户只是要求简单操作（如"显示前5行"、"数据概览"）
    - 没有历史经验库或库为空
    """
    hits = search_history(query, top_k)
    if not hits:
        return "（历史经验库为空，没有相似案例）"
    parts = []
    for i, hit in enumerate(hits):
        parts.append(
            f"案例{i+1}: 用户当时需求={hit['user_query']}\n"
            f"  成功代码(片段)={hit['analysis_code'][:400]}\n"
            f"  报告摘要={hit['report_summary'][:300]}"
        )
    return "\n---\n".join(parts)


def planner_node(state: AgentState) -> dict:
    print("\n🔄 [planner 节点] 正在规划分析方案（mini ReAct agent 模式）...")
    try:
        llm = _get_llm()

        # ========== 1. 绑定工具到 LLM ==========
        # bind_tools 会把 search_history_tool 的 JSON schema 传给 LLM
        # LLM 从此知道自己有一个"可以查历史"的工具可用
        llm_with_tools = llm.bind_tools([search_history_tool])

        # ========== 2. 构造消息历史 ==========
        # messages 是一个列表，LLM 会根据这个上下文来决定下一步
        system_prompt = """你是一个数据分析专家。请根据以下数据信息和用户需求，制定一份详细的分析计划。

你有一个可用的工具 search_history_tool，可以检索系统中过往类似的成功分析案例。
**注意**：只有当用户需求比较复杂、且你认为历史经验可能有帮助时，才调用这个工具。
如果用户需求简单（如"显示前5行"），直接输出计划即可，不必调工具。

请用中文输出 3-5 个具体可执行的步骤，每步说明：
- 要做什么操作
- 用什么方法/库
- 预期得到什么结果

格式：
1. 第一步：xxx
2. 第二步：xxx
...
"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=f"【数据概览】\n{state['data_summary']}\n\n"
                        f"【用户需求】\n{state['user_query']}"
            ),
        ]

        # ========== 3. ReAct 循环 ==========
        # max_iterations=3 防止 LLM 无限乱调工具导致超时
        MAX_ITERATIONS = 3
        for i in range(MAX_ITERATIONS):
            print(f"  [planner ReAct] 第 {i+1} 轮 LLM 调用...")
            response = llm_with_tools.invoke(messages)

            # ===== 关键判断：LLM 是输出了工具调用，还是纯文本？=====
            if not response.tool_calls:
                # 没有 tool_calls → LLM 输出的是最终分析计划 → 循环结束
                plan_text = response.content
                print(f"  [planner ReAct] LLM 输出了纯文本计划（第 {i+1} 轮结束）")
                break

            # LLM 要调工具 → 执行它要求的所有 tool_call
            print(f"  [planner ReAct] LLM 决定调 {len(response.tool_calls)} 个工具")
            messages.append(response)  # 先把 LLM 的 tool_call 请求加回 messages

            for tc in response.tool_calls:
                print(f"    → 调 {tc['name']}({tc['args']})")
                # LangChain 的 Tool 对象自带 .invoke() 方法
                tool_result = search_history_tool.invoke(tc)
                # 把工具执行结果包装成 ToolMessage 塞回 messages
                # tool_call_id 用来告诉 LLM 这个结果对应哪个 tool_call
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tc["id"],
                ))
        else:
            # 极端兜底：MAX_ITERATIONS 用完了 LLM 还在调工具
            # 直接取最后一轮的 content（可能是 partial 回答）
            plan_text = response.content or "计划生成超时：LLM 工具调用循环过多"
            print(f"  [planner ReAct] ⚠️ 达到最大迭代次数 {MAX_ITERATIONS}，强制结束")

        print(f"[planner 生成分析计划]\n{plan_text}")
        return {"analysis_plan": plan_text}

    except Exception as e:
        import traceback
        print(f"!!!!!!!! planner 捕获异常：{e}")
        traceback.print_exc()
        return {"analysis_plan": f"计划生成失败：大模型调用出错 - {e}"}
