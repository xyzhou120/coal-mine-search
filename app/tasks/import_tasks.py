"""
文档导入异步任务
整体流程：Excel 解析 → 下载文件 → 预处理（OCR/转换）→ 建 PageIndex 索引 → 更新状态
"""
import logging
import os
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.database import DocumentIndex, ImportTask
from app.services.file_downloader import download_file, cleanup_temp_files, get_temp_dir
from app.services.document_processor import process_document
from app.services.index_service import submit_document_for_indexing
from app.utils.helpers import safe_filename

logger = logging.getLogger(__name__)
settings = get_settings()

# Celery Worker 使用同步 SQLAlchemy
sync_database_url = settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
sync_engine = create_engine(sync_database_url, pool_pre_ping=True, pool_size=5)
SyncSession = sessionmaker(bind=sync_engine)


def get_sync_db() -> Session:
    return SyncSession()


# ------------------------------------------------------------------
# 单文档处理任务
# ------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.tasks.import_tasks.process_single_document",
    max_retries=3,
    default_retry_delay=60,  # 初始重试延迟 60 秒
    queue="documents",
)
def process_single_document(self, attachment_id: str, import_task_id: str):
    """
    处理单份文档：下载 → 预处理 → 建索引 → 更新状态

    Args:
        attachment_id: 文档的 attachment_id
        import_task_id: 所属的导入任务 task_id（用于更新进度）
    """
    db = get_sync_db()
    try:
        # 查询文档记录
        doc: DocumentIndex = db.query(DocumentIndex).filter(
            DocumentIndex.attachment_id == attachment_id
        ).first()

        if not doc:
            logger.error(f"找不到文档记录: attachment_id={attachment_id}")
            return

        # 幂等检查：已完成的跳过
        if doc.status == "completed":
            logger.info(f"文档已完成索引，跳过: {attachment_id}")
            _update_import_task_progress(db, import_task_id, "skipped")
            return

        logger.info(f"开始处理文档: {attachment_id} ({doc.attachment_name})")

        # --- 步骤1：下载文件 ---
        _update_doc_status(db, doc, "downloading")
        try:
            local_path = download_file(
                url=doc.attachment_link,
                mine_code=doc.mine_code,
                attachment_id=doc.attachment_id,
                attachment_name=doc.attachment_name,
            )
        except Exception as e:
            raise self.retry(
                exc=e,
                countdown=60 * (2 ** self.request.retries),  # 60/120/240 秒
                max_retries=3,
            )

        # --- 步骤2：文档预处理（OCR/格式转换）---
        _update_doc_status(db, doc, "processing")
        temp_dir = get_temp_dir(doc.mine_code, doc.attachment_id)
        try:
            processed_path = process_document(local_path, temp_dir)
        except Exception as e:
            logger.error(f"文档预处理失败: {attachment_id}: {e}")
            _update_doc_status(db, doc, "failed", str(e))
            _update_import_task_progress(db, import_task_id, "failed")
            return

        # --- 步骤3：PageIndex 建索引 ---
        _update_doc_status(db, doc, "indexing")
        try:
            # 使用 attachment_id_attachment_name 作为文档名确保唯一性
            doc_name = _build_doc_name(doc.attachment_id, doc.attachment_name)
            # 重命名为唯一名称后提交
            named_path = os.path.join(temp_dir, doc_name)
            if not os.path.exists(named_path):
                import shutil
                shutil.copy2(processed_path, named_path)

            doc_id = submit_document_for_indexing(
                processed_pdf_path=named_path,
                mine_code=doc.mine_code,
                attachment_id=doc.attachment_id,
                attachment_name=doc.attachment_name,
            )
        except Exception as e:
            logger.error(f"PageIndex 建索引失败: {attachment_id}: {e}")
            _update_doc_status(db, doc, "failed", str(e))
            _update_import_task_progress(db, import_task_id, "failed")
            return

        # --- 步骤4：更新状态为完成 ---
        try:
            # 获取页数
            import fitz
            pdf_doc = fitz.open(processed_path)
            page_count = len(pdf_doc)
            pdf_doc.close()
        except Exception:
            page_count = None

        doc.status = "completed"
        doc.doc_id = doc_id
        doc.page_count = page_count
        doc.indexed_at = datetime.now(timezone.utc)
        doc.error_msg = None
        db.commit()

        # 清理临时文件
        cleanup_temp_files(doc.mine_code, doc.attachment_id)

        # 更新导入任务进度
        _update_import_task_progress(db, import_task_id, "completed")

        logger.info(f"文档处理完成: {attachment_id}, doc_id={doc_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"处理文档异常: {attachment_id}: {e}", exc_info=True)
        # 更新数据库中的重试次数和错误信息
        try:
            doc = db.query(DocumentIndex).filter(
                DocumentIndex.attachment_id == attachment_id
            ).first()
            if doc:
                doc.retry_count = (doc.retry_count or 0) + 1
                doc.error_msg = str(e)
                db.commit()
        except Exception:
            db.rollback()

        _update_import_task_progress(db, import_task_id, "failed")

        # 如果还有重试次数，重新抛出让 Celery 重试
        raise self.retry(
            exc=e,
            countdown=60 * (2 ** self.request.retries),
            max_retries=3,
        )
    finally:
        db.close()


# ------------------------------------------------------------------
# Excel 批量处理任务
# ------------------------------------------------------------------

@shared_task(
    name="app.tasks.import_tasks.process_excel_batch",
    queue="celery",
)
def process_excel_batch(import_task_id: str):
    """
    Excel 批量导入任务：读取所有 pending 文档，批量触发单文档处理任务

    Args:
        import_task_id: ImportTask 的 task_id
    """
    db = get_sync_db()
    try:
        # 查询该任务下所有 pending 文档
        import_task = db.query(ImportTask).filter(
            ImportTask.task_id == import_task_id
        ).first()

        if not import_task:
            logger.error(f"导入任务不存在: {import_task_id}")
            return

        # 更新任务状态
        import_task.status = "processing"
        db.commit()

        # 查找所有需要处理的文档（pending 或 failed 且可重试的）
        pending_docs = db.query(DocumentIndex).filter(
            DocumentIndex.status.in_(["pending", "failed"]),
        ).all()

        # 过滤出与本次任务相关的文档（通过 import_task_id 关联）
        # 注意：这里简化处理，实际关联在 API 层通过创建时打标来实现
        # 重新查询本批次 attachment_id
        from sqlalchemy import text
        batch_docs = db.execute(
            text(
                "SELECT attachment_id FROM document_index "
                "WHERE status IN ('pending', 'failed') AND retry_count < 3 "
                "ORDER BY created_at"
            )
        ).fetchall()

        doc_ids = [row[0] for row in batch_docs]

        logger.info(f"批量导入任务 {import_task_id}: 共 {len(doc_ids)} 份文档待处理")

        # 逐个触发异步任务（Celery 会根据 worker_concurrency 控制并发）
        for attachment_id in doc_ids:
            process_single_document.delay(attachment_id, import_task_id)

        logger.info(f"已触发 {len(doc_ids)} 个处理任务")

    except Exception as e:
        logger.error(f"批量任务失败: {import_task_id}: {e}", exc_info=True)
        try:
            import_task = db.query(ImportTask).filter(
                ImportTask.task_id == import_task_id
            ).first()
            if import_task:
                import_task.status = "failed"
                import_task.error_msg = str(e)
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _update_doc_status(db: Session, doc: DocumentIndex, status: str, error_msg: str = None):
    """更新文档状态"""
    try:
        doc.status = status
        if error_msg:
            doc.error_msg = error_msg
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"更新文档状态失败: {e}")


def _update_import_task_progress(db: Session, import_task_id: str, result: str):
    """
    更新导入任务的进度计数
    result: "completed" | "failed" | "skipped"
    """
    try:
        task = db.query(ImportTask).filter(
            ImportTask.task_id == import_task_id
        ).first()
        if not task:
            return

        if result == "completed":
            task.completed_count = (task.completed_count or 0) + 1
        elif result == "failed":
            task.failed_count = (task.failed_count or 0) + 1
        elif result == "skipped":
            task.skipped_count = (task.skipped_count or 0) + 1

        # 检查是否全部完成
        finished = (task.completed_count or 0) + (task.failed_count or 0) + (task.skipped_count or 0)
        if finished >= (task.total_count or 0) and task.total_count > 0:
            if (task.failed_count or 0) > 0:
                task.status = "partial"
            else:
                task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"更新任务进度失败: {e}")


def _build_doc_name(attachment_id: str, attachment_name: str) -> str:
    """构建 PageIndex 文档唯一名称"""
    import os
    ext = os.path.splitext(attachment_name)[1] or ".pdf"
    if not ext.lower().endswith(".pdf"):
        ext = ".pdf"  # 预处理后统一是 PDF
    name = f"{attachment_id}{ext}"
    return safe_filename(name)
