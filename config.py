import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# LLM 配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "deepseek-v4-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# Embedding 配置
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
# RAG 检索配置
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

# 沙箱配置
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "30"))
SANDBOX_MAX_MEMORY_MB = int(os.getenv("SANDBOX_MAX_MEMORY_MB", "256"))
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_INPUT_DIR = os.path.join(BASE_DIR, "data", "input")
DATA_CHARTS_DIR = os.path.join(BASE_DIR, "data", "charts")
DATA_REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")

# LangSmith 追踪
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "true")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "data-analysis-agent")