import os
import pandas as pd
from agents.state import AgentState
from agents.tools import collect_charts, generate_auto_charts


def visualizer_node(state: AgentState) -> dict:
    """检查 executor 生成的图表，补充通用图表，合并输出"""
    print("\n[visualizer 节点] 开始检查图表...")

    data_path = state.get("data_path", "")
    if not data_path or not os.path.exists(data_path):
        print("[visualizer 节点] 数据文件不存在，跳过图表生成")
        return {"chart_paths": []}

    df = pd.read_csv(data_path)

    # ============ 1. 收集 executor 已生成的定制图表 ============
    existing_charts = collect_charts()
    print(f"[visualizer 节点] executor 已生成图表: {existing_charts}")
    chart_paths = [f"data/charts/{f}" for f in existing_charts]
    print(f"[visualizer 节点] 保留 executor 定制图 {len(chart_paths)} 张")

    # ============ 2. 补充生成通用图表（chart_0* 前缀，与 datachart_* 不重名）============
    print("[visualizer 节点] 补充生成通用图表...")
    auto_paths = generate_auto_charts(df)
    chart_paths.extend(auto_paths)

    print(f"\n[visualizer 节点] 最终图表列表（共 {len(chart_paths)} 张）:")
    for p in chart_paths:
        print(f"  - {p}")
    return {"chart_paths": chart_paths}
