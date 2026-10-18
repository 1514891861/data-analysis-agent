# 🤖 数据分析 Agent（Data Analysis Agent）

上传一份数据文件，用一句自然语言描述需求，Agent 会自动完成：**数据解读 → 代码生成 → 沙箱执行 → 报错自修复 → 图表与 HTML 报告输出** 的完整分析闭环。

## ✨ 功能特性

- **自然语言数据分析**：基于 LangGraph 的多节点工作流（代码生成 → 沙箱执行 → 审查 → 自动修复，最多重试 3 次）
- **多格式支持**：CSV / XLSX / XLS / TSV / TXT / JSON / Parquet
- **安全沙箱**：AST 静态扫描拦截危险调用（`os.system`、`open` 敏感路径等）+ 30s 超时 + 256MB 内存限制
- **可视化输出**：matplotlib/seaborn 图表内嵌展示 + 可下载的 HTML 分析报告
- **历史会话**：侧边栏历史记录（时间分组 / 置顶 / 重命名 / 删除），与豆包/DeepSeek 相同的交互
- **RAG 知识库**：内置 BGE-M3 + ChromaDB，检索数据分析方法论辅助生成

## 🛠️ 技术栈

FastAPI · LangGraph · Streamlit · ChromaDB · BGE-M3 · pandas · matplotlib

## 🚀 本地运行（Docker Compose）

```bash
# 1. 项目根目录创建 .env，写入密钥：
#    LLM_API_KEY=sk-xxx
#    LLM_BASE_URL=https://api.deepseek.com
#    LLM_MODEL_NAME=deepseek-v4-flash

# 2. 一键启动
docker compose up --build -d

# 3. 访问
#    前端界面  http://localhost:8501
#    后端文档  http://localhost:8001/docs
```

> 首次做分析时会自动下载 BGE-M3 向量模型（约 2GB，国内网络默认走 hf-mirror 镜像），属正常现象。

## 🙏 致谢

[LangGraph](https://github.com/langchain-ai/langgraph) · [Streamlit](https://streamlit.io/) · [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
