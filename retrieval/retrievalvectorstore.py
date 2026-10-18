"""ChromaDB 向量库操作 — 存历史分析、查相似经验。"""
import os
import uuid
from config import BASE_DIR

# 持久化目录（data/chroma_db/）
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
COLLECTION_NAME = "analysis_history"

# 🔑 延迟初始化 + 缓存 ChromaDB client
_client = None
_collection = None

def _get_collection():
    """返回 ChromaDB collection，单例"""
    global _client, _collection
    if _collection is None:
        import chromadb
        # 如果装了 chromadb-milvus 之类的后端可以换掉，默认 PersistentClient 就够了
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            # 指定用我们自己的 embedding 函数（BGE-M3）
            embedding_function=None,   # 我们自己算好向量再传进去，不走 ChromaDB 内置的
        )
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    return _collection

# ============ 核心函数 1：存一条历史分析 ============

def store_analysis(user_query: str, analysis_code: str, report: str, 
                    execution_result: str = "", chart_paths: list = None):
    """
    把一次成功的分析存入 ChromaDB，便于后续检索复用。

    存进去的内容分两块：
    - embedding 输入（拼接后的长文本）：用来算相似度、查相关
    - metadata（结构化字段）：方便后面按 user_query 过滤
    """
    try:
        from retrieval.retrievalembeddings import get_embedding

        coll = _get_collection()

        # 拼接成一段长文本做 embedding（query + plan + code + report，越全越准）
        # 截断到 4000 字符以内，BGE-M3 最大支持 8192，我们保守一点
        combined_text = f"用户需求: {user_query}\n"
        combined_text += f"分析代码:\n{analysis_code[:1500]}\n"    # 代码只取前 1500
        combined_text += f"执行结果:\n{execution_result[:1000]}\n"   # 执行结果只取前 1000
        combined_text += f"报告摘要:\n{report[:1500]}"               # 报告只取前 1500

        if len(combined_text) > 4000:
            combined_text = combined_text[:4000]

        # 算向量
        vec = get_embedding(combined_text)
        doc_id = str(uuid.uuid4())

        coll.add(
            ids=[doc_id],
            embeddings=[vec],
            documents=[combined_text],
            metadatas=[{
                "user_query": user_query,
                "analysis_code": analysis_code[:2000],  # metadata 里也存一份，retrieve 时可取
                "report_summary": report[:500],
                "has_charts": bool(chart_paths and len(chart_paths) > 0),
            }]
        )
        print(f"  [RAG] 已存入历史分析 (id={doc_id[:8]}..., 向量维度={len(vec)})")
        return True

    except Exception as e:
        print(f"  [RAG] 存储失败（不影响主流程）: {type(e).__name__}: {e}")
        return False

# ============ 核心函数 2：查相似历史 ============

def search_similar(user_query: str, top_k: int = 3) -> list[dict]:
    """
    根据用户当前的 query，从 ChromaDB 里查 top_k 条最相似的历史分析。

    返回格式：
    [
        {
            "user_query": "之前用户也问过的 query",
            "analysis_code": "上次成功的代码片段",
            "report_summary": "上次生成的报告摘要",
            "distance": 0.1234,   # 余弦距离，越小越相似
        },
        ...
    ]
    """
    try:
        from retrieval.retrievalembeddings import get_embedding

        coll = _get_collection()

        # 如果 collection 是空的，直接返回空列表（第一次跑肯定空，别报错）
        if coll.count() == 0:
            print("  [RAG] 历史库为空，跳过检索")
            return []

        # 把当前 query 转成向量
        query_vec = get_embedding(user_query)

        # ChromaDB query
        results = coll.query(
            query_embeddings=[query_vec],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        # 解析 ChromaDB 返回的嵌套列表结构
        # results["metadatas"] = [[{...}, {...}, {...}]]  (外层是 query 的数量，内层是 top_k)
        hits = []
        if results and results["metadatas"] and results["metadatas"][0]:
            metadatas = results["metadatas"][0]
            distances = results.get("distances", [[None]*top_k])[0]
            documents = results.get("documents", [[""]*top_k])[0]

            for i, meta in enumerate(metadatas):
                hits.append({
                    "user_query": meta.get("user_query", ""),
                    "analysis_code": meta.get("analysis_code", ""),
                    "report_summary": meta.get("report_summary", ""),
                    "distance": distances[i] if distances[i] is not None else 1.0,
                    "document": documents[i] if documents[i] else "",
                })

        print(f"  [RAG] 检索到 {len(hits)} 条相似历史 (距离范围: {[round(h['distance'],2) for h in hits]})")
        return hits

    except Exception as e:
        print(f"  [RAG] 检索失败（不影响主流程）: {type(e).__name__}: {e}")
        return []

def get_history_count() -> int:
    """返回历史库条数（调试用）"""
    try:
        coll = _get_collection()
        return coll.count()
    except Exception:
        return 0