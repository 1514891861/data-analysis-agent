import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluation.dataset import EVAL_CASES, DATA_PATH
from evaluation.metrics import run_evaluation, print_eval_summary
import time

if __name__ == "__main__":
    print(f"🧪 开始完整评测，共 {len(EVAL_CASES)} 条，预估 30-45 分钟...\n")
    t0 = time.time()
    results = run_evaluation(EVAL_CASES, DATA_PATH)
    print_eval_summary(results)
    print(f"\n总共耗时: {time.time()-t0:.1f}s ({(time.time()-t0)/60:.1f}min)")
    
    # 可选：把结果存成 JSON 方便后续参考
    import json
    with open("evaluation_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 详细结果已保存到 evaluation_result.json")