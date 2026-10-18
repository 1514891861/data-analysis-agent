import os
import sys
import io
import uuid
import shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from dotenv import load_dotenv
from agents.graph import build_graph 
from config import DATA_INPUT_DIR,MAX_RETRY
from langgraph.checkpoint.sqlite import SqliteSaver

THREAD_ID = str(uuid.uuid4())   # 🔑 关键：全程只用这一个 thread_id
DB_PATH = "checkpoints.db"
MERMAID_PATH = "agent_workflow.mmd"

load_dotenv()


def print_header():
    print("=" * 50)
    print("  🤖 数据分析 Agent (多轮对话版)")
    print("=" * 50)
    print(f"  thread_id: {THREAD_ID}")
    print(f"  checkpoint: {DB_PATH}")
    print("=" * 50)

# ==================== 工具函数 ====================

def new_config():
    """生成新的 thread config"""
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def reset_checkpoint():
    """彻底清除历史状态：删文件"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    return True


def clean_old_outputs():
    """清理旧的图表和报告文件"""
    for old_dir in ["data/charts", "data/reports"]:
        if os.path.exists(old_dir):
            shutil.rmtree(old_dir)
            os.makedirs(old_dir, exist_ok=True)


def generate_mermaid(graph):
    """根据当前图结构重新生成 agent_workflow.mmd"""
    mermaid_code = graph.get_graph().draw_mermaid()
    with open(MERMAID_PATH, "w", encoding="utf-8") as f:
        f.write(mermaid_code)
    print(f"\n📊 [工作流图] 已更新: {MERMAID_PATH}")


def run_graph(graph, initial_state, config):
    """运行图，返回最终结果，并打印每个节点的执行情况"""
    result = None
    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        for node_name in chunk.keys():
            print(f"\n✅ [{node_name}] 节点执行完成")
        result = graph.get_state(config).values
    return result


# ==================== 状态构建 ====================

def get_user_input():
    """获取用户输入的数据路径和分析需求"""
    if len(sys.argv) > 1:
        data_path = sys.argv[1]
    else:
        print(f"\n请将数据文件放到: {DATA_INPUT_DIR}")
        data_path = input("请输入数据文件路径: ").strip()

    if not os.path.exists(data_path):
        print(f"[错误] 文件不存在: {data_path}")
        sys.exit(1)

    user_query = input("请输入你的分析需求: ").strip()
    if not user_query:
        user_query = "对数据进行全面分析"

    print(f"\n[信息] 数据文件: {data_path}")
    print(f"[信息] 分析需求: {user_query}")
    print("-" * 50)
    return data_path, user_query


def build_initial_state(data_path, user_query):
    """构建初始状态"""
    return {
        "user_query": user_query,
        "data_path": data_path,
        "data_summary": "",
        "analysis_plan": "",
        "analysis_code": "",
        "execution_result": "",
        "error_message": "",
        "retry_count": 0,
        "max_retry": MAX_RETRY,
        "review_result": "",
        "approved": False,
        "chart_paths": [],
        "report": "",
        "report_path": ""
    }



# ==================== 主流程 ====================

def check_history():
    """检查是否有未完成的历史任务"""
    config = {"configurable": {"thread_id": THREAD_ID}}
    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        snapshot = graph.get_state(config)
    return bool(snapshot.next), config


def main():
    print_header()
    config = {"configurable": {"thread_id": THREAD_ID}}

    # ========== ① 阶段一：用临时 SqliteSaver 查 checkpoint 状态（查完就关，好让后面能安全删文件）==========
    has_history = False
    need_reset = False
    if os.path.exists(DB_PATH):
        # 临时开一个连接查一下上次状态
        with SqliteSaver.from_conn_string(DB_PATH) as tmp:
            tmp_graph = build_graph(checkpointer=tmp)
            snapshot = tmp_graph.get_state(config)
            has_history = bool(snapshot.next)   # next 非空 = 上次任务未完成

        if has_history:
            print("\n⚠️  发现上次未完成的任务")
            print("   正在自动恢复...")
        else:
            choice = input("\n发现历史会话记录，继续上次会话？(y=继续 / n=全新开始): ").strip().lower()
            if choice != 'y':
                need_reset = True

    # ========== ② 阶段二：这时 DB 文件已经释放了，想删就安全了 ==========
    if need_reset:
        reset_checkpoint()
        print("✅ 已清除历史 checkpoint")
    clean_old_outputs()

    # ========== ③ 阶段三：正式开 SqliteSaver 跑工作流 ==========
    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        generate_mermaid(graph)

        # ========== 主循环 ==========
        round_num = 0
        while True:
            round_num += 1
            print(f"\n{'='*50}")
            print(f"  🎯 第 {round_num} 轮分析")
            print(f"{'='*50}")

            if round_num == 1:
                data_path, user_query = get_user_input()
                initial_state = build_initial_state(data_path, user_query)
            else:
                user_query = input("请输入新的分析需求（输入 'exit' 退出）: ").strip()
                if not user_query or user_query.lower() in ('exit', 'quit', '退出'):
                    print("\n👋 会话结束")
                    break
                snapshot = graph.get_state(config)
                data_path = snapshot.values.get('data_path', '')
                initial_state = {
                    "user_query": user_query,
                    "execution_result": "",
                    "error_message": "",
                    "retry_count": 0,
                    "review_result": "",
                    "approved": False,
                    "chart_paths": [],
                    "report": "",
                    "report_path": ""
                }

            print(f"\n📝 本轮需求: {user_query}")
            print("-" * 50)
            result = run_graph(graph, initial_state, config)

            print(f"\n✅ 执行完成")
            print(f"   retry_count: {result.get('retry_count')}")
            print(f"   chart_paths: {len(result.get('chart_paths', []))} 张")
            report = result.get('report', '')
            if report:
                print(f"\n📄 报告预览 (前300字):")
                print(report[:300])
                print("...\n")

if __name__ == "__main__":
    main()