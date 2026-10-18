from typing import TypedDict, Optional, Any
import pandas as pd


class AgentState(TypedDict, total=False):
    """
    全局共享状态，所有 Agent 节点通过读写这个 State 来通信。
    total=False 表示所有字段都是可选的，初始化时不用全部填。
    """
    # 用户输入
    user_query: str                          # 用户的自然语言分析需求
    data_path: str                           # 数据文件路径

    # 数据相关
    # df: Optional[pd.DataFrame]               # pandas DataFrame 对象
    data_summary: str                        # 数据概览文本（形状、列名、缺失值等）

    # 分析相关
    analysis_plan: str                       # 分析计划文本
    analysis_code: str                       # 生成的分析代码
    execution_result: str                    # 代码执行结果
    error_message: str                       # 错误信息
    retry_count: int                         # 当前重试次数
    max_retry: int                           # 最大重试次数
    review_result: str                       # 审查是否通过
    approved: bool                           # 代码是否通过审核
    chart_paths: list[str]                   # 生成的图表路径列表

    #可视化
    chart_descriptions: str                  # 每张图表的描述信息

    # 最终输出
    report: str                              # 最终生成的报告
    report_path: str