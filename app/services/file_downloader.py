"""
MinIO 文件下载服务
从 MinIO HTTPS URL 下载文件到本地临时目录，支持重试和 SSL 跳过
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from app.config import get_settings
from app.utils.helpers import ensure_dir, safe_filename

logger = logging.getLogger(__name__)
settings = get_settings()


class FileDownloadError(Exception):
    """文件下载失败异常"""
    pass


def get_temp_dir(mine_code: str, attachment_id: str) -> str:
    """获取文件临时存储目录"""
    safe_mine = safe_filename(mine_code)
    safe_att = safe_filename(attachment_id)
    temp_path = os.path.join(settings.temp_file_dir, safe_mine, safe_att)
    ensure_dir(temp_path)
    return temp_path


def download_file(
    url: str,
    mine_code: str,
    attachment_id: str,
    attachment_name: str,
) -> str:
    """
    从 MinIO HTTPS URL 下载文件到本地临时目录

    Args:
        url: MinIO HTTPS 文件地址
        mine_code: 煤矿编码（用于目录隔离）
        attachment_id: 附件ID（用于目录命名）
        attachment_name: 附件名称（用于推断文件扩展名）

    Returns:
        下载后的本地文件路径

    Raises:
        FileDownloadError: 下载失败时抛出
    """
    temp_dir = get_temp_dir(mine_code, attachment_id)

    # 从 URL 或附件名推断扩展名
    ext = _get_extension(url, attachment_name)
    local_filename = f"original{ext}"
    local_path = os.path.join(temp_dir, local_filename)

    # 如果文件已存在且大小正常，直接返回（断点续传）
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        logger.info(f"文件已存在，跳过下载: {local_path}")
        return local_path

    max_retries = settings.minio_download_max_retries
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"下载文件 (第{attempt}次): {url[:80]}...")
            _do_download(url, local_path)
            logger.info(f"下载完成: {local_path} ({os.path.getsize(local_path)} bytes)")
            return local_path
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait_time = 2 ** attempt  # 指数退避：2s, 4s, 8s
                logger.warning(f"下载失败 (第{attempt}次)，{wait_time}秒后重试: {e}")
                time.sleep(wait_time)
            else:
                logger.error(f"下载失败，已重试 {max_retries} 次: {e}")

    raise FileDownloadError(f"下载失败，已重试 {max_retries} 次: {last_error}")


def _do_download(url: str, local_path: str) -> None:
    """执行实际下载"""
    verify_ssl = settings.minio_verify_ssl
    timeout = settings.minio_download_timeout

    with httpx.Client(verify=verify_ssl, timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)

    # 校验文件大小
    size = os.path.getsize(local_path)
    if size == 0:
        os.remove(local_path)
        raise FileDownloadError("下载后文件大小为 0，可能是空文件或下载中断")


def cleanup_temp_files(mine_code: str, attachment_id: str) -> None:
    """
    清理临时文件目录（索引完成后调用）
    """
    temp_dir = get_temp_dir(mine_code, attachment_id)
    if os.path.exists(temp_dir):
        import shutil
        try:
            shutil.rmtree(temp_dir)
            logger.debug(f"已清理临时目录: {temp_dir}")
        except Exception as e:
            logger.warning(f"清理临时目录失败: {temp_dir}: {e}")


def _get_extension(url: str, filename: str) -> str:
    """从 URL 或文件名推断扩展名"""
    # 优先从 URL 推断（去掉 query string）
    clean_url = url.split("?")[0]
    ext = Path(clean_url).suffix.lower()
    if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
        return ext

    # 从文件名推断
    ext = Path(filename).suffix.lower()
    if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
        return ext

    return ".pdf"  # 默认 PDF
