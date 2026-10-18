"""
repair.py —— 代码修复节点（ReAct agent）

改造：从"纯文本修复"到"ReAct 循环 + 代码执行验证"

改造前：
    LLM 只看 error_message / review_result 的文字描述 → 猜着修 → 可能还错

改造后（ReAct 循环，最多 3 轮）：
    第 1 轮: "让我先跑一下看具体报什么错" → tool_call: run_code_tool
    第 2 轮: "报错是 resample('M') 改成 'ME'" → 输出修复后的代码
    第 3 轮（如果需要）: 再跑一次验证 → 确认通过

好处：
    - 不用靠猜 reviewer 的反馈文字，直接看到实际 traceback
    - 修完自己跑一遍验证，错了再修
    - 减少对 repair 循环 retry 的依赖
"""

import os
from agents.state import AgentState
from agents.tools import execute_code_tool

from langchain_core.tools import tool
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, SANDBOX_TIMEOUT
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# ========== 1. 把 execute_code_tool 包装成 LLM 可调用的 @tool ==========
# 和 reviewer.py / coder.py 里完全一样
@tool
def run_code_tool(code: str, data_path: str = "", timeout: int = 30) -> str:
    """
    在安全沙箱中执行 Python 数据处理代码，返回执行结果或错误信息。

    你应该在以下情况调用此工具：
    - 想看看当前代码具体报什么错（强烈建议先跑一遍）
    - 修复代码后想验证是否跑通了
    - 想确认 result 变量是否被正确赋值
    - 想确认图表是否真的保存成功

    Args:
        code: 你想执行的纯 Python 代码（不要带 ```python 标记）
        data_path: CSV 数据文件路径（系统会传，你通常不用自己填）
        timeout: 最大执行秒数，默认 30 秒
    """
    return execute_code_tool(code, data_path, timeout)

def _get_llm(temperature=0):
    """延迟并缓存 LLM 实例"""
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

def _extract_code_from_response(text: str) -> str:
    """从 LLM 输出里提取纯代码（去掉 ```python 标记和解释文字）"""
    text = text.strip()

    # 如果有 ```python ... ``` 代码块，取里面的
    if "```" in text:
        parts = text.split("```")
        # 取奇数位置的（1, 3, 5...）
        for i in range(1, len(parts), 2):
            block = parts[i].strip()
            if block.startswith("python"):
                block = block[len("python"):].strip()
            if len(block) > 20:  # 只有代码块够长才认为是代码
                return block

    # 没有代码块标记，直接返回全文（可能有解释文字在开头/结尾）
    return text

def repair_node(state: AgentState) -> dict:
    print("\n🔄 [repair 节点] 正在修复代码（ReAct tool-calling 模式）...")

    llm = _get_llm(temperature=0)
    
    # ✅ 关键：把 run_code_tool 绑定到 LLM
    llm_with_tools = llm.bind_tools([run_code_tool])

    # 从 state 取所有需要的值
    data_path = state.get("data_path", "")
    error_msg = state.get('error_message', '')
    review_result = state.get('review_result', '')
    analysis_code = state.get('analysis_code', '')
    data_summary = state.get('data_summary', '')
    analysis_plan = state.get('analysis_plan', '')

    # 根据失败来源组装上下文
    if error_msg:
        failure_context = f"""【上次执行的错误信息】
代码在沙箱中执行时出现了以下错误（完整 traceback）：
```
{error_msg}
```
"""
    else:
        failure_context = f"""【上次审核的拒绝原因】
{review_result}
"""

    # ========== 2. 构造 prompt ==========
    system_prompt = """你是一个资深 Python 代码修复专家。你的任务是修复一段有问题的数据分析代码。
    
你有一个可用的工具 run_code_tool，可以把代码在安全沙箱里跑一遍，
**强烈建议在修复前先跑一次看看具体报什么错**（比看文字描述更准确），
修复后也再跑一次验证是否真的修好了。

=== 修复规则 ===

1. df 变量已存在（pandas DataFrame），禁止 import pandas，禁止 pd.read_csv()
2. os / pandas / matplotlib / matplotlib.pyplot / seaborn 已自动导入，禁止再次 import
3. import matplotlib; matplotlib.use('Agg') 必须在 import matplotlib.pyplot 之前（系统已注入，你不用写）
4. 图表保存格式：data/charts/datachart_序号_描述.png
5. 不要 plt.show()，只用 plt.savefig()
6. 每张图保存后必须 plt.close() 清画布
7. 最终分析结论赋值给 result 变量，result 必须是 f-string 动态计算，禁止硬编码文字
8. 如果原始代码里有自然语言（如 "Wait, I have..."），完全删掉
9. pandas 3.0+ 注意：resample('M') 改 'ME'，resample('Y') 改 'YE'，resample('Q') 改 'QE'

=== 输出格式 ===

当你确认代码已经修好后，**直接输出修复后的完整 Python 代码**，不要解释文字，不要 markdown 代码块标记。
只在确认修好后才输出代码——如果还要先跑一遍看错误或验证，就调用 run_code_tool。
"""

    human_content = (
        f"【数据概览】\n{data_summary}\n\n"
        f"【分析计划】\n{analysis_plan}\n\n"
        f"{failure_context}\n\n"
        f"【需要修复的原始代码】\n```python\n{analysis_code}\n```\n\n"
        f"请先调用 run_code_tool 跑一遍这段代码看看具体报什么错，"
        f"然后修复代码，修复后再跑一遍验证。"
        f"确认没问题后，输出修复后的完整代码。"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    # ========== 3. ReAct 循环 ==========
    MAX_ITERATIONS = 3  # repair 最多 3 轮（比 reviewer 多，因为要修+验证）
    final_code = ""

    for i in range(MAX_ITERATIONS):
        print(f"  [repair ReAct] 第 {i+1} 轮 LLM 调用...")
        response = llm_with_tools.invoke(messages)

        # ===== 判断：LLM 是输出了代码，还是要调工具？=====
        if not response.tool_calls:
            # 没有 tool_call → LLM 输出了最终修复代码 → 循环结束
            raw_output = response.content or ""
            final_code = _extract_code_from_response(raw_output)
            print(f"  [repair ReAct] ✅ LLM 输出了修复后的代码（第 {i+1} 轮）")
            break

        # LLM 要调工具 → 执行所有 tool_call
        print(f"  [repair ReAct] LLM 决定调 {len(response.tool_calls)} 个工具（跑代码验证）")
        messages.append(response)

        for tc in response.tool_calls:
            print(f"    → run_code_tool(code长度={len(tc['args'].get('code', ''))})")
            
            # 🔑 关键：注入 data_path（不信任 LLM 传的）
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
        # MAX_ITERATIONS 用完了 → 兜底：把最后一次 LLM 的输出当代码
        print(f"  [repair ReAct] ⚠️ 达到最大迭代次数，用最后输出兜底")
        raw_output = response.content or ""
        final_code = _extract_code_from_response(raw_output)

    # 兜底：如果 LLM 一直没输出代码（只调了工具没给代码），就用原始代码
    if not final_code or len(final_code) < 10:
        print(f"  [repair ReAct] ⚠️ LLM 未输出有效代码，兜底使用原始代码")
        final_code = analysis_code

    print(f"\n[repair 节点] 代码修复完成 (最终代码长度: {len(final_code)})")

    return {
        "analysis_code": final_code,
        "retry_count": state.get("retry_count", 0) + 1,
        "approved": True,
        "review_result": "代码已修复，请执行"
    }