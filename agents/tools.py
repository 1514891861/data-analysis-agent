"""
agents/tools.py —— 数据执行 Agent 的工具函数集

把散落在各 node（graph.py / visualizer.py / executor.py / reporter.py）里的
实际干活代码（非 LLM 调用部分）统一封装到这里，各 node 调 tools 而不是自己写实现。

当前 pipeline 是固定流程（planner→coder→reviewer→executor→visualizer→reporter），
LLM 只输出文本；真正执行操作的是本模块里的函数。

未来若要升级成 ReAct agent（LLM 自主调工具），直接用:
    llm.bind_tools([load_csv_data, run_sandbox_code, ...])
即可复用这些函数，无需重写。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from sandbox.executor import execute_in_sandbox, ExecutionResult


# =============================================================
# 1. 数据加载工具
# =============================================================

def read_any(path: str) -> pd.DataFrame:
    """
    按文件后缀自动选择读取方式，统一返回 DataFrame。
    支持：.csv / .xlsx / .xls / .tsv / .txt / .json / .parquet
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)                     # xlsx→openpyxl，xls→xlrd
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    if ext == ".txt":
        # 分隔符未知，让 pandas 自动嗅探（逗号/制表符/分号都能识别）
        return pd.read_csv(path, sep=None, engine="python")
    if ext == ".json":
        return pd.read_json(path)                      # 只支持"表形态"的 JSON
    if ext == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)                           # 默认（含 .csv）


def load_csv_data(path: str) -> tuple[pd.DataFrame, str]:
    """
    读取数据文件（按后缀自动分流到 read_any）并生成数据概览文本。

    来源: agents/graph.py::load_data_node
    被 graph.py 的 load_data_node 调用。

    Returns:
        (df, summary_str): DataFrame + 人类可读的概览文本
    """
    df = read_any(path)
    summary = f"=== 数据概览 ===\n"
    summary += f"文件: {path}\n"
    summary += f"行数: {len(df)}\n"
    summary += f"列数: {len(df.columns)}\n\n"
    summary += "--- 列信息 ---\n"
    for col in df.columns:
        summary += f"  {col} | 类型: {df[col].dtype} | 非空: {df[col].count()} | 缺失: {df[col].isnull().sum()}\n"
    summary += "\n--- 前5行数据 ---\n"
    summary += df.head().to_string()
    return df, summary


# =============================================================
# 2. 沙箱执行工具
# =============================================================

def run_sandbox_code(
    code: str,
    timeout: int = 30,
) -> ExecutionResult:
    """
    在隔离子进程中安全执行 Python 代码。

    来源: sandbox/executor.py::execute_in_sandbox（直接 re-export）
    被 executor.py 调用。
    """
    return execute_in_sandbox(code, timeout=timeout)


def execute_code_tool(code: str, data_path: str = "", timeout: int = 30) -> str:
    """
    【给 LLM 调的版本】在沙箱中执行代码，返回可读的 str 结果。
    自动拼 context（df 加载 + savefig 劫持 + pandas 兼容），
    因为 LLM 只会输出裸代码，不会带 context。
    """
    full_code = build_sandbox_context(data_path) + "\n\n" + code
    result = run_sandbox_code(full_code, timeout)
    
    if result.success:
        return "✅ 执行成功！\n" + extract_result_tag(result.output)
    else:
        return f"❌ 执行失败！错误：{result.error or '未知错误'}\n\n原始输出：{result.output[:500]}"


def build_sandbox_context(data_path: str = "") -> str:
    """
    构建沙箱注入代码块：字体设置 + savefig 路径劫持 + pandas 3.x 兼容 + df 加载。

    来源: agents/nodes/executor.py::_build_sandbox_context
    被 executor.py 调用。
    """
    font_setup = """
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Zen Hei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# ============ 压制 matplotlib/pandas 等库的 WARNING ============
import warnings
warnings.filterwarnings("ignore")
plt.rcParams["font.weight"] = "normal"
plt.rcParams["axes.titleweight"] = "normal"
plt.rcParams["axes.labelweight"] = "normal"

# ==================== 强制路径约束（覆盖 plt.savefig） ====================
CHART_DIR = "data/charts"
os.makedirs(CHART_DIR, exist_ok=True)

_original_savefig = plt.savefig

def _patched_savefig(*args, **kwargs):
    if args and isinstance(args[0], str):
        original_path = args[0]
        filename = os.path.basename(original_path)
        new_path = os.path.join(CHART_DIR, filename)
        args = (new_path,) + args[1:]
    else:
        import time
        filename = f"chart_auto_{int(time.time())}.png"
        new_path = os.path.join(CHART_DIR, filename)
        args = (new_path,) + args
    print(f"  [INFO] 正在保存图表: {new_path} ...")
    kwargs.setdefault('dpi', 150)
    kwargs.setdefault('bbox_inches', 'tight')
    _original_savefig(*args, **kwargs)
    print(f"  [OK] 图表已保存: {new_path}")

plt.savefig = _patched_savefig

# ==================== pandas 3.x 兼容 patch ====================
import pandas as _pd
_old_resample = _pd.DataFrame.resample
def _patched_resample(self, rule, *args, **kwargs):
    rule_map = {'M': 'ME', 'Y': 'YE', 'Q': 'QE', 'D': 'DE', 'H': 'h', 'T': 'min', 'S': 's'}
    if isinstance(rule, str) and rule in rule_map:
        rule = rule_map[rule]
    return _old_resample(self, rule, *args, **kwargs)
_pd.DataFrame.resample = _patched_resample
"""
    if data_path and os.path.exists(data_path):
        # 注入的加载代码也按后缀分流（和 read_any 保持一致）——
        # 沙箱代码必须自包含，不能直接 import 项目里的 read_any
        load_code = f"""
# ==================== 按后缀自动选择读取方式 ====================
_p = r'{data_path}'
_ext = os.path.splitext(_p)[1].lower()
if _ext in ('.xlsx', '.xls'):
    df = pd.read_excel(_p)
elif _ext == '.tsv':
    df = pd.read_csv(_p, sep='\\t')
elif _ext == '.txt':
    df = pd.read_csv(_p, sep=None, engine='python')
elif _ext == '.json':
    df = pd.read_json(_p)
elif _ext == '.parquet':
    df = pd.read_parquet(_p)
else:
    df = pd.read_csv(_p)
"""
        return font_setup + load_code
    else:
        return font_setup + "\ndf = None  # 数据文件不存在\n"


def extract_result_tag(full_output: str) -> str:
    """
    从沙箱 stdout 中精准提取 __RESULT_START__ 与 __RESULT_END__ 之间的分析结论。

    来源: agents/nodes/executor.py::_extract_result
    保证返回值非空（极端兜底会原样返回 stdout 文本）。
    """
    full_output = full_output or ""

    m = re.search(r"__RESULT_START__\s*\n(.*?)\n__RESULT_END__", full_output, re.DOTALL)
    core_result = m.group(1).strip() if m else ""

    info_lines = []
    for line in full_output.splitlines():
        if any(tag in line for tag in ["[INFO]", "[OK]", "[分析结论]", "图表"]):
            info_lines.append(line)
    logs_block = "\n".join(info_lines).strip()

    parts = []
    if core_result:
        parts.append(f"【分析结论】\n{core_result}")
    if logs_block:
        parts.append(f"【执行日志】\n{logs_block}")
    if not parts:
        parts.append(full_output.strip() or "(沙箱执行已成功完成，但代码未输出任何文本结果)")

    return "\n\n".join(parts)


# =============================================================
# 3. 图表工具
# =============================================================

def cleanup_charts(charts_dir: str = "data/charts") -> None:
    """清空图表目录中的所有旧 PNG（executor 执行前调用）。"""
    os.makedirs(charts_dir, exist_ok=True)
    for f in os.listdir(charts_dir):
        if f.endswith(".png"):
            os.remove(os.path.join(charts_dir, f))


def cleanup_root_charts() -> None:
    """清理项目根目录下误生成的 datachart_*.png 文件。"""
    for f in os.listdir("."):
        if f.startswith("datachart_") and f.endswith(".png"):
            try:
                os.remove(f)
            except Exception:
                pass


def collect_charts(charts_dir: str = "data/charts") -> list[str]:
    """扫描目录，返回所有 PNG 文件名列表。"""
    if not os.path.exists(charts_dir):
        return []
    return [f for f in os.listdir(charts_dir) if f.endswith(".png")]


def generate_auto_charts(
    df: pd.DataFrame,
    charts_dir: str = "data/charts",
) -> list[str]:
    """
    根据 DataFrame 列类型自动生成 6 张通用图表：
    折线图 / 柱状图 / 饼图 / 分布图(直方图+箱线图) / 热力图 / 散点图

    来源: agents/nodes/visualizer.py 的后半部分（自动补充通用图）
    被 visualizer_node 调用。

    Returns:
        成功生成的图表文件路径列表
    """
    os.makedirs(charts_dir, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Zen Hei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False

    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52",
              "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    datetime_cols = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()

    # 尝试将 object 列解析为日期
    for col in cat_cols[:]:
        try:
            parsed = pd.to_datetime(df[col])
            if parsed.notna().sum() > len(df) * 0.5:
                datetime_cols.append(col)
                cat_cols.remove(col)
        except (ValueError, TypeError):
            pass

    generated: list[str] = []

    # 1. 时间趋势图（折线图）
    if datetime_cols and numeric_cols:
        try:
            dt_col = datetime_cols[0]
            num_col = numeric_cols[0]
            temp_df = df.copy()
            temp_df[dt_col] = pd.to_datetime(temp_df[dt_col])
            temp_df = temp_df.sort_values(dt_col)

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(temp_df[dt_col], temp_df[num_col],
                    color=colors[0], linewidth=2, marker="o", markersize=3)
            ax.set_title(f"{num_col} 随时间变化趋势", fontsize=14)
            ax.set_xlabel(dt_col)
            ax.set_ylabel(num_col)
            plt.xticks(rotation=45, ha="right")
            path = f"{charts_dir}/chart_01_trend.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 折线图生成失败: {e}")

    # 2. 分类对比图（柱状图）
    if cat_cols and numeric_cols:
        try:
            cat_col = cat_cols[0]
            num_col = numeric_cols[0]
            grouped = df.groupby(cat_col)[num_col].mean().sort_values(ascending=False)
            if len(grouped) > 15:
                grouped = grouped.head(15)

            fig, ax = plt.subplots(figsize=(10, 5))
            grouped.plot(kind="bar", ax=ax, color=colors[:len(grouped)],
                        edgecolor="black", alpha=0.85)
            ax.set_title(f"各{cat_col}的{num_col}均值对比", fontsize=14)
            ax.set_xlabel(cat_col)
            ax.set_ylabel(f"{num_col} (均值)")
            plt.xticks(rotation=45, ha="right")
            path = f"{charts_dir}/chart_02_category_bar.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 柱状图生成失败: {e}")

    # 3. 占比分布图（饼图）
    if cat_cols:
        try:
            cat_col = cat_cols[0]
            counts = df[cat_col].value_counts()
            if len(counts) > 8:
                top = counts.head(7)
                top["其他"] = counts.iloc[7:].sum()
                counts = top

            fig, ax = plt.subplots(figsize=(7, 7))
            ax.pie(counts.values, labels=counts.index, autopct="%1.1f%%",
                   colors=colors[:len(counts)], startangle=90,
                   textprops={"fontsize": 10})
            ax.set_title(f"{cat_col} 占比分布", fontsize=14)
            path = f"{charts_dir}/chart_03_pie.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 饼图生成失败: {e}")

    # 4. 分布图（直方图 + 箱线图）
    if numeric_cols:
        try:
            col = numeric_cols[0]
            fig, axes = plt.subplots(1, 2, figsize=(14, 5))

            axes[0].hist(df[col].dropna(), bins=20, edgecolor="black",
                         alpha=0.7, color=colors[0])
            axes[0].set_title(f"{col} 分布（直方图）", fontsize=13)
            axes[0].set_xlabel(col)
            axes[0].set_ylabel("频次")

            axes[1].boxplot(df[col].dropna(), vert=True,
                            patch_artist=True,
                            boxprops=dict(facecolor=colors[1], alpha=0.7))
            axes[1].set_title(f"{col} 分布（箱线图）", fontsize=13)
            axes[1].set_ylabel(col)

            path = f"{charts_dir}/chart_04_distribution.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 分布图生成失败: {e}")

    # 5. 相关性热力图
    if len(numeric_cols) >= 2:
        try:
            corr = df[numeric_cols].corr()
            fig, ax = plt.subplots(figsize=(max(8, len(numeric_cols) * 1.2),
                                             max(6, len(numeric_cols) * 0.9)))
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r",
                        center=0, ax=ax, square=True,
                        linewidths=0.5, cbar_kws={"shrink": 0.8})
            ax.set_title("数值列相关性热力图", fontsize=14)
            path = f"{charts_dir}/chart_05_heatmap.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 热力图生成失败: {e}")

    # 6. 散点图
    if len(numeric_cols) >= 2:
        try:
            x_col = numeric_cols[0]
            y_col = numeric_cols[1]
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.scatter(df[x_col], df[y_col], alpha=0.5,
                       color=colors[0], edgecolors="white", s=30)

            try:
                z = np.polyfit(df[x_col].dropna(), df[y_col].dropna(), 1)
                p = np.poly1d(z)
                x_range = np.linspace(df[x_col].min(), df[x_col].max(), 100)
                ax.plot(x_range, p(x_range), "--", color=colors[3],
                        linewidth=2, label=f"趋势线 (y={z[0]:.2f}x+{z[1]:.2f})")
                ax.legend()
            except Exception:
                pass

            ax.set_title(f"{x_col} vs {y_col}", fontsize=14)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            path = f"{charts_dir}/chart_06_scatter.png"
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            generated.append(path)
        except Exception as e:
            print(f"  [tools] 散点图生成失败: {e}")

    return generated


# =============================================================
# 4. 报告工具
# =============================================================

def save_report_md(
    report_text: str,
    reports_dir: str = "data/reports",
) -> str:
    """
    把 LLM 生成的 Markdown 报告写入文件。

    来源: agents/nodes/reporter.py
    Returns:
        保存的文件绝对路径
    """
    os.makedirs(reports_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"{reports_dir}/report_{timestamp}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return report_path


# =============================================================
# 5. RAG 历史经验工具
# =============================================================

def search_history(query: str, top_k: int = 3) -> list[dict]:
    """
    从历史经验库中检索相似分析案例。

    来源: retrieval/__init__.py::search_similar
    被 planner.py 调用。检索失败时返回空列表（不阻塞主流程）。
    """
    try:
        from retrieval import search_similar, get_history_count
        if get_history_count() == 0:
            return []
        return search_similar(query, top_k=top_k)
    except Exception as e:
        print(f"  [tools.RAG] 检索异常（跳过）: {e}")
        return []


def store_history(
    user_query: str,
    analysis_code: str,
    report: str,
    execution_result: str,
    chart_paths: list[str],
) -> bool:
    """
    把本次成功的分析存入历史经验库。

    来源: retrieval/__init__.py::store_analysis
    被 reporter.py 调用。存储失败时返回 False（不阻塞主流程）。
    """
    try:
        from retrieval import store_analysis
        store_analysis(
            user_query=user_query,
            analysis_code=analysis_code,
            report=report,
            execution_result=execution_result,
            chart_paths=chart_paths,
        )
        return True
    except Exception as e:
        print(f"  [tools.RAG] 存储异常（跳过）: {e}")
        return False
