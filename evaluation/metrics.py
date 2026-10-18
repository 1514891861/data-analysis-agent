# evaluation/metrics.py
import os
import uuid
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


def _run_single_case(query: str, data_path: str, max_retry: int = 3) -> dict:
    """输入：query 字符串 + 数据路径；输出：包含 state + 耗时 + 错误的 dict"""
    from langgraph.checkpoint.sqlite import SqliteSaver
    from agents.graph import build_graph

    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    start_time = time.time()
    error_msg = None
    state_values = None

    try:
        with SqliteSaver.from_conn_string(tmp_db.name) as cp:
            graph = build_graph(checkpointer=cp)
            initial = {
                "user_query": query,
                "data_path": os.path.abspath(data_path),
                "data_summary": "",
                "analysis_plan": "",
                "analysis_code": "",
                "execution_result": "",
                "error_message": "",
                "retry_count": 0,
                "review_result": "",
                "approved": False,
                "chart_paths": [],
                "report": "",
                "report_path": "",
            }
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            last_values = None
            for chunk in graph.stream(initial, config=config, stream_mode="updates"):
                last_values = graph.get_state(config).values
            state_values = last_values if last_values else {}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"

    elapsed = round(time.time() - start_time, 1)
    try: os.unlink(tmp_db.name)
    except: pass

    return {"query": query, "elapsed": elapsed, "error": error_msg, "state": state_values}


def _score_case(result_dict: dict, case_def: dict) -> dict:
    """把 _run_single_case 的结果和 dataset.py 的标注对比，判断 task_success"""
    state = result_dict["state"]
    result_dict["category"] = case_def["category"]

    if state is None:
        result_dict["report_ok"] = False
        result_dict["chart_count"] = 0
        result_dict["charts_ok"] = False
        result_dict["retry_count"] = -1
        result_dict["task_success"] = False
        return result_dict

    report_text = state.get("report", "")
    approved = state.get("approved", False)
    # 失败标志词：reporter 在"执行状态"一节如实报告失败时必然用到的措辞
    fail_markers = ("执行失败", "无法执行", "代码未通过审核")
    has_fail_marker = any(m in report_text[:300] for m in fail_markers)

    result_dict["report_ok"] = bool(report_text) and approved and not has_fail_marker
    result_dict["approved"] = approved   # 新增字段：方便在 evaluation_result.json 里直接看到审核结果
    result_dict["chart_count"] = len(state.get("chart_paths", []))
    result_dict["charts_ok"] = result_dict["chart_count"] >= case_def["min_charts"]
    result_dict["retry_count"] = state.get("retry_count", 0)
    result_dict["task_success"] = (
        not result_dict["error"] and result_dict["report_ok"] and result_dict["charts_ok"]
    )
    return result_dict


def run_evaluation(cases, data_path):
    """把所有 case 跑一遍，返回 list[dict]（单条超时保护版）"""
    results = []
    total = len(cases)
    for i, case in enumerate(cases):
        print(f"\n[{i+1}/{total}] 跑: {case['query'][:40]}")
        limit = case.get("timeout_seconds", 300)   # 用上 dataset 里写好的超时
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run_single_case, case["query"], data_path)
            try:
                raw = fut.result(timeout=limit)
            except FutureTimeout:
                elapsed = round(time.time() - t0, 1)
                print(f"  ⏰ 超过 {limit}s，强制跳过本条")
                raw = {
                    "query": case["query"],
                    "elapsed": elapsed,
                    "error": f"单条超时（>{limit}s），已跳过",
                    "state": None,
                }
        scored = _score_case(raw, case)
        results.append(scored)
        if scored["error"]:
            print(f"  ❌ 崩溃: {scored['error']}")
        elif scored["task_success"]:
            print(f"  ✅ 通过 ({scored['elapsed']}s, {scored['chart_count']}图, retry={scored['retry_count']})")
        else:
            parts = []
            if not scored["report_ok"]: parts.append("无报告/报告不合格")
            if not scored["charts_ok"]: parts.append(f"图不够({scored['chart_count']}/{case['min_charts']})")
            print(f"  ⚠️  部分通过: {', '.join(parts)}")
    return results


def print_eval_summary(results):
    """打印汇总表"""
    from collections import defaultdict
    total = len(results)
    passed = sum(1 for r in results if r["task_success"])
    rate = passed / total * 100 if total > 0 else 0
    total_time = sum(r["elapsed"] for r in results)
    avg_time = total_time / total if total > 0 else 0

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "未分类")].append(r)

    print("\n" + "=" * 60)
    print("  📊 EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  总用例:   {total}")
    print(f"  通过:     {passed}")
    print(f"  通过率:   {rate:.1f}%")
    print(f"  总耗时:   {total_time:.1f}s  ({total_time/60:.1f}min)")
    print(f"  平均耗时: {avg_time:.1f}s/条")
    print()
    print("  按类别细分:")
    print("  " + "-" * 56)
    for cat in sorted(by_cat.keys()):
        rs = by_cat[cat]
        cat_pass = sum(1 for r in rs if r["task_success"])
        cat_rate = cat_pass / len(rs) * 100
        cat_time = sum(r["elapsed"] for r in rs) / len(rs)
        print(f"  {cat:<16} {cat_pass}/{len(rs)} 通过  ({cat_rate:.0f}%)  均 {cat_time:.0f}s")
    print("=" * 60)

    failures = [r for r in results if not r["task_success"]]
    if failures:
        print("\n  ❌ 失败详情:")
        for r in failures:
            if r["error"]:
                print(f"    - [{r['category']}] {r['query'][:35]} → 崩溃: {r['error'][:50]}")
            else:
                reason = []
                if not r["report_ok"]: reason.append("无报告")
                if not r["charts_ok"]: reason.append(f"图不够({r['chart_count']})")
                print(f"    - [{r['category']}] {r['query'][:35]} → {', '.join(reason)}")
