# ============================================================
# 数据分析 Agent 镜像：backend(8001) 和 frontend(8501) 共用
# 基础镜像 python:3.11-slim（Debian），CPU 推理足够
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    MATPLOTLIB_FONT=WenQuanYi

WORKDIR /app

# 系统依赖：文泉驿中文字体（Linux 没有 SimHei，图表中文防乱码）+ libgomp（torch/numpy 运行库）
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-wqy-zenhei \
        libgomp1 \
        fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# 先装 CPU 版 torch（官方默认 wheel 带 CUDA，体积 6GB+；CPU 版 ~800MB 且本项目用不到 GPU）
# -i 清华镜像：国内直连 PyPI 只有 ~100KB/s，镜像源快 10 倍以上
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 再装项目依赖（requirements 里的 sentence-transformers 检测到 torch 已装，不会再拉 CUDA 版）
# PIP_INDEX_URL 可被构建参数覆盖：compose 默认传清华镜像（国内快）；海外设备删掉 compose 里的 args 段即走官方源
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

# 拷贝项目代码（.dockerignore 已排除 .env / venv / 数据库 / data）
COPY . .

EXPOSE 8001 8501
# 启动命令由 docker-compose.yml 按服务指定（backend=uvicorn, frontend=streamlit）
