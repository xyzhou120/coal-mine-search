"""
通用工具函数
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 上报频率映射
UPDATE_RATE_MAP = {
    1: "日报",
    7: "周报",
    10: "旬报",
    30: "月报",
    90: "季报",
    180: "半年报",
    360: "年报",
}

CYCLE_MAP = {
    "日": "日报",
    "周": "周报",
    "旬": "旬报",
    "月": "月报",
    "季": "季报",
    "半年": "半年报",
    "年": "年报",
}

FILE_TYPE_MAP = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".xls": "excel",
    ".xlsx": "excel",
    ".ppt": "ppt",
    ".pptx": "ppt",
}


def resolve_frequency_label(update_rate: Optional[int], cycle: Optional[str]) -> str:
    """
    解析上报频率标签
    - update_rate=0 时，由 cycle 枚举（日/周/旬/月/季/半年/年）决定
    - update_rate!=0 时，数值 1/7/10/30/90/180/360 决定
    """
    if update_rate is None:
        return cycle or "未知"
    if update_rate == 0:
        return CYCLE_MAP.get(cycle or "", cycle or "未知")
    return UPDATE_RATE_MAP.get(update_rate, f"每{update_rate}天")


def get_file_type_from_url(url: str) -> str:
    """从 URL 或文件名推断文件类型"""
    url_lower = url.lower().split("?")[0]  # 去掉 query string
    for ext, ftype in FILE_TYPE_MAP.items():
        if url_lower.endswith(ext):
            return ftype
    return "unknown"


def get_file_type_from_name(name: str) -> str:
    """从文件名推断文件类型"""
    ext = Path(name).suffix.lower()
    return FILE_TYPE_MAP.get(ext, "unknown")


def generate_task_id() -> str:
    return str(uuid.uuid4())


def ensure_dir(path: str) -> str:
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """将字符串转为安全的文件名（移除特殊字符）"""
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:200]  # 限制长度


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"
