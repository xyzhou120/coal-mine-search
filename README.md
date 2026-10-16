# 煤矿文档检索系统

基于 [PageIndex](https://docs.pageindex.ai/) Local 模式的煤矿文档智能检索系统。

## 核心能力

- 通过 Excel 批量导入 300+ 家煤矿上报文件（PDF / Word / Excel）
- 自动 OCR 处理扫描件、手写体、复杂表格
- 按 **煤矿 / 清单类型 / 上报周期** 分级隔离存储和检索
- 基于 PageIndex 树形索引 + 私有化大模型推理，返回答案及页码引用
- 支持每日增量同步（幂等处理，已索引文件自动跳过）
- 全程数据不出内网

---

## 技术栈

| 组件 | 技术 |
|---|---|
| Web 框架 | FastAPI |
| 文档检索引擎 | PageIndex Local |
| 文档处理 | pymupdf + python-docx + openpyxl |
| OCR | PaddleOCR-VL（私有化 API） |
| 视觉理解 | Qwen3-VL-27B（私有化 API） |
| 任务队列 | Celery + Redis |
| 数据库 | PostgreSQL 15 |
| 部署 | Docker + docker-compose |

---

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
```

打开 `.env`，**必须填写以下配置**：

```env
# 数据库密码
POSTGRES_PASSWORD=your_strong_password

# PageIndex 索引模型（私有化 LLM）
PAGEINDEX_INDEX_API_BASE_URL=http://your-llm-server:8000/v1
PAGEINDEX_INDEX_API_KEY=your_key
PAGEINDEX_INDEX_MODEL_NAME=qwen3-27b

# PageIndex 检索模型（私有化 LLM）
PAGEINDEX_CHAT_API_BASE_URL=http://your-llm-server:8000/v1
PAGEINDEX_CHAT_API_KEY=your_key
PAGEINDEX_CHAT_MODEL_NAME=qwen3-27b

# PaddleOCR-VL（扫描件识别）
PADDLEOCR_API_BASE_URL=http://your-paddleocr-server:8000/v1
PADDLEOCR_API_KEY=your_key
PADDLEOCR_MODEL_NAME=paddleocr-vl

# Qwen Vision（复杂图表/手写体）
VISION_API_BASE_URL=http://your-vision-server:8000/v1
VISION_API_KEY=your_key
VISION_MODEL_NAME=qwen3-vl-27b
```

Embedding 和 Reranker 为预留配置，可暂时不填。

### 2. 启动服务

**生产环境：**
```bash
docker-compose up -d
```

**Windows 开发环境（热重载）：**
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### 3. 验证服务

访问 http://localhost/health 或 http://localhost/docs

健康检查返回示例：
```json
{
  "status": "ok",
  "version": "1.0.0",
  "models_configured": {
    "pageindex_index": true,
    "pageindex_chat": true,
    "vision_model": true,
    "paddleocr": true,
    "embedding": false,
    "reranker": false
  },
  "core_ready": true
}
```

---

## Excel 导入格式

Excel 文件需包含以下列（列名不区分大小写）：

| 列名 | 必填 | 说明 |
|---|---|---|
| mine_code | ✅ | 煤矿编码 |
| mine_name | ✅ | 煤矿名称 |
| file_name_id | ✅ | 清单类型 ID |
| file_name | ✅ | 清单类型名称 |
| attachment_id | ✅ | 附件唯一 ID |
| attachment_name | ✅ | 附件文件名 |
| attachment_link | ✅ | MinIO HTTPS 文件地址 |
| report_time | ❌ | 上报时间（如 2025-01） |
| update_rate | ❌ | 更新频率（0=由cycle决定；1/7/10/30/90/180/360=日报/周报/旬报/月报/季报/半年报/年报） |
| cycle | ❌ | 上报周期（日/周/旬/月/季/半年/年，update_rate=0时有效） |

---

## API 接口说明

### 文档导入

```
POST /api/import/upload              上传 Excel，创建导入任务
GET  /api/import/tasks               查看所有导入任务
GET  /api/import/tasks/{task_id}     查看任务进度
POST /api/import/tasks/{task_id}/retry  重试失败文件
GET  /api/import/documents           查看文档列表（支持按矿/状态过滤）
POST /api/import/documents/{id}/reindex  手动重新索引
```

### 文档检索

```
POST /api/search                     执行检索
GET  /api/search/mines               已索引煤矿列表
GET  /api/search/mines/{code}/list-types  指定煤矿清单类型
```

**检索请求示例：**
```json
POST /api/search
{
  "query": "2025年1月安全检查发现了哪些隐患？",
  "mine_code": "mine_001",
  "file_name_id": "list_003",
  "report_time": "2025-01"
}
```

**检索响应示例：**
```json
{
  "answer": "根据2025年1月安全检查报告，发现以下隐患：...",
  "citations": [
    {
      "attachment_id": "att_123",
      "attachment_name": "1月安全检查报告.pdf",
      "mine_name": "某某煤矿",
      "file_name": "安全检查清单",
      "page": 12
    }
  ],
  "doc_count": 45,
  "query": "2025年1月安全检查发现了哪些隐患？"
}
```

---

## 索引存储结构

```
/data/pageindex_index/
├── mine_001/          ← 每家煤矿独立索引目录
│   ├── att_abc.pdf.json
│   └── att_def.pdf.json
├── mine_002/
└── ...
```

---

## 生产部署建议

### 扩容 Celery Worker

存量 100 万文件导入期间，可横向扩展 worker：

```bash
docker-compose up -d --scale worker=3
```

同时调整 `.env` 中的 `CELERY_WORKER_CONCURRENCY`（推荐 5~10，根据 LLM 服务器负载）。

### 数据持久化

生产环境建议将 volume 绑定到大容量磁盘（索引文件较大）：

```yaml
# docker-compose.yml 中修改 pageindex_data volume
pageindex_data:
  driver: local
  driver_opts:
    type: none
    o: bind
    device: /data/coal-mine/pageindex_index
```

### 服务监控

```bash
# 查看 Worker 状态
docker-compose exec worker celery -A app.tasks.celery_app inspect active

# 查看任务队列积压
docker-compose exec worker celery -A app.tasks.celery_app inspect reserved

# 实时日志
docker-compose logs -f worker
```

---

## 目录结构

```
coal-mine-search/
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 所有模型和服务配置
│   ├── api/
│   │   ├── import_api.py     # 文档导入接口
│   │   └── search_api.py     # 检索接口
│   ├── models/
│   │   └── database.py       # SQLAlchemy 数据模型
│   ├── services/
│   │   ├── excel_parser.py   # Excel 解析
│   │   ├── file_downloader.py # MinIO 文件下载
│   │   ├── document_processor.py # OCR + 格式转换
│   │   ├── index_service.py  # PageIndex 索引构建
│   │   └── search_service.py # 检索服务
│   ├── tasks/
│   │   ├── celery_app.py     # Celery 配置
│   │   └── import_tasks.py   # 异步导入任务
│   └── utils/
│       ├── db.py             # 数据库连接管理
│       └── helpers.py        # 工具函数
├── nginx/
│   └── nginx.conf
├── docker-compose.yml        # 生产部署
├── docker-compose.dev.yml    # 开发环境
├── .env.example              # 环境变量模板
└── README.md
```
