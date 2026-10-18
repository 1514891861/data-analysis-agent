# evaluation/dataset.py
import os

DATA_PATH = os.path.join("data", "input", "sales.csv")

EVAL_CASES = [
    # ========== 趋势分析（3 条）==========
    {
        "query": "分析销售数据的月度趋势变化",
        "category": "趋势分析",
        "expect_report": True,
        "min_charts": 2,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "整体销售额的变化趋势",
        "category": "趋势分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "各产品销量随时间的变化情况",
        "category": "趋势分析",
        "expect_report": True,
        "min_charts": 2,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    
    # ========== 对比分析（3 条）==========
    {
        "query": "对比不同 region 地区的销售额",
        "category": "对比分析",
        "expect_report": True,
        "min_charts": 2,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "对比不同 product 产品的销量",
        "category": "对比分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "category 维度的销售数据对比",
        "category": "对比分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },

    # ========== 占比分析（2 条）==========
    {
        "query": "各产品销售额占总销售额的比例",
        "category": "占比分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "各 region 销量的结构分布",
        "category": "占比分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },

    # ========== 综合分析（3 条）==========
    {
        "query": "综合统计：各产品在各 region 的销售情况",
        "category": "综合分析",
        "expect_report": True,
        "min_charts": 2,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "简单看一下这份数据里的销售额和销量",
        "category": "综合分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "找到销售额最高和最低的产品分别是什么",
        "category": "综合分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },

    # ========== 边界 case（4 条）==========
    {
        "query": "asdfghjkl qwerty 123456",
        "category": "边界case_垃圾query",
        "expect_report": True,   # 就算是垃圾 query，graph 也应该跑完不崩，reporter 总要生成 report
        "min_charts": 0,        # 不要求图表
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "算一下数据",
        "category": "边界case_极短query",
        "expect_report": True,
        "min_charts": 0,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "找出数据里的异常值和离群点",
        "category": "综合分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
    {
        "query": "price 单价和 quantity 销量之间有没有相关性？",
        "category": "综合分析",
        "expect_report": True,
        "min_charts": 1,
        "max_retry": 3,
        "timeout_seconds": 300,
    },
]

# 最后打印总数确认
print(f"[evaluation/dataset.py] 共 {len(EVAL_CASES)} 条评测用例")