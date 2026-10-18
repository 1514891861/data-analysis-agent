"""
agent.py —— 终极自主 ReAct agent

所有工具注册给 LLM，LLM 自己决定下一步调什么、按什么顺序。

执行轨迹示例：
  第 1 轮: LLM → tool_call: search_history_tool("月环比趋势")
  第 2 轮: LLM → 输出纯文本代码 + tool_call: run_code_tool(代码)
  第 3 轮: run_code_tool 返回错误 → LLM 看 traceback → 输出修复后代码 → tool_call: run_code_tool(新代码)
  第 4 轮: run_code_tool 执行成功 → LLM → tool_call: save_report_tool(...)
  第 5 轮: LLM → 输出纯文本总结（不是 tool_call）→ agent 循环结束
"""

import os
from agents.state import AgentState
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, SANDBOX_TIMEOUT
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# =============================================================

# 1. 延迟加载 LLM（和各 node 里的 _get_llm 一样）

# =============================================================
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

# =============================================================

# 2. 把所有底层函数包装成 LLM 可调用的 @tool

# =============================================================

@tool
def search_history_tool(query: str, top_k: int = 3) -> str:
    """
    检索历史成功案例库，返回相似的分析代码和报告摘要。

    何时调用：
    - 用户需求比较复杂（如"预测趋势"、"综合分析"）
    - 你想参考以前类似需求的成功经验
    - 库不为空时才有用，空库会返回提示

    Args:
        query: 你的分析需求关键词（如"月环比趋势"、"产品占比分析"）
        top_k: 返回几条相似案例，默认 3
    """
    from agents.tools import search_history
    hits = search_history(query, top_k)
    if not hits:
        return "（历史经验库为空，没有相似案例）"
    parts = []
    for i, hit in enumerate(hits):
        parts.append(
            f"案例{i+1}: 用户需求={hit['user_query']}\n"
            f"  成功代码(片段)={hit['analysis_code'][:400]}\n"
            f"  报告摘要={hit['report_summary'][:300]}"
        )
    return "\n---\n".join(parts)

@tool
def run_code_tool(code: str, data_path: str = "", timeout: int = 30) -> str:
    """
    在安全沙箱中执行 Python 数据处理代码，返回执行结果或错误信息。

    你应该在以下情况调用此工具：
    - 写完分析代码后想验证是否能跑通（强烈建议调）
    - 之前的执行报错了，修完想再验证
    - 想确认 result 变量是否被正确赋值
    - 想确认图表是否真的保存成功

    Args:
        code: 你想执行的纯 Python 代码（不要带 ```python 标记）
        data_path: CSV 数据文件路径（系统会自动注入，你不用自己填）
        timeout: 最大执行秒数，默认 30 秒
    """
    from agents.tools import execute_code_tool
    return execute_code_tool(code, data_path, timeout)

@tool
def save_report_tool(
    report_text: str,
    data_path: str = "",
    analysis_code: str = "",
    execution_result: str = "",
    user_query: str = "",
) -> str:
    """
    生成分析报告、保存到文件、把成功经验存入 RAG 历史库、收集所有图表。

    **这是你的"收工工具"——当你确认分析已经完成（代码跑通了、result 变量有值了），
    调用此工具结束任务。**

    此工具会自动完成以下事情：
    1. 根据你提供的 report_text 保存为 .md 文件
    2. 收集 data/charts/ 下所有已有图表
    3. 自动补充生成 6 张通用图表（趋势图/柱状图/饼图/分布图/热力图/散点图）
    4. 如果代码执行成功，把本次经验存入 RAG 历史库（下次可被 search_history_tool 检索到）

    Args:
        report_text: 你写的 Markdown 格式报告正文（完整报告）
        data_path: 数据文件路径（系统会自动注入）
        analysis_code: 最终成功执行的代码（系统会自动注入）
        execution_result: result 变量的值（系统会自动注入）
        user_query: 原始用户需求（系统会自动注入）
    """
    from agents.tools import (
        save_report_md, store_history,
        collect_charts, generate_auto_charts,
    )
    import pandas as pd

    # 1. 保存报告
    report_path = save_report_md(report_text)

    # 2. 收集图表 + 补通用图（原 visualizer 的逻辑）
    existing_charts = collect_charts()
    chart_paths = [f"data/charts/{f}" for f in existing_charts]

    if data_path and os.path.exists(data_path):
        try:
            df = pd.read_csv(data_path)
            auto_paths = generate_auto_charts(df)
            chart_paths.extend(auto_paths)
        except Exception as e:
            print(f"  [save_report] 补通用图失败（忽略）: {e}")

    # 3. 存 RAG（执行成功才存）
    if execution_result and len(execution_result) > 10:
        try:
            store_history(
                user_query=user_query or "",
                analysis_code=analysis_code or "",
                report=report_text,
                execution_result=execution_result,
                chart_paths=chart_paths,
            )
        except Exception as e:
            print(f"  [save_report] RAG 存储失败（忽略）: {e}")

    return f"✅ 报告已保存: {report_path}\n📊 共 {len(chart_paths)} 张图表\n{'💾 RAG 经验已存入' if execution_result else '⚠️ 执行结果为空，跳过 RAG 存储'}"

# 把所有 tool 收集起来，方便统一注入 data_path
ALL_TOOLS = [search_history_tool, run_code_tool, save_report_tool]

# =============================================================

# 3. Agent 节点主函数

# =============================================================
def agent_node(state: AgentState) -> dict:
    print("\n🤖 [agent 节点] 自主分析 Agent 启动...")

    llm = _get_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    # 从 state 取固定值
    data_path = state.get("data_path", "")
    user_query = state.get("user_query", "")
    data_summary = state.get("data_summary", "")

    # ========== System Prompt ==========
    system_prompt = """你是一个自主数据分析 Agent。你可以使用工具来帮助完成任务。

=== 你有哪些工具 ===

1. search_history_tool(query) — 检索系统中历史成功案例的经验

2. run_code_tool(code) — 在安全沙箱中执行 Python 代码

3. save_report_tool(report_text) — 生成报告、保存文件、存 RAG（收工用）

=== 推荐的执行顺序 ===

1. **了解需求**：先看用户需求和数据概览

2. **查历史经验**（可选）：如果需求复杂，先调 search_history_tool 看看有没有类似案例

3. **制定计划**：在脑子里想清楚分几步做

4. **写代码 + 验证**：写 Python 分析代码 → 调 run_code_tool 验证
   - 🔴 run_code_tool 是你最重要的工具——写完代码必须调它验证！
   - 🔴 代码里必须有 `result = f"..."` 来保存最终分析结论（动态计算的 f-string，不能硬编码）
   - 🔴 图表用 plt.savefig("datachart_序号_描述.png") 保存，不要 plt.show()
   - 🔴 pandas 3.x 注意：resample('M')→'ME'，'Y'→'YE'，'Q'→'QE'

5. **处理错误**：run_code_tool 返回错误时，看 traceback → 修代码 → 再跑

6. **写报告 + 收工**：代码跑通后，写一份完整的 Markdown 格式报告 → 调 save_report_tool

=== ⛔ 绝对禁止的行为 ===

- **🔴 禁止在 run_code_tool 成功后继续反复调 run_code_tool！** 当 run_code_tool 返回"✅ 执行成功"且 result 变量有值时，说明分析已完成，**立即调 save_report_tool 收工**，不要再优化、再试别的方案。
- 禁止同一轮里调 3 次以上 run_code_tool
- 禁止 run_code_tool 没报错但 result 没值时继续瞎改——要么补 result 赋值，要么接受现状往下走

=== 代码规则 ===

- df 变量已存在（pandas DataFrame），禁止 pd.read_csv()

- os / pandas / matplotlib / matplotlib.pyplot / seaborn 已自动导入，禁止再次 import

- import matplotlib; matplotlib.use('Agg') 已注入，你不用写

- 每张 plt.savefig() 后必须 plt.close()

- 最终结论赋值给 result = f"..."，必须包含变量，禁止硬编码

=== 报告格式 ===

save_report_tool 需要完整的 Markdown 报告，包含：

- 执行状态（成功/失败）

- 数据概览

- 分析计划

- 分析发现（有数据支撑）

- 可视化图表说明

- 结论与建议

=== 输出规则 ===

- 如果你想调工具，**只输出 tool_call**（不要同时输出文字和 tool_call）

- 当你确认任务已完成、想结束时，输出纯文本总结（比如"分析完成"）—— 不要调工具

- 不要输出自然语言解释（如"我来写代码..."），直接输出代码或调工具
"""

    # ========== Human Message ==========
    human_content = (
        f"【用户需求】\n{user_query}\n\n"
        f"【数据概览】\n{data_summary}\n\n"
        f"【数据文件路径】\n{data_path}\n\n"
        f"请自主完成分析。建议先制定计划，然后写代码验证，最后生成报告。"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    # ========== ReAct 循环 ==========
    MAX_ITERATIONS = 10  # 自主 agent 需要更多轮次（规划→写→跑→修→报告→存）
    round_num = 0

    # 用于最终 state 的累积值
    final_report = ""
    final_code = ""
    final_result = ""
    final_chart_paths = []
    final_error = ""
    execution_success = False

    # 用于防止循环跑代码的计数器
    consecutive_run_code_success = 0
    last_tool_type = ""  # 上一轮 LLM 调的工具类型（跨轮次跟踪）

    for i in range(MAX_ITERATIONS):
        round_num = i + 1
        print(f"\n  [agent ReAct] === 第 {round_num} 轮 LLM 调用 ===")
        response = llm_with_tools.invoke(messages)

        # ===== LLM 没调工具 → 输出了纯文本 → agent 结束 =====
        if not response.tool_calls:
            final_text = response.content or ""
            print(f"  [agent ReAct] ✅ LLM 输出了纯文本（第 {round_num} 轮）")
            print(f"  [agent ReAct] Agent 循环结束")
            
            # 如果 LLM 最后输出的是报告文本但忘了调 save_report_tool
            if final_text and not final_report:
                print(f"  [agent ReAct] ⚠️ LLM 输出了报告文本但没调 save_report_tool，帮它保存")
                # 兜底：直接保存报告
                from agents.tools import save_report_md, generate_auto_charts, collect_charts, store_history
                import pandas as pd
                report_path = save_report_md(final_text)
                final_report = final_text
                # 收集图表
                existing = collect_charts()
                final_chart_paths = [f"data/charts/{f}" for f in existing]
                if data_path and os.path.exists(data_path):
                    try:
                        df = pd.read_csv(data_path)
                        final_chart_paths.extend(generate_auto_charts(df))
                    except Exception:
                        pass
            
            break

        # ===== LLM 要调工具 → 执行 =====
        print(f"  [agent ReAct] LLM 决定调 {len(response.tool_calls)} 个工具")
        messages.append(response)

        for tc in response.tool_calls:
            tc_name = tc[ "name" ]
            tc_args = dict (tc[ "args" ])

            # 🔒 强制覆盖超时：只对 run_code_tool 生效（其他工具没有 timeout 参数， 
            #    多塞会触发 pydantic 严格校验直接报错） 
            if tc_name == "run_code_tool" :
                tc_args[ "timeout" ] = SANDBOX_TIMEOUT 

            # 🔑 关键：统一注入固定参数（不信任 LLM 传的）
            if not tc_args.get( "data_path" ) and data_path:
                tc_args[ "data_path" ] = data_path
            
            if tc_name == "save_report_tool":
                # 补 save_report_tool 需要的额外参数（即使 LLM 传了也要覆盖，确保正确）
                if not tc_args.get("user_query"):
                    tc_args["user_query"] = user_query
                if final_code:  # 只要有就覆盖
                    tc_args["analysis_code"] = final_code
                if final_result:  # 只要有就覆盖（包含提示文本也没关系，save_report_tool 会跳过短内容）
                    tc_args["execution_result"] = final_result

            print(f"    → {tc_name}(...)")

            # 执行工具（用 @tool 对象自带的 .invoke()）
            tool_obj = next(t for t in ALL_TOOLS if t.name == tc_name)
            tool_result = tool_obj.invoke(tc_args)
            
            tool_result_str = str(tool_result)
            print(f"    ← 返回: {tool_result_str[:200]}{'...' if len(tool_result_str) > 200 else ''}")

            # ===== 工具结果后处理 =====
            if tc_name == "run_code_tool":
                # 解析 run_code_tool 结果，提取成功/失败 + 代码副本
                if "✅ 执行成功" in tool_result_str:
                    execution_success = True
                    # 提取 result 值（【分析结论】标签后面的内容）
                    import re
                    m = re.search(r"【分析结论】\s*\n(.*?)(?:\n\n【执行日志】|\Z)", tool_result_str, re.DOTALL)
                    if m:
                        _extracted = m.group(1).strip()
                        # 过滤掉 executor 返回的提示文本（不是真正的 result 值）
                        if "(result 变量未设置" not in _extracted and "result 提取失败" not in _extracted:
                            final_result = _extracted
                else:
                    execution_success = False
                    final_error = tool_result_str

                # 保存本次 run_code_tool 里的代码副本
                code_in_tool = tc_args.get("code", "")
                if code_in_tool and len(code_in_tool) > 10:
                    final_code = code_in_tool

            elif tc_name == "save_report_tool":
                # save_report_tool 内部已完成：保存报告 + 收集图表 + 补通用图 + 存 RAG
                # 这里只需更新 state 变量
                report_text = tc_args.get("report_text", "")
                if report_text:
                    final_report = report_text
                execution_success = True

            # 把工具结果塞回 messages
            messages.append(ToolMessage(
                content=tool_result_str,
                tool_call_id=tc["id"],
            ))

        # ===== 防循环：连续 3 次 run_code_tool 成功且 result 有值 → 强制提醒收工 =====
        if all(tc["name"] == "run_code_tool" for tc in response.tool_calls):
            if execution_success and final_result:
                consecutive_run_code_success += 1
            else:
                consecutive_run_code_success = 0
        else:
            consecutive_run_code_success = 0  # 调了其他工具就重置

        if consecutive_run_code_success >= 3 and execution_success and final_result:
            print(f"  [agent ReAct] ⚠️ 已连续 {consecutive_run_code_success} 次成功执行且 result 有值，强制提醒收工")
            # 往 messages 里插一条强提醒
            messages.append(SystemMessage(
                content="⚠️⚠️⚠️ 强制提醒：你已经连续 3 次成功执行代码且 result 变量有值！"
                        "分析已完成，**立即调用 save_report_tool** 收工！"
                        "不要再调 run_code_tool 了！"
            ))

    else:
        # MAX_ITERATIONS 用完了 → 强制结束
        print(f"\n  [agent ReAct] ⚠️ 达到最大迭代次数 {MAX_ITERATIONS}，强制结束")

    # ========== 统一收集图表（save_report_tool 已生成，这里扫一次目录）==========
    if execution_success and not final_chart_paths:
        try:
            from agents.tools import collect_charts
            final_chart_paths = [f"data/charts/{f}" for f in collect_charts()]
        except Exception as e:
            print(f"  [agent 节点] ⚠️ 图表收集失败（忽略）: {e}")

    # ========== 构造返回 state ==========
    print(f"\n🤖 [agent 节点] 分析完成")
    print(f"  总轮次: {round_num}")
    print(f"  执行成功: {execution_success}")
    print(f"  图表数: {len(final_chart_paths)}")
    print(f"  报告长度: {len(final_report)}")

    result_state = {
        "analysis_code": final_code,
        "execution_result": final_result,
        "error_message": final_error if not execution_success else "",
        "retry_count": max(0, round_num - 3),  # 估算：前 3 轮是规划/写代码/验证
        "review_result": "agent 自主完成审核",
        "approved": execution_success,
        "chart_paths": final_chart_paths,
        "report": final_report,
    }

    # 如果 LLM 没调 save_report_tool，但执行成功了，兜底补报告
    if execution_success and not final_report:
        print(f"  [agent 节点] ⚠️ 执行成功但没有报告，兜底生成")
        # 从 messages 里找 LLM 可能输出的文本
        for msg in reversed(messages):
            if hasattr(msg, 'content') and msg.content and len(msg.content) > 50:
                final_report = msg.content
                result_state["report"] = final_report
                break

    return result_state
