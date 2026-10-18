"""
api.py —— 数据分析 Agent 的后端接口

职责：把 agents/graph.py 的工作流包装成 HTTP 接口，给前端调用。
运行方式（项目根目录）：
    & "D:\Agent Project\data_analysis_agent\langgraph_env\Scripts\python.exe" -m uvicorn api:app --reload --port 8001
"""

import os
import json
import sqlite3
import shutil
from datetime import datetime
from contextlib import asynccontextmanager
from config import MAX_RETRY, DATA_INPUT_DIR

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from agents.graph import build_graph
from config import MAX_RETRY
from langgraph.checkpoint.sqlite import SqliteSaver

load_dotenv()

DB_PATH = "data/checkpoints_web.db"  # LangGraph checkpoint 库：存每个会话的"记忆"（data_path、分析上下文）
HISTORY_DB = "data/web_history.db"   # 历史记录库：存会话列表 + 聊天消息，专门给前端"历史会话"功能用
CHARTS_DIR = "data/charts"         # agent 生成的图表都放这里，前端通过 /charts/xxx.png 访问
ALLOWED_EXT = {".csv", ".xlsx", ".xls", ".tsv", ".txt", ".json", ".parquet"}   # 允许上传/分析的数据格式白名单

# 全局变量：服务存活期间一直复用这三个对象
graph = None
conn = None
hist_conn = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时加载 graph + 建历史表，关闭时释放数据库连接"""
    global graph, conn, hist_conn
    # check_same_thread=False：FastAPI 每个请求可能在不同线程执行，SQLite 需要放开这个限制
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    graph = build_graph(checkpointer=checkpointer)

    # ===== 历史记录两张表 =====
    # conversations：会话列表（侧边栏那一列）
    # messages：聊天消息（每个会话下的用户提问和 AI 回复）
    hist_conn = sqlite3.connect(HISTORY_DB, check_same_thread=False)
    hist_conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            thread_id  TEXT PRIMARY KEY,
            title      TEXT,
            created_at TEXT
        )""")
    hist_conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id  TEXT,
            role       TEXT,      -- 'user' 或 'assistant'
            content    TEXT,      -- 消息文本（AI 侧存的是报告全文）
            charts     TEXT,      -- 图表 URL 列表（JSON 数组字符串）
            created_at TEXT
        )""")
    # 置顶字段（后期加的列：老库已存在时 ALTER 会报"列已存在"，忽略即可）
    try:
        hist_conn.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    hist_conn.commit()

    print("✅ [api] 工作流已加载，API 就绪")
    yield
    conn.close()
    hist_conn.close()
    print("👋 [api] 数据库连接已关闭")

app = FastAPI(title="数据分析 Agent API", lifespan=lifespan)

# 跨域放行：Streamlit 页面(8501端口)调后端(8001端口)属于跨域，不放开前端会报 CORS 错
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 把 data/charts 目录挂成静态文件：前端访问 http://localhost:8001/charts/xxx.png 即可看图
os.makedirs(CHARTS_DIR, exist_ok=True)
app.mount("/charts", StaticFiles(directory=CHARTS_DIR), name="charts")

# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    thread_id: str          # 会话ID：前端为每个浏览器会话生成一个，实现多轮记忆
    message: str            # 用户输入的分析需求
    data_path: str = ""     # 数据文件路径：首轮必填，后续轮留空

# ==================== 接口 ====================

@app.get("/health")
def health():
    """健康检查：前端启动时ping一下，确认后端活着"""
    return {"status": "ok"}

@app.post("/chat")
def chat(req: ChatRequest):
    """核心接口：跑一遍完整工作流，返回报告和图表"""
    config = {"configurable": {"thread_id": req.thread_id}}

    # 判断是首轮还是后续轮（首轮 state 里还没有 data_path）
    snapshot = graph.get_state(config)
    locked_path = snapshot.values.get("data_path", "")   # 当前会话已锁定的数据文件
    is_first_round = not locked_path

    if is_first_round:
        if not req.data_path or not os.path.exists(req.data_path):
            return {"error": "首轮分析必须提供有效的 data_path（数据文件路径）"}
        # 首轮：把会话登记进历史列表（标题取需求前20字，像豆包那样）
        # OR IGNORE：同一 thread_id 万一重复登记不会主键冲突报错
        hist_conn.execute(
            "INSERT OR IGNORE INTO conversations (thread_id, title, created_at) VALUES (?,?,?)",
            (req.thread_id, req.message[:20], datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        hist_conn.commit()
        # 首轮：完整初始状态（和 main.py 的 build_initial_state 一致）
        initial_state = {
            "user_query": req.message,
            "data_path": req.data_path,
            "data_summary": "",
            "analysis_plan": "",
            "analysis_code": "",
            "execution_result": "",
            "error_message": "",
            "retry_count": 0,
            "max_retry": MAX_RETRY,
            "review_result": "",
            "approved": False,
            "chart_paths": [],
            "report": "",
            "report_path": "",
        }
    else:
        # 后续轮：只重置中间字段，保留对话记忆
        initial_state = {
            "user_query": req.message,
            "execution_result": "",
            "error_message": "",
            "retry_count": 0,
            "review_result": "",
            "approved": False,
            "chart_paths": [],
            "report": "",
            "report_path": "",
        }
        # 会话内换文件：本轮带来了新 data_path 且和 checkpoint 里锁定的不同
        # → 重置 data_path、清空 data_summary，load 节点会重读新文件生成新概览
        if req.data_path and req.data_path != locked_path:
            if not os.path.exists(req.data_path):
                return {"error": f"数据文件不存在: {req.data_path}"}
            initial_state["data_path"] = req.data_path
            initial_state["data_summary"] = ""

    try:
        # 跑工作流（和 main.py 的 run_graph 一致）
        result = None
        for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
            result = graph.get_state(config).values
    except Exception as e:
        return {"error": f"工作流执行出错: {e}"}

    # 把本地路径转成前端能访问的 URL
    chart_urls = [f"/charts/{os.path.basename(p)}" for p in result.get("chart_paths", [])]

    # ===== 把本轮对话写进历史库（前端"历史会话"的数据来源）=====
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # AI 侧文本 = 报告全文；报告为空就把错误信息当回复存进去，保证记录完整
    assistant_text = result.get("report", "") or f"（本轮执行出错: {result.get('error_message', '')}）"
    hist_conn.execute(
        "INSERT INTO messages (thread_id, role, content, charts, created_at) VALUES (?,?,?,?,?)",
        (req.thread_id, "user", req.message, "[]", now),
    )
    hist_conn.execute(
        "INSERT INTO messages (thread_id, role, content, charts, created_at) VALUES (?,?,?,?,?)",
        (req.thread_id, "assistant", assistant_text, json.dumps(chart_urls, ensure_ascii=False), now),
    )
    hist_conn.commit()

    # 本轮实际生效的数据文件：换了就返回新路径，没换返回锁定路径（前端拿它跟踪 active_file）
    effective_path = req.data_path if (is_first_round or (req.data_path and req.data_path != locked_path)) else locked_path

    return {
        "report": result.get("report", ""),
        "chart_urls": chart_urls,
        "retry_count": result.get("retry_count", 0),
        "approved": result.get("approved", False),
        "error_message": result.get("error_message", ""),
        "data_path": effective_path,
    }

@app.get("/conversations")
def list_conversations():
    """历史会话列表：置顶的排最前，其余按创建时间倒序"""
    rows = hist_conn.execute(
        "SELECT thread_id, title, created_at, pinned FROM conversations "
        "ORDER BY pinned DESC, created_at DESC"
    ).fetchall()
    return {"conversations": [
        {"thread_id": r[0], "title": r[1], "created_at": r[2], "pinned": r[3] or 0}
        for r in rows
    ]}


class RenameRequest(BaseModel):
    title: str


class PinRequest(BaseModel):
    pinned: bool


@app.post("/conversations/{thread_id}/rename")
def rename_conversation(thread_id: str, req: RenameRequest):
    """重命名会话（标题最长 30 字）"""
    title = req.title.strip()[:30] or "未命名会话"
    hist_conn.execute(
        "UPDATE conversations SET title = ? WHERE thread_id = ?", (title, thread_id)
    )
    hist_conn.commit()
    return {"ok": True, "title": title}


@app.post("/conversations/{thread_id}/pin")
def pin_conversation(thread_id: str, req: PinRequest):
    """置顶（pinned=True）/ 取消置顶（pinned=False）"""
    hist_conn.execute(
        "UPDATE conversations SET pinned = ? WHERE thread_id = ?",
        (1 if req.pinned else 0, thread_id),
    )
    hist_conn.commit()
    return {"ok": True}


@app.delete("/conversations/{thread_id}")
def delete_conversation(thread_id: str):
    """删除会话：会话列表 + 聊天记录 + checkpoint 记忆，三处一起清"""
    hist_conn.execute("DELETE FROM conversations WHERE thread_id = ?", (thread_id,))
    hist_conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
    hist_conn.commit()
    # checkpoint 库（LangGraph 的会话记忆）也清掉，不留僵尸数据
    # 表名因 langgraph 版本而异，没有就跳过
    for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        try:
            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
            conn.commit()
        except sqlite3.OperationalError:
            pass
    return {"ok": True}


@app.get("/conversations/{thread_id}/messages")
def get_messages(thread_id: str):
    """拉取某个历史会话的全部聊天记录：前端点击历史会话时调用"""
    rows = hist_conn.execute(
        "SELECT role, content, charts FROM messages WHERE thread_id = ? ORDER BY id",
        (thread_id,),
    ).fetchall()
    return {"messages": [
        {"role": r[0], "content": r[1], "charts": json.loads(r[2])} for r in rows
    ]}

@app.get("/files")
def list_files():
    """列出 data/input 下所有可分析的数据文件（前端做成下拉框）"""
    os.makedirs(DATA_INPUT_DIR, exist_ok=True)
    files = sorted(
        f for f in os.listdir(DATA_INPUT_DIR)
        if os.path.splitext(f)[1].lower() in ALLOWED_EXT
    )
    return {"files": files}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """上传数据文件到 data/input 目录，返回保存后的路径"""
    # 1. basename：只取文件名本身，防止恶意路径（如 ../../xxx）写到别处
    safe_name = os.path.basename(file.filename)

    # 2. 后缀白名单：入口就把不认识的格式拦住（读取分流由 agents/tools.py 的 read_any 处理）
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXT:
        return {"error": f"暂不支持 {ext} 格式，目前支持：CSV / Excel / TSV / TXT / JSON / Parquet"}

    save_path = os.path.join(DATA_INPUT_DIR, safe_name)

    # 3. 把上传的内容写进磁盘
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"filename": safe_name, "data_path": save_path}