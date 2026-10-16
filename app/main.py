"""
煤矿文档检索系统 - FastAPI 主入口
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.utils.db import init_db
from app.api.import_api import router as import_router
from app.api.search_api import router as search_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库"""
    logger.info("正在初始化数据库...")
    await init_db()
    logger.info("数据库初始化完成")

    # 确保必要目录存在
    import os
    for path in [settings.pageindex_storage_root, settings.temp_file_dir, settings.upload_dir]:
        os.makedirs(path, exist_ok=True)
    logger.info("存储目录检查完成")

    yield

    logger.info("应用关闭")


app = FastAPI(
    title="煤矿文档检索系统",
    description="""
基于 PageIndex 的煤矿文档智能检索系统。

## 功能
- **文档导入**: 通过 Excel 批量导入煤矿上报文件，支持 PDF/Word/Excel 格式
- **智能检索**: 按煤矿/清单类型/上报周期分级检索，支持全文语义搜索
- **任务管理**: 查看导入进度，重试失败文件

## 说明
- 所有模型（视觉/OCR/Chat）均使用私有化部署，数据不出内网
- 索引按煤矿隔离存储，检索时只加载对应煤矿索引
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(import_router, prefix="/api/import", tags=["文档导入"])
app.include_router(search_router, prefix="/api/search", tags=["文档检索"])


@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查接口"""
    config_status = {
        "pageindex_index": settings.pageindex_index_configured,
        "pageindex_chat": settings.pageindex_chat_configured,
        "vision_model": settings.vision_configured,
        "paddleocr": settings.paddleocr_configured,
        "embedding": settings.embedding_configured,
        "reranker": settings.reranker_configured,
    }
    all_core_configured = (
        settings.pageindex_index_configured and settings.pageindex_chat_configured
    )
    return JSONResponse(
        content={
            "status": "ok",
            "version": "1.0.0",
            "models_configured": config_status,
            "core_ready": all_core_configured,
            "message": (
                "核心模型已配置，系统就绪"
                if all_core_configured
                else "⚠️ 请在 .env 中配置 PAGEINDEX_INDEX_* 和 PAGEINDEX_CHAT_* 模型参数"
            ),
        }
    )


@app.get("/", tags=["系统"])
async def root():
    return {"message": "煤矿文档检索系统", "docs": "/docs", "health": "/health"}
