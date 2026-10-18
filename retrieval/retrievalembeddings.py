"""Embedding 模型封装 — 把文本转成向量，给 ChromaDB 用。

优先用本地 BGE-M3（sentence-transformers），失败时自动降级到智谱 embedding API。
降级只做一次，之后再也不试本地模型了，避免每次都卡 torch DLL 加载。
"""
import os
import time
import requests
from config import EMBEDDING_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY

# 🔑 延迟初始化 + 缓存
_local_model = None        # 本地 BGE-M3 模型
_fallback_to_api = False   # 是否已经降级到 API

# 缓存 API client
_api_key = None
_api_base = None


def _init_api_config():
    """初始化 API 配置（从 .env 读取）"""
    global _api_key, _api_base
    if _api_key is None:
        _api_key = LLM_API_KEY
        # 智谱的 embedding endpoint 和 chat endpoint 一样
        _api_base = LLM_BASE_URL.rstrip("/")


def _try_local_model():
    """尝试加载本地 BGE-M3，成功返回 model，失败设 _fallback_to_api=True"""
    global _local_model, _fallback_to_api
    if _fallback_to_api:
        return None  # 已经跳过本地了
    if _local_model is not None:
        return _local_model
    
    try:
        t0 = time.time()
        print("  [RAG] 尝试加载本地 BGE-M3 (sentence-transformers)...")
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        print(f"  [RAG] ✅ BGE-M3 加载完成 ({time.time()-t0:.1f}s)")
        return _local_model
    except Exception as e:
        print(f"  [RAG] ⚠️ 本地 BGE-M3 加载失败: {e}")
        print(f"  [RAG] 🔄 自动降级到智谱 embedding API")
        _fallback_to_api = True
        return None


def _api_embed_single(text: str) -> list:
    """调智谱 API 做单条 embedding"""
    _init_api_config()
    resp = requests.post(
        f"{_api_base}/embeddings",
        headers={
            "Authorization": f"Bearer {_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "embedding-3",
            "input": text,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def get_embedding(text: str) -> list:
    """把一段文本转成向量"""
    model = _try_local_model()
    if model is not None:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    else:
        return _api_embed_single(text)


def get_embeddings_batch(texts: list[str]) -> list[list]:
    """批量 embedding"""
    model = _try_local_model()
    if model is not None:
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return vecs.tolist()
    else:
        # API 没有批量接口，一条条转
        return [_api_embed_single(t) for t in texts]
