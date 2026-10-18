"""
coder.py —— 代码生成节点

Step 5 改造：从"一次性输出代码"到"ReAct 循环 + 自测"

改造前：
    response = llm.invoke(prompt)
    code = _extract_last_code_block(response.content)

改造后（ReAct 循环）：
    llm_with_tools = llm.bind_tools([execute_code_tool])
    for i in range(MAX_ITERATIONS):
        resp = llm_with_tools.invoke(messages)
        if not resp.tool_calls:
            break  # 纯文本 → 最终代码
        # LLM 要调工具 → 执行沙箱 → 把结果塞回 messages → 继续
"""

import os
import re
from agents.state import AgentState
from agents.tools import execute_code_tool
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, SANDBOX_TIMEOUT

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# ========== 1. 把 execute_code_tool 包装成 LLM 可调用的 @tool ==========
# 注意：这里我们要让 LLM 传 data_path，这样 tool 内部才能 build_sandbox_context
@tool
def run_code_tool(code: str, data_path: str = "", timeout: int = 30) -> str:
    """
    在安全沙箱中执行 Python 数据处理代码，返回执行结果或错误信息。

    你应该在以下情况调用此工具：
    - 写完代码后想验证是否能跑通（强烈建议调一次）
    - 之前的执行报错了，修完想再验证
    - 想确认 result 变量是否被正确赋值

    不要调用此工具的情况：
    - 你已经确认代码没问题（可以直接输出最终版本）
    - 用户需求极简单（如"显示前5行"），无需自测

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

def _extract_last_code_block(text: str) -> str:
    """从文本中提取最后一个 ``` ... ``` 代码块里的纯代码。没有就返回清理后的全文。"""
    pattern = r"```(?:python)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    code = text.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1]
    if code.endswith("```"):
        code = code.rsplit("```", 1)[0]
    return code.strip()

def coder_node(state: AgentState) -> dict:
    print("\n🔄 [coder 节点] 正在生成代码（tool-calling 模式）...")

    llm = _get_llm(temperature=0)
    
    # ✅ 关键：把 run_code_tool 绑定到 LLM
    llm_with_tools = llm.bind_tools([run_code_tool])

    # 把 data_path 存起来，稍后 tool_call 里用
    data_path = state.get("data_path", "")

    # ========== 2. 构造 prompt ==========
    # 和原来 coder 的 prompt 基本一样，额外加一句说明 LLM 可以调 run_code_tool
    system_prompt = f"""你是一个 Python 数据分析师。请根据以下信息编写可执行的 Python 代码。

你有一个可用的工具 run_code_tool，可以把你写的代码在沙箱里跑一遍，
看看有没有报错。**强烈建议写完代码后调一次这个工具验证**，这样能提前发现 bug，
比等下游 reviewer 或 executor 报错再回来修效率高得多。

=== 最重要规则：result 变量 ===

result 必须是代码执行时动态计算得出的，禁止写死任何分析文字。

✅ 正确写法（动态计算）：
total_sales = df['销售额'].sum()
result = f"总销售额为{{total_sales}}元"

❌ 错误写法（硬编码，绝对禁止）：
result = "分析结论：销售额呈上升趋势..."

规则：result = f"..." 中必须包含 {{变量名}}，变量的值来自代码计算结果。

=== 其他规则 ===

1. 只输出纯 Python 代码，不要任何解释文字，不要 markdown 代码块标记
2. 以下库已由系统自动导入：os, pandas, matplotlib, matplotlib.pyplot, seaborn。直接使用 os, pd, plt, sns
3. 绝对不要 pd.read_csv()，df 变量已存在
4. 图表保存为 datachart_序号_描述.png，例如 datachart_02_region_compare.png
5. 不要 plt.show()，只用 plt.savefig()
6.⚠️ pandas 3.0+ 注意：resample('M')→'ME', 'Y'→'YE', 'Q'→'QE', 'D'→'DE', 'H'→'h'
"""

    # HumanMessage 包含用户需求 + 数据概览 + 分析计划
    human_content = (
        f"【用户需求】\n{state['user_query']}\n\n"
        f"【数据概览】\n{state['data_summary']}\n\n"
        f"【分析计划】\n{state['analysis_plan']}\n\n"
        f"【数据文件路径】\n{data_path}\n\n"
        f"请编写可执行的 Python 分析代码。写完后可以调 run_code_tool 验证。"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    # ========== 3. ReAct 循环 ==========
    MAX_ITERATIONS = 3  # 最多 3 轮（写代码 + 验证 + 可能修一次）
    final_code = ""

    for i in range(MAX_ITERATIONS):
        print(f"  [coder ReAct] 第 {i+1} 轮 LLM 调用...")
        response = llm_with_tools.invoke(messages)

                # ===== 判断：LLM 是输出了纯文本代码，还是要调工具？=====
        if not response.tool_calls:
            raw_text = response.content or ""
            raw_code = _extract_last_code_block(raw_text)
            
            # ===== 新增：验证提取出来的真的是 Python 代码 =====
            code_keywords = ['import ', 'pd.', 'plt.', 'df.', 'result', 'def ', 'class ']
            has_code_keyword = any(kw in raw_code for kw in code_keywords)
            has_report_pattern = raw_code.count('|') > 3 or raw_code.count('##') > 2
            
            is_valid_python = raw_code and len(raw_code) > 20 and has_code_keyword and not has_report_pattern
            
            if is_valid_python:
                final_code = raw_code
                print(f"  [coder ReAct] ✅ LLM 输出了最终代码（第 {i+1} 轮，长度 {len(final_code)}）")
            elif final_code and len(final_code) > 20:
                print(f"  [coder ReAct] ⚠️ LLM 输出的纯文本不像代码，用 tool_call 备份兜底（长度 {len(final_code)}）")
            else:
                print(f"  [coder ReAct] ⚠️ LLM 输出无效，从 messages 历史里找...")
                for msg in reversed(messages):
                    if hasattr(msg, 'content') and msg.content and '```' in msg.content:
                        final_code = _extract_last_code_block(msg.content)
                        break
            break

        # LLM 要调工具 → 执行所有 tool_call
        print(f"  [coder ReAct] LLM 决定调 {len(response.tool_calls)} 个工具（做自测）")
        messages.append(response)  # 把 LLM 的 tool_call 请求加回对话

        for tc in response.tool_calls:
            print(f"    → run_code_tool(code长度={len(tc['args'].get('code', ''))}, data_path=...)")
            
            # ⚠️ 关键：把 data_path 注入 tool_call 的 args
            # 因为 LLM 可能忘了传 data_path，但我们知道 state 里有
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
            
            # ⭐ 额外：提取这次 tool_call 里 LLM 写的代码
            # 万一 LLM 后面的纯文本输出是空的，我们至少有这份代码
            raw_code = tc_args.get("code", "")
            if raw_code and len(raw_code) > 20:
                final_code = raw_code
                print(f"    (记录代码副本，长度 {len(final_code)})")

    else:
        # MAX_ITERATIONS 用完了 → 兜底
        print(f"  [coder ReAct] ⚠️ 达到最大迭代次数 {MAX_ITERATIONS}，用最后记录的代码兜底")

    print(f"\n[coder 节点] 代码生成完成（tool-calling 模式，最终长度 {len(final_code)}）")
    print(final_code)
    return {"analysis_code": final_code}