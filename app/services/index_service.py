"""
PageIndex 索引构建服务
使用 PageIndex Local 模式将预处理后的 PDF 建立树形索引
索引文件按煤矿分目录隔离存储：{PAGEINDEX_STORAGE_ROOT}/{mine_code}/
"""
import logging
import os
import time
from typing import Optional

from pageindex import PageIndexClient

from app.config import get_settings
from app.utils.helpers import ensure_dir

logger = logging.getLogger(__name__)
settings = get_settings()

# 缓存 PageIndexClient 实例，按 mine_code 缓存（同步使用，Celery Worker 中每个进程独立）
_client_cache: dict[str, PageIndexClient] = {}


def get_pageindex_client(mine_code: str) -> PageIndexClient:
    """
    获取指定煤矿的 PageIndexClient 实例
    按煤矿隔离索引存储目录
    """
    if mine_code in _client_cache:
        return _client_cache[mine_code]

    if not settings.pageindex_index_configured:
        raise RuntimeError(
            "PageIndex 索引模型未配置，请在 .env 中设置 "
            "PAGEINDEX_INDEX_API_BASE_URL 和 PAGEINDEX_INDEX_MODEL_NAME"
        )
    if not settings.pageindex_chat_configured:
        raise RuntimeError(
            "PageIndex 检索模型未配置，请在 .env 中设置 "
            "PAGEINDEX_CHAT_API_BASE_URL 和 PAGEINDEX_CHAT_MODEL_NAME"
        )

    storage_path = settings.get_pageindex_storage_path(mine_code)
    ensure_dir(storage_path)

    client = PageIndexClient(
        index={
            "model": f"openai/{settings.pageindex_index_model_name}",
            "storage_path": storage_path,
            "backend": {
                "api_key": settings.pageindex_index_api_key or "none",
                "base_url": settings.pageindex_index_api_base_url,
            },
        },
        chat={
            "model": f"openai/{settings.pageindex_chat_model_name}",
            "backend": {
                "api_key": settings.pageindex_chat_api_key or "none",
                "base_url": settings.pageindex_chat_api_base_url,
            },
        },
    )

    _client_cache[mine_code] = client
    logger.info(f"创建 PageIndexClient: mine_code={mine_code}, storage={storage_path}")
    return client


def submit_document_for_indexing(
    processed_pdf_path: str,
    mine_code: str,
    attachment_id: str,
    attachment_name: str,
) -> str:
    """
    将预处理后的 PDF 提交 PageIndex 建立树形索引

    Args:
        processed_pdf_path: 预处理后的 PDF 文件路径
        mine_code: 煤矿编码（决定索引存储目录）
        attachment_id: 附件ID（用于幂等检查）
        attachment_name: 附件名称（作为 PageIndex 文档名）

    Returns:
        PageIndex doc_id

    Raises:
        RuntimeError: 索引失败时抛出
    """
    client = get_pageindex_client(mine_code)

    # 幂等检查：通过 attachment_name 查找已有 doc_id
    existing_doc_id = _find_existing_doc(client, attachment_name, attachment_id)
    if existing_doc_id:
        logger.info(f"文档已有索引，复用 doc_id: {existing_doc_id}")
        return existing_doc_id

    logger.info(f"提交 PageIndex 索引: {attachment_name} ({processed_pdf_path})")

    # 提交文档，wait=True 阻塞直到索引完成
    try:
        result = client.submit_document(
            processed_pdf_path,
            wait=True,
        )
        doc_id = result["doc_id"]
        logger.info(f"索引完成: doc_id={doc_id}, name={attachment_name}")
        return doc_id
    except Exception as e:
        raise RuntimeError(f"PageIndex 索引失败: {e}") from e


def _find_existing_doc(client: PageIndexClient, attachment_name: str, attachment_id: str) -> Optional[str]:
    """
    在 PageIndex 中查找已有文档
    通过文档名称匹配（attachment_id 作为名称前缀确保唯一性）
    """
    try:
        # 使用 attachment_id_attachment_name 作为文档名，确保唯一
        doc_name = f"{attachment_id}_{attachment_name}"
        # 截断过长的文件名
        if len(doc_name) > 200:
            ext = os.path.splitext(attachment_name)[1]
            doc_name = f"{attachment_id}{ext}"

        doc_id = client.get_document_id(doc_name)
        return doc_id
    except Exception:
        return None


def get_document_info(mine_code: str, doc_id: str) -> Optional[dict]:
    """获取 PageIndex 文档信息"""
    try:
        client = get_pageindex_client(mine_code)
        return client.get_document(doc_id)
    except Exception as e:
        logger.error(f"获取文档信息失败: {e}")
        return None


def delete_document_index(mine_code: str, doc_id: str) -> bool:
    """删除文档索引"""
    try:
        client = get_pageindex_client(mine_code)
        client.delete_document(doc_id)
        logger.info(f"已删除索引: mine_code={mine_code}, doc_id={doc_id}")
        return True
    except Exception as e:
        logger.error(f"删除索引失败: {e}")
        return False


def list_indexed_documents(mine_code: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """列出指定煤矿已索引的文档"""
    try:
        client = get_pageindex_client(mine_code)
        result = client.list_documents(limit=limit, offset=offset)
        return result.get("documents", [])
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        return []


def clear_client_cache():
    """清除客户端缓存（用于测试或配置更新）"""
    global _client_cache
    _client_cache.clear()
