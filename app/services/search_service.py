"""
检索服务
基于 PageIndex Local 推理检索，支持按煤矿/清单/周期分级检索
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import DocumentIndex
from app.services.index_service import get_pageindex_client
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 每批检索的最大 doc_id 数量（PageIndex Local 模式建议不超过 50）
BATCH_SIZE = 50


@dataclass
class Citation:
    """检索结果引用"""
    attachment_id: str
    attachment_name: str
    mine_code: str
    mine_name: str
    file_name: str
    file_name_id: str
    report_time: Optional[str]
    page: Optional[int]


@dataclass
class SearchResult:
    """检索结果"""
    answer: str
    citations: list[Citation] = field(default_factory=list)
    doc_count: int = 0
    query: str = ""
    error: Optional[str] = None


async def search(
    db: AsyncSession,
    query: str,
    mine_code: Optional[str] = None,
    file_name_id: Optional[str] = None,
    report_time: Optional[str] = None,
    cycle: Optional[str] = None,
) -> SearchResult:
    """
    执行文档检索

    Args:
        db: 数据库会话
        query: 检索问题
        mine_code: 煤矿编码（不传则全库检索）
        file_name_id: 清单类型ID（不传则不限清单）
        report_time: 上报时间（不传则不限时间）
        cycle: 上报周期枚举（不传则不限周期）

    Returns:
        SearchResult
    """
    if not settings.pageindex_chat_configured:
        return SearchResult(
            answer="",
            error="检索模型未配置，请在 .env 中配置 PAGEINDEX_CHAT_* 参数",
            query=query,
        )

    # 1. 从数据库查询满足条件的 doc_id 列表
    doc_records = await _query_documents(db, mine_code, file_name_id, report_time, cycle)

    if not doc_records:
        scope_desc = _build_scope_description(mine_code, file_name_id, report_time)
        return SearchResult(
            answer=f"在{scope_desc}中未找到已索引的文档，请确认文档已成功导入。",
            doc_count=0,
            query=query,
        )

    logger.info(
        f"检索范围: {len(doc_records)} 份文档 "
        f"[mine={mine_code}, list={file_name_id}, time={report_time}]"
    )

    # 2. 按煤矿分组（不同煤矿使用不同的 PageIndexClient）
    mine_groups: dict[str, list[DocumentIndex]] = {}
    for doc in doc_records:
        if doc.mine_code not in mine_groups:
            mine_groups[doc.mine_code] = []
        mine_groups[doc.mine_code].append(doc)

    # 3. 对每组执行检索，汇总结果
    all_answers = []
    all_citations = []

    for current_mine_code, docs in mine_groups.items():
        try:
            answer_text, citations = await asyncio.to_thread(
                _search_in_mine, current_mine_code, docs, query
            )
            if answer_text:
                all_answers.append(answer_text)
            all_citations.extend(citations)
        except Exception as e:
            logger.error(f"煤矿 {current_mine_code} 检索失败: {e}")

    if not all_answers:
        return SearchResult(
            answer="未能在相关文档中找到与问题匹配的内容。",
            citations=all_citations,
            doc_count=len(doc_records),
            query=query,
        )

    # 多煤矿结果合并（目前简单拼接，后续可加 reranker 排序）
    final_answer = "\n\n---\n\n".join(all_answers) if len(all_answers) > 1 else all_answers[0]

    return SearchResult(
        answer=final_answer,
        citations=all_citations,
        doc_count=len(doc_records),
        query=query,
    )


def _search_in_mine(
    mine_code: str,
    docs: list[DocumentIndex],
    query: str,
) -> tuple[str, list[Citation]]:
    """
    在指定煤矿的文档范围内执行检索（同步，在线程池中运行）
    分批处理大量 doc_id
    """
    client = get_pageindex_client(mine_code)

    # 只取已完成索引的文档
    completed_docs = [d for d in docs if d.status == "completed" and d.doc_id]
    if not completed_docs:
        return "", []

    doc_ids = [d.doc_id for d in completed_docs]
    doc_map = {d.doc_id: d for d in completed_docs}

    answers = []
    all_raw_citations = []

    # 分批检索
    for i in range(0, len(doc_ids), BATCH_SIZE):
        batch = doc_ids[i:i + BATCH_SIZE]
        try:
            answer = client.chat(
                query,
                doc_id=batch,
                citations=True,
            )
            if answer:
                answers.append(answer)
                # 解析引用
                raw_citations = client.get_citations(answer)
                all_raw_citations.extend(raw_citations)
        except Exception as e:
            logger.warning(f"批次 {i // BATCH_SIZE + 1} 检索失败: {e}")

    if not answers:
        return "", []

    # 合并批次答案
    merged_answer = "\n\n".join(answers) if len(answers) > 1 else answers[0]

    # 构建结构化引用列表
    citations = []
    seen = set()
    for raw_cite in all_raw_citations:
        cited_doc_id = raw_cite.get("doc_id", "")
        page = raw_cite.get("page")
        cite_key = f"{cited_doc_id}:{page}"
        if cite_key in seen:
            continue
        seen.add(cite_key)

        doc = doc_map.get(cited_doc_id)
        if doc:
            citations.append(Citation(
                attachment_id=doc.attachment_id,
                attachment_name=doc.attachment_name,
                mine_code=doc.mine_code,
                mine_name=doc.mine_name,
                file_name=doc.file_name,
                file_name_id=doc.file_name_id,
                report_time=doc.report_time,
                page=page,
            ))

    return merged_answer, citations


async def _query_documents(
    db: AsyncSession,
    mine_code: Optional[str],
    file_name_id: Optional[str],
    report_time: Optional[str],
    cycle: Optional[str],
) -> list[DocumentIndex]:
    """从数据库查询满足条件的已索引文档"""
    stmt = select(DocumentIndex).where(
        DocumentIndex.status == "completed",
        DocumentIndex.doc_id.isnot(None),
    )

    if mine_code:
        stmt = stmt.where(DocumentIndex.mine_code == mine_code)
    if file_name_id:
        stmt = stmt.where(DocumentIndex.file_name_id == file_name_id)
    if report_time:
        stmt = stmt.where(DocumentIndex.report_time == report_time)
    if cycle:
        stmt = stmt.where(DocumentIndex.cycle == cycle)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_available_mines(db: AsyncSession) -> list[dict]:
    """获取所有已有已索引文档的煤矿列表"""
    stmt = (
        select(
            DocumentIndex.mine_code,
            DocumentIndex.mine_name,
        )
        .where(DocumentIndex.status == "completed")
        .distinct()
        .order_by(DocumentIndex.mine_code)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()
    return [{"mine_code": r[0], "mine_name": r[1]} for r in rows]


async def get_mine_list_types(db: AsyncSession, mine_code: str) -> list[dict]:
    """获取指定煤矿的清单类型列表"""
    stmt = (
        select(
            DocumentIndex.file_name_id,
            DocumentIndex.file_name,
        )
        .where(
            DocumentIndex.mine_code == mine_code,
            DocumentIndex.status == "completed",
        )
        .distinct()
        .order_by(DocumentIndex.file_name_id)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()
    return [{"file_name_id": r[0], "file_name": r[1]} for r in rows]


def _build_scope_description(
    mine_code: Optional[str],
    file_name_id: Optional[str],
    report_time: Optional[str],
) -> str:
    parts = []
    if mine_code:
        parts.append(f"煤矿[{mine_code}]")
    if file_name_id:
        parts.append(f"清单[{file_name_id}]")
    if report_time:
        parts.append(f"周期[{report_time}]")
    return "、".join(parts) if parts else "全库"
