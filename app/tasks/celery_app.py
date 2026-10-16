"""
Celery 应用配置
"""
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "coal_mine_search",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["tasks.import_tasks"],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # Worker 配置
    worker_concurrency=settings.celery_worker_concurrency,
    worker_prefetch_multiplier=1,  # 一次只预取1个任务，避免大任务积压
    # 任务超时（单个文档处理最长 30 分钟，复杂 OCR 可能很慢）
    task_soft_time_limit=1800,
    task_time_limit=2100,
    # 重试配置
    task_acks_late=True,  # 任务完成后再确认，避免崩溃导致任务丢失
    task_reject_on_worker_lost=True,
    # 结果过期时间（7天）
    result_expires=604800,
    # 任务路由
    task_routes={
        "tasks.import_tasks.process_single_document": {"queue": "documents"},
        "tasks.import_tasks.process_excel_batch": {"queue": "celery"},
    },
)
