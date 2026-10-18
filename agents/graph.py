# ============================================================
# 架构 1：固定流水线 + 分散式 ReAct（主架构，激活）
# ============================================================
# 节点流转：load_data → planner → coder → reviewer
#                                  ↑            ↓
#                                  └── repair ←┘
#                                              ↓
#                                          executor → visualizer → reporter → END
#
# planner / coder / reviewer / repair 各自带小 ReAct（Step 1、2 改造的）
# executor / visualizer 是固定逻辑

from langgraph.graph import StateGraph, START, END
from agents.state import AgentState
from agents.tools import load_csv_data
from agents.nodes.planner import planner_node
from agents.nodes.coder import coder_node
from agents.nodes.reviewer import reviewer_node
from agents.nodes.executor import executor_node
from agents.nodes.repair import repair_node
from agents.nodes.visualizer import visualizer_node
from agents.nodes.reporter import reporter_node
from dotenv import load_dotenv

load_dotenv()

MAX_REPAIR_ATTEMPTS = 3

def load_data_node(state: AgentState) -> dict:
    """加载数据文件并生成概览"""
    df, summary = load_csv_data(state["data_path"])

    print("\n[load_data 节点] 数据加载完成")
    print(summary)
    return {"df": df, "data_summary": summary}

def route_after_review(state: AgentState) -> str:
    """reviewer 审核后路由：通过→executor，拒绝→repair"""
    if state.get("approved", False):
        return "pass"

    # 超过最大修复次数，强制往下走
    if state.get("retry_count", 0) >= MAX_REPAIR_ATTEMPTS:
        print(f"\n[警告] 已修复 {state.get('retry_count', 0)} 次，达到上限，强制继续执行")
        return "pass"

    return "repair"

def route_after_executor(state: AgentState) -> str:
    """executor 执行后路由：成功→visualizer，失败但还有机会→repair"""
    if not state.get("approved", False):
        # 代码审核未通过，无法执行，直接生成报告
        return "visualizer"

    if state.get("error_message"):
        retry_count = state.get("retry_count", 0)
        max_retry = state.get("max_retry", 3)
        if retry_count < max_retry:
            return "repair"
        else:
            print(f"\n[executor 节点] 已达最大重试次数 ({max_retry})，继续生成报告...")
            return "visualizer"

    return "visualizer"

def build_graph(checkpointer=None):
    """构建并编译工作流"""
    graph = StateGraph(AgentState)

    # 添加 8 个节点
    graph.add_node("load_data", load_data_node)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("executor", executor_node)
    graph.add_node("repair", repair_node)
    graph.add_node("visualizer", visualizer_node)
    graph.add_node("reporter", reporter_node)

    # 固定流转
    graph.add_edge(START, "load_data")
    graph.add_edge("load_data", "planner")
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "reviewer")

    # 条件路由 1：reviewer 审核后
    graph.add_conditional_edges(
        source="reviewer",
        path=route_after_review,
        path_map={
            "pass": "executor",
            "repair": "repair"
        }
    )

    # 条件路由 2：executor 执行后
    graph.add_conditional_edges(
        source="executor",
        path=route_after_executor,
        path_map={
            "visualizer": "visualizer",
            "repair": "repair",
        }
    )

    # repair 完了重新走 reviewer（循环）
    graph.add_edge("repair", "reviewer")

    # 收尾
    graph.add_edge("visualizer", "reporter")
    graph.add_edge("reporter", END)

    return graph.compile(checkpointer=checkpointer)

# ============================================================
# 架构 2：单一全能 Agent（备选架构，注释留底）
# ============================================================
# 激活方法：把上面架构1的代码整段注释掉，把下面的注释解开
# 节点流转：load_data → agent → END
# agent_node 内部是一个大 ReAct 循环（3个工具自由切换）
#
# 切换步骤：
#   1. 注释掉上面 "架构 1" 的全部代码（从 from langgraph... 到 graph.compile）
#   2. 解开下面 "架构 2" 的注释

# from langgraph.graph import StateGraph, START, END
# from agents.state import AgentState
# from agents.tools import load_csv_data
# from agents.nodes.agent import agent_node
# from dotenv import load_dotenv
#
# load_dotenv()
#
# def load_data_node(state: AgentState) -> dict:
#     """加载数据文件并生成概览（固定逻辑，不需要 LLM）"""
#     df, summary = load_csv_data(state["data_path"])
#     print("\n[load_data 节点] 数据加载完成")
#     print(summary)
#     return {"df": df, "data_summary": summary}
#
# def build_graph(checkpointer=None):
#     """构建最简工作流：load_data → agent → END"""
#     graph = StateGraph(AgentState)
#     graph.add_node("load_data", load_data_node)
#     graph.add_node("agent", agent_node)
#     graph.add_edge(START, "load_data")
#     graph.add_edge("load_data", "agent")
#     graph.add_edge("agent", END)
#     return graph.compile(checkpointer=checkpointer)