"""
全局配置模块
所有模型和服务配置从环境变量读取，用户通过 .env 文件配置
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # 数据库配置
    # ------------------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "coal_mine_search"
    postgres_user: str = "coal_mine"
    postgres_password: str = "changeme"
    database_url: str = (
        "postgresql+asyncpg://coal_mine:changeme@postgres:5432/coal_mine_search"
    )

    # ------------------------------------------------------------------
    # Redis / Celery 配置
    # ------------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    celery_worker_concurrency: int = 5

    # ------------------------------------------------------------------
    # MinIO 文件下载配置
    # ------------------------------------------------------------------
    # 内网自签证书时设为 False
    minio_verify_ssl: bool = False
    minio_download_timeout: int = 120
    minio_download_max_retries: int = 3

    # ------------------------------------------------------------------
    # 文件存储路径
    # ------------------------------------------------------------------
    pageindex_storage_root: str = "/data/pageindex_index"
    temp_file_dir: str = "/data/temp"
    upload_dir: str = "/data/uploads"

    # ------------------------------------------------------------------
    # PageIndex Local 模式 - 索引构建模型（Index 侧）
    # 用于将文档解析为树形索引结构
    # 填写：你的私有化 LLM 服务地址和模型名称
    # ------------------------------------------------------------------
    pageindex_index_api_base_url: str = ""
    pageindex_index_api_key: str = ""
    pageindex_index_model_name: str = ""  # 如：qwen3-27b

    # ------------------------------------------------------------------
    # PageIndex Local 模式 - 检索推理模型（Chat 侧）
    # 用于在树形索引上推理检索，回答用户问题
    # 填写：你的私有化 LLM 服务地址和模型名称
    # ------------------------------------------------------------------
    pageindex_chat_api_base_url: str = ""
    pageindex_chat_api_key: str = ""
    pageindex_chat_model_name: str = ""  # 如：qwen3-27b

    # ------------------------------------------------------------------
    # 视觉模型配置（Qwen3-VL-27B）
    # 用于处理扫描件、复杂图表、手写体 PDF 页面
    # ------------------------------------------------------------------
    vision_api_base_url: str = ""
    vision_api_key: str = ""
    vision_model_name: str = ""  # 如：qwen3-vl-27b
    vision_request_timeout: int = 120

    # ------------------------------------------------------------------
    # PaddleOCR-VL 模型配置
    # 优先用于纯文字识别（比视觉模型更快更准）
    # ------------------------------------------------------------------
    paddleocr_api_base_url: str = ""
    paddleocr_api_key: str = ""
    paddleocr_model_name: str = ""  # 如：paddleocr-vl
    paddleocr_request_timeout: int = 60

    # ------------------------------------------------------------------
    # Embedding 模型配置（预留）
    # 用于后续语义增强检索
    # ------------------------------------------------------------------
    embedding_api_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model_name: str = ""  # 如：qwen-text-embedding
    embedding_dimensions: int = 1024

    # ------------------------------------------------------------------
    # Reranker 模型配置（预留）
    # 用于检索结果重排序，提升精度
    # ------------------------------------------------------------------
    reranker_api_base_url: str = ""
    reranker_api_key: str = ""
    reranker_model_name: str = ""  # 如：qwen-reranker
    reranker_request_timeout: int = 30

    # ------------------------------------------------------------------
    # PDF 处理配置
    # ------------------------------------------------------------------
    # PDF 页面文字字符数低于此阈值则视为扫描件，触发 OCR
    pdf_text_threshold: int = 50

    # ------------------------------------------------------------------
    # 应用配置
    # ------------------------------------------------------------------
    app_env: str = "production"
    app_debug: bool = False
    app_api_key: Optional[str] = None
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def pageindex_index_configured(self) -> bool:
        """PageIndex 索引模型是否已配置"""
        return bool(
            self.pageindex_index_api_base_url and self.pageindex_index_model_name
        )

    @property
    def pageindex_chat_configured(self) -> bool:
        """PageIndex 检索模型是否已配置"""
        return bool(
            self.pageindex_chat_api_base_url and self.pageindex_chat_model_name
        )

    @property
    def vision_configured(self) -> bool:
        """视觉模型是否已配置"""
        return bool(self.vision_api_base_url and self.vision_model_name)

    @property
    def paddleocr_configured(self) -> bool:
        """PaddleOCR 是否已配置"""
        return bool(self.paddleocr_api_base_url and self.paddleocr_model_name)

    @property
    def embedding_configured(self) -> bool:
        """Embedding 模型是否已配置"""
        return bool(self.embedding_api_base_url and self.embedding_model_name)

    @property
    def reranker_configured(self) -> bool:
        """Reranker 模型是否已配置"""
        return bool(self.reranker_api_base_url and self.reranker_model_name)

    def get_pageindex_storage_path(self, mine_code: str) -> str:
        """获取指定煤矿的 PageIndex 索引存储路径"""
        return f"{self.pageindex_storage_root}/{mine_code}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
