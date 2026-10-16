"""
检索 API
提供按煤矿/清单/周期分级的全文检索接口
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_service import search, get_available_mines, get_mine_list_types
from app.utils.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------
# 请求/响应模型
# ------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    mine_code: Optional[str] = None
    file_name_id: Optional[str] = None
    report_time: Optional[str] = None
    cycle: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "query": "2025年1月安全检查中发现了哪些问题？",
                "mine_code": "mine_001",
                "file_name_id": "list_003",
                "report_time": "2025-01",
                "cycle": None,
            }
        }


class CitationItem(BaseModel):
    attachment_id: str
    attachment_name: str
    mine_code: str
    mine_name: str
    file_name: str
    file_name_id: str
    report_time: Optional[str]
    page: Optional[int]


class SearchResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    doc_count: int
    query: str
    error: Optional[str] = None


# ------------------------------------------------------------------
# 检索接口
# ------------------------------------------------------------------

@router.post("", response_model=SearchResponse, summary="文档检索")
async def search_documents(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    在已索引的文档中执行全文检索。

    **检索范围说明：**
    - 不传 mine_code：全库检索（所有煤矿）
    - 只传 mine_code：检索该煤矿下所有文档
    - mine_code + file_name_id：检索该煤矿指定清单类型的文档
    - mine_code + file_name_id + report_time：最精确，检索特定煤矿+清单+时间的文档

    **返回说明：**
    - answer：基于 PageIndex 推理检索的答案
    - citations：答案的引用来源（文件名 + 页码）
    - doc_count：本次检索涉及的文档数量
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="检索问题不能为空")

    result = await search(
        db=db,
        query=request.query,
        mine_code=request.mine_code,
        file_name_id=request.file_name_id,
        report_time=request.report_time,
        cycle=request.cycle,
    )

    return SearchResponse(
        answer=result.answer,
        citations=[
            CitationItem(
                attachment_id=c.attachment_id,
                attachment_name=c.attachment_name,
                mine_code=c.mine_code,
                mine_name=c.mine_name,
                file_name=c.file_name,
                file_name_id=c.file_name_id,
                report_time=c.report_time,
                page=c.page,
            )
            for c in result.citations
        ],
        doc_count=result.doc_count,
        query=result.query,
        error=result.error,
    )


# ------------------------------------------------------------------
# 元数据查询接口
# ------------------------------------------------------------------

@router.get("/mines", summary="获取已有索引文档的煤矿列表")
async def list_mines(db: AsyncSession = Depends(get_db)):
    """返回所有已成功建立索引的煤矿列表"""
    mines = await get_available_mines(db)
    return {"total": len(mines), "items": mines}


@router.get("/mines/{mine_code}/list-types", summary="获取指定煤矿的清单类型列表")
async def list_mine_list_types(mine_code: str, db: AsyncSession = Depends(get_db)):
    """返回指定煤矿下已索引文档涵盖的清单类型"""
    list_types = await get_mine_list_types(db, mine_code)
    if not list_types:
        raise HTTPException(
            status_code=404,
            detail=f"煤矿 {mine_code} 暂无已索引文档，请确认文档已导入",
        )
    return {"mine_code": mine_code, "total": len(list_types), "items": list_types}
