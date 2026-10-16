# ============================================================
# 煤矿文档检索系统 - 应用镜像
# 同时用于 FastAPI 服务 和 Celery Worker
# ============================================================
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 避免交互式安装
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 切换为阿里云 Debian 镜像源（python:3.11-slim 基于 Debian bookworm）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list 2>/dev/null || true

# 安装系统依赖
# - libgl1, libglib2.0-0: pymupdf 依赖
# - fonts-noto-cjk: 中文字体支持（PDF 中文渲染）
# - curl: 健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    fonts-noto-cjk \
    curl \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip 并配置国内镜像
RUN pip install --no-cache-dir --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/

# 复制依赖文件并安装（单独一层，利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /data/pageindex_index /data/temp /data/uploads

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app /data

USER appuser

# 健康检查（FastAPI 服务）
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动命令（FastAPI 服务，可被 docker-compose 覆盖）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
