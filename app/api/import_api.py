"""
文档导入 API
提供 Excel 上传、任务进度查询、失败重试等接口
"""
import logging
import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import get_settings
from app.models.database import DocumentIndex, ImportTask, CoalMine, ListType
from app.services.excel_parser import parse_excel
from app.tasks.celery_app import celery_app
from app.utils.db import get_db
from app.utils.helpers import generate_task_id, ensure_dir

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


# ------------------------------------------------------------------
# 响应模型
# ------------------------------------------------------------------

class ImportTaskResponse(BaseModel):
    task_id: str
    status: str
    file_name: str
    total_count: int
    pending_count: int
    processing_count: int
    completed_count: int
    failed_count: int
    skipped_count: int
    created_at: str
    completed_at: Optional[str] = None
    error_msg: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    attachment_id: str
    attachment_name: str
    mine_code: str
    mine_name: str
    file_name_id: str
    file_name: str
    report_time: Optional[str]
    update_rate: Optional[int]
    cycle: Optional[str]
    frequency_label: Optional[str]
    file_type: Optional[str]
    status: str
    doc_id: Optional[str]
    page_count: Optional[int]
    error_msg: Optional[str]
    retry_count: int
    created_at: str
    indexed_at: Optional[str]

    class Config:
        from_attributes = True


# ------------------------------------------------------------------
# 上传 Excel 并创建导入任务
# ------------------------------------------------------------------

@router.post("/upload", summary="上传 Excel 文件，创建导入任务")
async def upload_excel(
    file: UploadFile = File(..., description="Excel 文件 (.xlsx/.xls)"),
    db: AsyncSession = Depends(get_db),
):
    """
    上传 Excel 文件，解析文档列表，创建异步导入任务。

    Excel 必须包含以下列：
    mine_code, mine_name, report_time, update_rate, cycle,
    file_name_id, file_name, attachment_id, attachment_name, attachment_link
    """
    # 检查文件格式
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 格式的 Excel 文件")

    # 保存上传文件
    ensure_dir(settings.upload_dir)
    task_id = generate_task_id()
    save_path = os.path.join(settings.upload_dir, f"{task_id}_{file.filename}")

    try:
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    # 解析 Excel
    parse_result = parse_excel(save_path)
    if not parse_result.success:
        os.remove(save_path)
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {parse_result.error}")

    if not parse_result.documents:
        raise HTTPException(status_code=400, detail="Excel 中没有有效的文档记录")

    # 写入数据库
    new_count = 0
    skip_count = parse_result.invalid_count  # 格式无效的行

    for doc_meta in parse_result.documents:
        # 幂等检查：attachment_id 已存在且 completed 则跳过
        existing = await db.execute(
            select(DocumentIndex).where(
                DocumentIndex.attachment_id == doc_meta.attachment_id
            )
        )
        existing_doc = existing.scalar_one_or_none()

        if existing_doc:
            if existing_doc.status == "completed":
                skip_count += 1
                continue
            else:
                # 已存在但未完成（failed/pending），重置为 pending 重新处理
                existing_doc.status = "pending"
                existing_doc.error_msg = None
                existing_doc.attachment_link = doc_meta.attachment_link  # 更新链接
        else:
            # 新文档
            new_doc = DocumentIndex(
                attachment_id=doc_meta.attachment_id,
                attachment_name=doc_meta.attachment_name,
                attachment_link=doc_meta.attachment_link,
                mine_code=doc_meta.mine_code,
                mine_name=doc_meta.mine_name,
                file_name_id=doc_meta.file_name_id,
                file_name=doc_meta.file_name,
                report_time=doc_meta.report_time,
                update_rate=doc_meta.update_rate,
                cycle=doc_meta.cycle,
                frequency_label=doc_meta.frequency_label,
                file_type=doc_meta.file_type,
                status="pending",
            )
            db.add(new_doc)
            new_count += 1

        # 同步煤矿主表
        await _upsert_coal_mine(db, doc_meta.mine_code, doc_meta.mine_name)
        # 同步清单类型表
        await _upsert_list_type(db, doc_meta.file_name_id, doc_meta.file_name)

    await db.flush()

    # 创建导入任务记录
    import_task = ImportTask(
        task_id=task_id,
        file_name=file.filename,
        file_path=save_path,
        total_count=parse_result.valid_count,
        pending_count=new_count,
        processing_count=0,
        completed_count=0,
        failed_count=0,
        skipped_count=skip_count,
        status="created",
    )
    db.add(import_task)
    await db.commit()

    # 触发异步批量处理任务
    from app.tasks.import_tasks import process_excel_batch
    celery_task = process_excel_batch.delay(task_id)

    # 更新 Celery task ID
    await db.execute(
        update(ImportTask)
        .where(ImportTask.task_id == task_id)
        .values(celery_task_id=celery_task.id, status="processing")
    )
    await db.commit()

    return {
        "task_id": task_id,
        "message": "导入任务已创建，正在后台处理",
        "total_rows": parse_result.total_rows,
        "valid_count": parse_result.valid_count,
        "new_count": new_count,
        "skip_count": skip_count,
        "invalid_rows": parse_result.skipped_rows[:10],  # 只返回前10条无效行
    }


# ------------------------------------------------------------------
# 查询导入任务
# ------------------------------------------------------------------

@router.get("/tasks", summary="查询所有导入任务列表")
async def list_import_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    stmt = select(ImportTask).order_by(ImportTask.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    count_stmt = select(func.count(ImportTask.id))
    total = (await db.execute(count_stmt)).scalar()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_task_to_dict(t) for t in tasks],
    }


@router.get("/tasks/{task_id}", summary="查询单个导入任务进度")
async def get_import_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ImportTask).where(ImportTask.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    # 实时从 document_index 统计最新进度
    stats = await _get_task_stats(db)
    return {**_task_to_dict(task), "realtime_stats": stats}


@router.post("/tasks/{task_id}/retry", summary="重试任务中失败的文件")
async def retry_failed_documents(task_id: str, db: AsyncSession = Depends(get_db)):
    """将任务中所有 failed 状态的文档重置为 pending，并重新触发处理"""
    result = await db.execute(
        select(ImportTask).where(ImportTask.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    # 重置 failed 文档
    await db.execute(
        update(DocumentIndex)
        .where(
            DocumentIndex.status == "failed",
            DocumentIndex.retry_count < 3,
        )
        .values(status="pending", error_msg=None)
    )
    await db.commit()

    # 重新触发批量任务
    from app.tasks.import_tasks import process_excel_batch
    process_excel_batch.delay(task_id)

    return {"message": "已重新触发失败文件的处理"}


# ------------------------------------------------------------------
# 查询文档列表
# ------------------------------------------------------------------

@router.get("/documents", summary="查询已导入文档列表")
async def list_documents(
    mine_code: Optional[str] = Query(None),
    file_name_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending/processing/completed/failed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DocumentIndex)
    if mine_code:
        stmt = stmt.where(DocumentIndex.mine_code == mine_code)
    if file_name_id:
        stmt = stmt.where(DocumentIndex.file_name_id == file_name_id)
    if status:
        stmt = stmt.where(DocumentIndex.status == status)

    count_stmt = select(func.count(DocumentIndex.id))
    if mine_code:
        count_stmt = count_stmt.where(DocumentIndex.mine_code == mine_code)
    if file_name_id:
        count_stmt = count_stmt.where(DocumentIndex.file_name_id == file_name_id)
    if status:
        count_stmt = count_stmt.where(DocumentIndex.status == status)

    total = (await db.execute(count_stmt)).scalar()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(DocumentIndex.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_doc_to_dict(d) for d in docs],
    }


@router.post("/documents/{attachment_id}/reindex", summary="手动重新索引单个文件")
async def reindex_document(attachment_id: str, db: AsyncSession = Depends(get_db)):
    """将单个文档重置为 pending 状态，触发重新索引"""
    result = await db.execute(
        select(DocumentIndex).where(DocumentIndex.attachment_id == attachment_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {attachment_id}")

    doc.status = "pending"
    doc.error_msg = None
    doc.doc_id = None
    doc.retry_count = 0
    await db.commit()

    from app.tasks.import_tasks import process_single_document
    process_single_document.delay(attachment_id, "manual_reindex")

    return {"message": f"已触发重新索引: {attachment_id}"}


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

async def _upsert_coal_mine(db: AsyncSession, mine_code: str, mine_name: str):
    """插入或更新煤矿记录"""
    result = await db.execute(
        select(CoalMine).where(CoalMine.mine_code == mine_code)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        db.add(CoalMine(mine_code=mine_code, mine_name=mine_name))


async def _upsert_list_type(db: AsyncSession, file_name_id: str, file_name: str):
    """插入或更新清单类型记录"""
    result = await db.execute(
        select(ListType).where(ListType.file_name_id == file_name_id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        db.add(ListType(file_name_id=file_name_id, file_name=file_name))


async def _get_task_stats(db: AsyncSession) -> dict:
    """统计全局文档状态"""
    stmt = select(
        DocumentIndex.status,
        func.count(DocumentIndex.id).label("count")
    ).group_by(DocumentIndex.status)
    result = await db.execute(stmt)
    rows = result.fetchall()
    return {r[0]: r[1] for r in rows}


def _task_to_dict(task: ImportTask) -> dict:
    return {
        "task_id": task.task_id,
        "status": task.status,
        "file_name": task.file_name,
        "total_count": task.total_count,
        "pending_count": task.pending_count,
        "processing_count": task.processing_count,
        "completed_count": task.completed_count,
        "failed_count": task.failed_count,
        "skipped_count": task.skipped_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error_msg": task.error_msg,
    }


def _doc_to_dict(doc: DocumentIndex) -> dict:
    return {
        "attachment_id": doc.attachment_id,
        "attachment_name": doc.attachment_name,
        "mine_code": doc.mine_code,
        "mine_name": doc.mine_name,
        "file_name_id": doc.file_name_id,
        "file_name": doc.file_name,
        "report_time": doc.report_time,
        "update_rate": doc.update_rate,
        "cycle": doc.cycle,
        "frequency_label": doc.frequency_label,
        "file_type": doc.file_type,
        "status": doc.status,
        "doc_id": doc.doc_id,
        "page_count": doc.page_count,
        "error_msg": doc.error_msg,
        "retry_count": doc.retry_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
    }
