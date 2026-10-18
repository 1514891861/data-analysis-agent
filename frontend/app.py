"""
frontend/app.py —— 数据分析 Agent 的前端界面（Streamlit）

运行方式（项目根目录）：
    & "D:\Agent Project\data_analysis_agent\langgraph_env\Scripts\python.exe" -m streamlit run frontend/app.py
"""

import html
import os
import uuid
from datetime import datetime, date

import requests
import streamlit as st

# ===== 配置：后端地址（端口要和你启动 api.py 时一致，你用的是 8001）=====
# Docker 部署时由 compose 注入 BACKEND_URL=http://backend:8001；本地开发默认 localhost
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")

# 本地服务不走系统代理（Clash等代理会劫持localhost请求导致连不上）
SESSION = requests.Session()
SESSION.trust_env = False

st.set_page_config(page_title="数据分析 Agent", page_icon="🤖", layout="wide")

# ===== 全局视觉样式（豆包/DeepSeek 式：浅色底 + 窄栏居中 + 渐变主色）=====
st.markdown("""
<style>
/* ---------- 全局 ---------- */
.stApp { background: #ffffff; }
#MainMenu, footer, [data-testid="stStatusWidget"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="block-container"] { max-width: 860px; padding-top: 1.2rem; }

/* ---------- 标题区 ---------- */
.app-title-sm { font-size: 1.05rem; font-weight: 700; color: #1f2328;
  margin-bottom: .8rem; }
.hero { text-align: center; font-size: 1.7rem; font-weight: 700;
  color: #1f2328; margin: 120px 0 20px; }
.empty-tip { text-align: center; color: #8a919f; font-size: .95rem;
  line-height: 2; margin-bottom: 2rem; }
.hero svg, .app-title-sm svg { vertical-align: -3px; margin-right: 6px; }
/* 侧边栏小节标题（线条图标 + 灰字） */
.side-label { color: #6b7280; font-size: .8rem; margin: 0 0 2px 6px;
  display: flex; align-items: center; gap: 6px; }

/* ---------- 用户气泡（右侧渐变蓝） ---------- */
.user-row { display: flex; justify-content: flex-end; margin: 10px 0; }
.user-bubble {
    background: linear-gradient(135deg, #3b82f6, #2563eb); color: #fff;
    padding: 10px 16px; border-radius: 18px 18px 6px 18px;
    max-width: 78%; word-break: break-word; white-space: pre-wrap;
    line-height: 1.6; font-size: 15px;
    box-shadow: 0 2px 8px rgba(37, 99, 235, .25);
}

/* ---------- AI 头像（圆形渐变） ---------- */
.ai-avatar { width: 36px; height: 36px; border-radius: 50%;
  background: linear-gradient(135deg, #4f8cff, #8f5cff);
  display: flex; align-items: center; justify-content: center; font-size: 18px;
  box-shadow: 0 2px 6px rgba(79, 140, 255, .35); }

/* ---------- 图表 ---------- */
[data-testid="stImage"] img { border-radius: 12px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, .08); }

/* ---------- 历史会话时间分组 ---------- */
.conv-group { color: #9aa1ac; font-size: .75rem; margin: 14px 0 2px 6px; }

/* ---------- 侧边栏 ---------- */
[data-testid="stSidebar"] { background: #f9fafb; border-right: 1px solid #eceef2; }
[data-testid="stSidebar"] .stButton > button {
  border: none; background: transparent; text-align: left;
  border-radius: 10px; font-size: .9rem; }
/* 会话行：hover 整行亮一整条（豆包式）——文字和 ⋯ 共享同一个悬浮区域 */
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) {
  border-radius: 8px; transition: background .12s ease;
  align-items: center;   /* ⋯ 与标题文字垂直居中对齐 */
  padding: 4px 8px !important;   /* 灰块内缩，左右不顶格（豆包式） */
  margin-top: -4px !important; margin-bottom: -4px !important; }   /* 抵消 padding 带来的行距变化 */
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]):hover {
  background: #f3f4f6; }
/* 行内瘦身：清掉 Streamlit 列/元素容器的默认留白（元凶：它们把灰块撑厚 12px+、把 ⋯ 顶上去） */
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) [data-testid="stColumn"],
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) [data-testid="stElementContainer"],
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) [data-testid="stVerticalBlock"] {
  margin: 0 !important; padding: 0 !important;
  gap: 0 !important; min-height: 0 !important; }
/* 根源修复：会话行已改用 st.container(horizontal=True)（Streamlit 专为窄容器设计的
   横排容器，永不堆叠）。CSS 只负责外观：hover 灰块 + 内缩 + 圆角 */
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) {
  border-radius: 8px; transition: background .12s ease;
  padding: 4px 8px !important;                  /* 灰块内缩，左右不顶格（豆包式） */
  margin-top: -4px !important; margin-bottom: -4px !important;   /* 抵消 padding 的行距变化 */
  gap: 0 !important; min-height: 0 !important; align-items: center !important; }
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]) [data-testid="stColumn"] {
  width: auto !important; min-width: 0 !important; }
/* 会话 ⋯ 按钮（豆包式）：剥掉默认样式，hover 会话行才浮现
   注意：不要加 aside/stSidebar 前缀！实测本版 Streamlit 的 popover 按钮不在侧边栏标签后代里，
   全页只有这 3 个 stPopoverButton，直接全局命中最稳 */
[data-testid="stPopoverButton"] {
  border: none !important; background: transparent !important;
  box-shadow: none !important; color: #9aa1ac !important;
  padding: 2px 8px !important; min-height: 0 !important;
  opacity: 0; }
/* 箭头是 Material 字体图标（expand_more），精确隐藏 */
[data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
  display: none !important; }
[data-testid="stHorizontalBlock"]:hover [data-testid="stPopoverButton"],
[data-testid="stPopoverButton"][aria-expanded="true"] {
  opacity: 1; }
/* 行 hover 之上，鼠标再移到 ⋯ 上：更深的圆角小块（豆包式的按钮感，与整行背景分层） */
[data-testid="stHorizontalBlock"]:has([data-testid="stPopoverButton"]):hover [data-testid="stPopoverButton"]:hover {
  background: #e2e5ea !important; border-radius: 6px !important; }
/* 菜单本体：紧凑白卡片，透明菜单项 hover 浅灰（恢复上条规则误伤的可见性） */
[data-testid="stPopoverBody"] {
  padding: 6px !important;
  min-width: 0 !important;      /* 清掉 Streamlit 默认的大 min-width（面板过宽的元凶） */
  width: 128px !important;      /* 面板定宽，刚好包住"取消置顶"最长项 */ }
[data-testid="stPopoverBody"] .stButton > button {
  border: none !important; background: transparent !important;
  border-radius: 8px; justify-content: flex-start; font-size: .9rem;
  padding: 6px 10px !important; min-height: 0 !important; opacity: 1 !important; }
[data-testid="stPopoverBody"] .stButton > button:hover { background: #f3f4f6 !important; }
/* 删除项：红色文字，hover 浅红底（源码顺序在后，覆盖上面的灰色规则） */
[data-testid="stPopoverBody"] button[kind="primary"],
[data-testid="stPopoverBody"] button[kind="primary"]:hover {
  background: transparent !important; color: #dc2626 !important; }
[data-testid="stPopoverBody"] button[kind="primary"]:hover {
  background: #fef2f2 !important; }

/* 「开启新对话」主按钮：蓝底白字胶囊 */
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #3b82f6, #2563eb); color: #fff;
  text-align: center; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] p::before {
  content: "+"; font-weight: 800; margin-right: 8px; }

/* ---------- 圆滑化杂项 ---------- */
/* 隐藏右上角 Deploy/工具栏 和 顶部装饰线 */
/* 隐藏右上角 Deploy 按钮/状态灯 和 顶部装饰线（stToolbar 本体保留——侧边栏收起后的展开箭头在里面） */
[data-testid="stDecoration"] { display: none; }
[data-testid="stDeployButton"], [data-testid="stStatusWidget"] { display: none !important; }
/* 侧边栏收起按钮常显（Streamlit 默认 hover 侧边栏才出现，实测外层容器 visibility:hidden） */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"] * {
  visibility: visible !important; opacity: 1 !important; }
/* 侧边栏小标题：小号灰字，更精致 */
[data-testid="stSidebar"] h3 { font-size: .95rem; color: #6b7280; letter-spacing: .5px; }
/* 欢迎提示已极简化（见标题区段，DeepSeek 式纯文字居中） */
/* 折叠面板/下载按钮/下拉框 圆角统一 */
[data-testid="stExpander"] { border-radius: 12px; border: 1px solid #eceef2; }
.stDownloadButton > button { border-radius: 10px; }
[data-testid="stSelectbox"] > div > div { border-radius: 10px; }
/* 输入框聚焦时边框跟主题蓝（主题文件之外的双保险） */
[data-testid="stChatInput"]:focus-within { border-color: #2563eb !important; }

/* ---------- 底部输入框 ---------- */
[data-testid="stChatInput"] { border-radius: 16px; border: 1px solid #e5e7eb;
  box-shadow: 0 4px 18px rgba(0, 0, 0, .06); }
</style>
""", unsafe_allow_html=True)

# ===== ⋯ 菜单自动收起（豆包/DeepSeek 式）：切走再切回页面时，自动关闭还开着的菜单 =====
# 难点：Streamlit 的 popover 没有编程式开关 API，且原生 st.html 组件运行在沙箱 iframe 里摸不到主页面。
# 方案：streamlit-js-eval 的组件 iframe 与主页面同源，可以在主页面 document 上注册一次监听——
#       页面重新可见（document.hidden 变 False）时，把所有开着的 popover 模拟点击一次，React 收到 click 即收起。
try:
    from streamlit_js_eval import streamlit_js_eval
    streamlit_js_eval(js_expressions=(
        # visibilitychange：切标签页/最小化后切回时触发；blur：切到其他应用窗口时触发
        "window.__menuAutoClose=1;"
        "function __closeOpenMenus(){"
        "document.querySelectorAll('[data-testid=\"stPopoverButton\"][aria-expanded=\"true\"]')"
        ".forEach(function(b){b.click();});}"
        "document.addEventListener('visibilitychange',function(){"
        "if(!document.hidden){__closeOpenMenus();}});"
        "window.addEventListener('blur',__closeOpenMenus);"
        "'hook-ok'"), key="menu_auto_close_hook")
except ImportError:
    pass   # 未装该包则跳过：菜单功能完全正常，只是没有"切回自动收起"

# ===== 线条风 SVG 图标（Lucide 风格，统一替代 emoji）=====
def svg_spark(size=18, color="#2563eb"):
    """四角星（spark）：AI 元素的统一图标"""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.8" stroke-linejoin="round">'
            '<path d="M12 3l1.8 7.2L21 12l-7.2 1.8L12 21l-1.8-7.2L3 12l7.2-1.8L12 3Z"/></svg>')


def svg_folder(size=14, color="#6b7280"):
    """文件夹线条图标"""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg>')


# 标题区：DeepSeek 式——空会话显示居中大标题，有对话后只留小标题
if st.session_state.get("messages"):
    st.markdown(f'<div class="app-title-sm">{svg_spark(17)} 数据分析 Agent</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="hero">{svg_spark(26)} 你好，我能帮你分析数据</div>', unsafe_allow_html=True)
    st.markdown('<div class="empty-tip">点输入框左侧 <b>📎</b> 上传一份 CSV/Excel 数据，然后问点什么都行<br>'
                '例如：<b>分析销量Top5的产品类别</b> · <b>销售额随时间的变化趋势</b> · <b>找出异常订单</b></div>',
                unsafe_allow_html=True)


def time_group(created_at: str) -> str:
    """把会话创建时间归入豆包式分组：今天/昨天/7 天内/30 天内/年-月"""
    try:
        d = datetime.strptime(created_at, "%Y-%m-%d %H:%M").date()
    except Exception:
        return "更早"
    diff = (date.today() - d).days
    if diff <= 0:
        return "今天"
    if diff == 1:
        return "昨天"
    if diff <= 7:
        return "7 天内"
    if diff <= 30:
        return "30 天内"
    return f"{d.year}-{d.month:02d}"


def render_user_msg(content: str):
    """用户消息：右侧浅蓝气泡。html.escape 防止输入里的 < > 破坏页面"""
    st.markdown(
        f'<div class="user-row"><span class="user-bubble">{html.escape(content)}</span></div>',
        unsafe_allow_html=True,
    )


def render_assistant_msg(content: str, charts: list):
    """AI 回复：左侧 🤖 头像列 + 正文列（豆包式无气泡），图表跟在正文下方"""
    _head, _body = st.columns([1, 30])   # 窄列放头像，宽列放正文
    with _head:
        st.markdown(f'<div class="ai-avatar">{svg_spark(18, "#fff")}</div>', unsafe_allow_html=True)
    with _body:
        st.markdown(content)                    # 报告是 markdown，直接渲染标题/表格/加粗
        for img in charts:
            try:
                st.image(img)                   # 图表字节直接显示
            except Exception:
                st.caption("（一张图表已失效，无法显示）")   # 兜底：坏字节只降级提示，不炸整页


def load_chart_bytes(url: str):
    """
    把图表 URL 下载成图片字节；只接受真正的图片响应，否则返回 None。
    关键校验：旧图表被新一轮分析清理后 /charts/xxx.png 返回 404 JSON，
    不检查状态码的话 JSON 文本会被当成图片字节存进去，渲染时 PIL 直接报错。
    """
    try:
        r = SESSION.get(f"{BACKEND_URL}{url}", timeout=10)
        if r.status_code != 200:
            return None
        if not r.headers.get("content-type", "").startswith("image/"):
            return None
        return r.content
    except Exception:
        return None

# ======================================================================
# 会话状态：Streamlit 的机制是"用户每点一下/输入一次，整个脚本从头跑一遍"，
# 所以普通变量每次都会被清空。session_state 是跨交互保存数据的"保险柜"。
# ======================================================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())   # 每个浏览器会话一个独立记忆
if "messages" not in st.session_state:
    st.session_state.messages = []   # 对话历史: [{"role": 用户/助手, "content": 文本, "charts": [图字节]}]
if "active_file" not in st.session_state:
    st.session_state.active_file = None   # 当前会话正在使用的数据文件名（后端锁定文件的镜像）

# ==================== 侧边栏 ====================
with st.sidebar:
    # 新建会话 = 换一个新的 thread_id（后端 checkpoint 就从零开始了）+ 清空聊天记录
    if st.button("开启新对话", type="primary", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.active_file = None   # 新会话没有锁定文件
        st.rerun()   # 立刻重跑整个脚本，刷新界面

    st.divider()
    # 每次渲染都拉一次列表（数据量小，开销可忽略），保证刚聊完的会话立刻出现
    try:
        convs = SESSION.get(f"{BACKEND_URL}/conversations", timeout=5).json().get("conversations", [])
    except Exception:
        convs = []
        st.caption("（连不上后端，历史列表不可用）")
    def open_conversation(tid):
        """切换会话：换 thread_id + 从后端拉这个会话的聊天记录"""
        st.session_state.thread_id = tid
        st.session_state.active_file = None   # 切换会话后重新跟踪文件
        try:
            hist = SESSION.get(
                f"{BACKEND_URL}/conversations/{tid}/messages", timeout=5
            ).json().get("messages", [])
            st.session_state.messages = [
                {
                    "role": m["role"],
                    "content": m["content"],
                    # 图表当场下载成字节固化（后端可能清理旧图），下载失败的图直接丢弃
                    "charts": [b for b in (load_chart_bytes(u) for u in m.get("charts", [])) if b],
                }
                for m in hist
            ]
        except Exception:
            st.session_state.messages = []
        st.rerun()

    last_group = None   # 分组标题（置顶/今天/7 天内/2026-08...），分组名变化才插入
    for c in convs:
        # 置顶的会话归入「置顶」分组（后端已把置顶排最前）
        g = "置顶" if c.get("pinned") else time_group(c.get("created_at", ""))
        if g != last_group:
            st.markdown(f'<div class="conv-group">{g}</div>', unsafe_allow_html=True)
            last_group = g

        # 每条会话一行：左边标题按钮，右边 ⋯ 菜单（置顶/重命名/删除）
        # 🔑 用 st.container(horizontal=True) 而不是 st.columns——
        # 侧边栏内容区永远小于 Streamlit 的 640px 响应式断点，
        # columns 在里面会被官方规则强制垂直堆叠（这就是 ⋯ 掉到标题下面的根源）；
        # horizontal 容器专为"窄容器里一行放多个元素"设计，永不堆叠
        tid = c["thread_id"]
        row = st.container(
            horizontal=True,
            horizontal_alignment="distribute",   # 标题靠左、⋯ 靠右，中间自动撑开（注意必须小写）
        )
        with row:
            label = ("●  " if tid == st.session_state.thread_id else "") + c["title"]
            if st.button(label, key=f"conv_{tid}"):
                open_conversation(tid)
            with st.popover("⋯", key=f"pop_{tid}"):
                # ===== 重命名（两级交互：先点菜单项 → 才展开输入框，避免菜单里顶着个输入框）=====
                if st.session_state.get(f"rn_open_{tid}"):
                    new_title = st.text_input("新名称", value=c["title"], key=f"rn_{tid}",
                                              label_visibility="collapsed")
                    ok_col, cancel_col = st.columns(2)
                    if ok_col.button("保存", key=f"rnok_{tid}", use_container_width=True):
                        if new_title.strip():
                            SESSION.post(f"{BACKEND_URL}/conversations/{tid}/rename",
                                         json={"title": new_title}, timeout=5)
                        st.session_state[f"rn_open_{tid}"] = False
                        st.rerun()
                    if cancel_col.button("取消", key=f"rncn_{tid}", use_container_width=True):
                        st.session_state[f"rn_open_{tid}"] = False
                        st.rerun()
                elif st.button("✏️ 重命名", key=f"rnbtn_{tid}", use_container_width=True):
                    st.session_state[f"rn_open_{tid}"] = True
                    st.rerun()
                # ===== 置顶 / 取消置顶 =====
                pin_txt = "📌 取消置顶" if c.get("pinned") else "📌 置顶"
                if st.button(pin_txt, key=f"pin_{tid}", use_container_width=True):
                    SESSION.post(f"{BACKEND_URL}/conversations/{tid}/pin",
                                 json={"pinned": not c.get("pinned")}, timeout=5)
                    st.rerun()
                # ===== 删除（primary 类型，CSS 渲染成红色文字）=====
                if st.button("🗑️ 删除", key=f"del_{tid}", type="primary", use_container_width=True):
                    SESSION.delete(f"{BACKEND_URL}/conversations/{tid}", timeout=5)
                    # 删的是当前打开的会话 → 回到一个全新会话
                    if tid == st.session_state.thread_id:
                        st.session_state.thread_id = str(uuid.uuid4())
                        st.session_state.messages = []
                        st.session_state.active_file = None
                    st.rerun()

    st.divider()
    st.markdown(f'<div class="side-label">{svg_folder()} 数据文件</div>', unsafe_allow_html=True)

    # 列出后端 data/input 里已有的文件（📎 只管传新文件，历史文件的复用靠这里）
    try:
        files = SESSION.get(f"{BACKEND_URL}/files", timeout=5).json().get("files", [])
    except Exception:
        files = []
        st.error("❌ 连不上后端！请先在另一个窗口启动 api.py 服务")
    selected_file = st.selectbox(
        "切换数据文件", files,
        label_visibility="collapsed",
        placeholder="选择文件（可不选）",
    ) if files else None
    # 当前会话生效的文件：📎 刚上传的 > 下拉框选的 > 无
    current = st.session_state.active_file or selected_file
    if current:
        st.caption(f"当前会话使用：`{current}`")

# ==================== 显示历史对话 ====================
for msg in st.session_state.messages:
    if msg["role"] == "user":
        render_user_msg(msg["content"])                                # 用户：右侧气泡
    else:
        render_assistant_msg(msg["content"], msg.get("charts", []))    # AI：左侧头像+正文

# ==================== 底部输入框（带 📎 上传按钮，豆包样式）====================
# accept_file=True 让输入框左侧出现回形针按钮：点击附带数据文件，选完即传
chat_val = st.chat_input(
    "输入你的分析需求，例如：分析销量Top5的产品类别",
    accept_file=True,
    file_type=["csv", "xlsx", "xls", "tsv", "txt", "json", "parquet"],
)

if chat_val is not None:
    # 兼容处理：带 accept_file 时返回对象（.prompt + .files），纯文本输入返回字符串
    prompt = getattr(chat_val, "prompt", chat_val) or ""
    up_files = getattr(chat_val, "files", None) or []

    # ---- 0. 带了附件：先上传（选完即传，和豆包一致）----
    pending_data_path = None   # 刚上传成功的文件路径，优先用它分析
    for f in up_files:
        try:
            resp = SESSION.post(
                f"{BACKEND_URL}/upload",
                files={"file": (f.name, f.getvalue())},
                timeout=30,
            )
            up_data = resp.json()
            if "error" in up_data:
                st.error(up_data["error"])
            else:
                st.success(f"📎 已上传: {up_data['data_path']}")
                pending_data_path = up_data["data_path"]   # 多个附件取最后一个
        except Exception as e:
            st.error(f"上传失败: {e}")
    if up_files and not pending_data_path:
        st.stop()   # 附件全部上传失败，不再继续
    if up_files and not prompt.strip():
        st.rerun()   # 只传了文件没输文字：上传完刷新，文件出现在左侧下拉框

    prompt = prompt.strip()

    # ---- 1. 校验：首轮必须有数据文件（左侧选的 或 刚用 📎 传的）----
    is_first_round = len(st.session_state.messages) == 0
    if is_first_round and not selected_file and not pending_data_path:
        st.warning("首轮分析请先选择数据文件，或点输入框左侧 📎 上传")
        st.stop()   # 中止本轮脚本，不往下执行

    # ---- 2. 立刻把用户消息显示出来并记入历史 ----
    st.session_state.messages.append({"role": "user", "content": prompt, "charts": []})
    render_user_msg(prompt)

    # ---- 3. 调后端 /chat 接口（真正干活的地方，约1分钟）----
    # data_path 优先级：📎 刚上传的 > 下拉框换的新文件 > 不传（沿用会话锁定的旧文件）
    # 注意：/files 返回纯文件名，但后端需要 "data/input/xxx" 完整路径，所以要拼接
    if pending_data_path:
        data_path = pending_data_path
    elif selected_file and (is_first_round or selected_file != st.session_state.active_file):
        data_path = f"data/input/{selected_file}"
    else:
        data_path = ""
    payload = {
        "thread_id": st.session_state.thread_id,
        "message": prompt,
        "data_path": data_path,
    }

    _head, _body = st.columns([1, 30])   # 左窄列放 🤖 头像，右宽列放正文（和历史的 AI 回复布局一致）
    with _head:
        st.markdown(f'<div class="ai-avatar">{svg_spark(18, "#fff")}</div>', unsafe_allow_html=True)
    with _body:
        with st.spinner("正在分析（规划→写代码→审核→执行→绘图→报告，约需1分钟）..."):
            try:
                resp = SESSION.post(f"{BACKEND_URL}/chat", json=payload, timeout=300)
                data = resp.json()
            except Exception as e:
                data = {"error": f"请求后端失败: {e}"}

        # ---- 4. 展示结果并记入历史 ----
        if "error" in data:
            st.error(data["error"])
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ {data['error']}", "charts": []}
            )
        else:
            # 🔑 记下后端本轮实际生效的数据文件，下一轮拿它判断"用户是否换了文件"
            st.session_state.active_file = os.path.basename(data.get("data_path", "")) or st.session_state.active_file
            st.markdown(data["report"])
            # 📥 报告下载按钮
            st.download_button(
                label="📥 下载报告 (Markdown)",
                data=data["report"],
                file_name="analysis_report.md",
                mime="text/markdown",
                key=f"dl_{len(st.session_state.messages)}",
            )
            # 🔑 立刻把图表字节下载下来存进历史（以后后端清理也不怕）
            chart_bytes = []
            for url in data.get("chart_urls", []):
                img = load_chart_bytes(url)
                if img:
                    chart_bytes.append(img)
                    st.image(img)
                else:
                    st.caption(f"（图表 {url} 加载失败）")
            if not chart_bytes:
                st.caption("（本次分析没有生成图表）")
            # 📋 执行详情折叠面板
            with st.expander("📋 执行详情"):
                st.write(f"代码审核通过: {'✅' if data.get('approved') else '❌'}")
                st.write(f"重试次数: {data.get('retry_count', 0)}")
                if data.get("error_message"):
                    st.write(f"最后错误信息: {data['error_message']}")
            st.session_state.messages.append(
                {"role": "assistant", "content": data["report"], "charts": chart_bytes}
            )