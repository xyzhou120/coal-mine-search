"""
Excel 解析服务
解析导入 Excel 文件，提取文档元数据，处理上报频率字段
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import openpyxl

from app.utils.helpers import resolve_frequency_label, get_file_type_from_url, get_file_type_from_name

logger = logging.getLogger(__name__)

# Excel 列名映射（允许大小写不敏感匹配）
EXPECTED_COLUMNS = {
    "mine_code", "mine_name", "report_time", "update_rate",
    "cycle", "file_name_id", "file_name",
    "attachment_id", "attachment_name", "attachment_link",
}

REQUIRED_COLUMNS = {
    "mine_code", "mine_name", "file_name_id", "file_name",
    "attachment_id", "attachment_name", "attachment_link",
}


@dataclass
class DocumentMeta:
    """从 Excel 解析出的单条文档元数据"""
    attachment_id: str
    attachment_name: str
    attachment_link: str
    mine_code: str
    mine_name: str
    file_name_id: str
    file_name: str
    report_time: Optional[str] = None
    update_rate: Optional[int] = None
    cycle: Optional[str] = None
    frequency_label: str = ""
    file_type: str = "unknown"
    row_number: int = 0  # 原始行号，方便排查问题


@dataclass
class ExcelParseResult:
    """Excel 解析结果"""
    success: bool
    documents: list[DocumentMeta] = field(default_factory=list)
    skipped_rows: list[dict] = field(default_factory=list)  # 跳过的行（缺失必填字段）
    error: Optional[str] = None
    total_rows: int = 0
    valid_count: int = 0
    invalid_count: int = 0


def parse_excel(file_path: str) -> ExcelParseResult:
    """
    解析 Excel 文件，返回文档元数据列表

    Args:
        file_path: Excel 文件本地路径

    Returns:
        ExcelParseResult
    """
    path = Path(file_path)
    if not path.exists():
        return ExcelParseResult(success=False, error=f"文件不存在: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        return ExcelParseResult(success=False, error=f"不支持的文件格式: {suffix}，请使用 .xlsx 或 .xls")

    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    except Exception as e:
        return ExcelParseResult(success=False, error=f"打开 Excel 文件失败: {e}")

    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        return ExcelParseResult(success=False, error=f"读取 Excel 内容失败: {e}")
    finally:
        wb.close()

    if not rows:
        return ExcelParseResult(success=False, error="Excel 文件为空")

    # 解析表头（第一行），做列名映射（大小写不敏感）
    header_row = rows[0]
    col_map: dict[str, int] = {}  # 列名 -> 列索引
    for idx, cell in enumerate(header_row):
        if cell is not None:
            col_name = str(cell).strip().lower()
            col_map[col_name] = idx

    # 检查必填列是否存在
    missing = REQUIRED_COLUMNS - set(col_map.keys())
    if missing:
        return ExcelParseResult(
            success=False,
            error=f"Excel 缺少必填列: {', '.join(sorted(missing))}，"
                  f"当前列: {', '.join(sorted(col_map.keys()))}",
        )

    def get_cell(row: tuple, col_name: str) -> Optional[str]:
        """安全获取单元格值并转为字符串"""
        idx = col_map.get(col_name)
        if idx is None or idx >= len(row):
            return None
        val = row[idx]
        if val is None:
            return None
        return str(val).strip() or None

    def get_int_cell(row: tuple, col_name: str) -> Optional[int]:
        """安全获取整数单元格值"""
        val = get_cell(row, col_name)
        if val is None:
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    documents: list[DocumentMeta] = []
    skipped_rows: list[dict] = []
    total_rows = len(rows) - 1  # 去掉表头

    for row_idx, row in enumerate(rows[1:], start=2):  # 从第2行开始（1-indexed）
        # 跳过完全空白行
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        attachment_id = get_cell(row, "attachment_id")
        attachment_name = get_cell(row, "attachment_name")
        attachment_link = get_cell(row, "attachment_link")
        mine_code = get_cell(row, "mine_code")
        mine_name = get_cell(row, "mine_name")
        file_name_id = get_cell(row, "file_name_id")
        file_name = get_cell(row, "file_name")

        # 验证必填字段
        missing_fields = []
        if not attachment_id:
            missing_fields.append("attachment_id")
        if not attachment_name:
            missing_fields.append("attachment_name")
        if not attachment_link:
            missing_fields.append("attachment_link")
        if not mine_code:
            missing_fields.append("mine_code")
        if not mine_name:
            missing_fields.append("mine_name")
        if not file_name_id:
            missing_fields.append("file_name_id")
        if not file_name:
            missing_fields.append("file_name")

        if missing_fields:
            skipped_rows.append({
                "row": row_idx,
                "reason": f"缺少必填字段: {', '.join(missing_fields)}",
                "attachment_id": attachment_id,
            })
            logger.warning(f"第 {row_idx} 行跳过：缺少 {missing_fields}")
            continue

        # 验证 attachment_link 是有效 URL
        if not attachment_link.startswith(("http://", "https://")):
            skipped_rows.append({
                "row": row_idx,
                "reason": f"attachment_link 不是有效 URL: {attachment_link[:100]}",
                "attachment_id": attachment_id,
            })
            logger.warning(f"第 {row_idx} 行跳过：attachment_link 无效")
            continue

        report_time = get_cell(row, "report_time")
        update_rate = get_int_cell(row, "update_rate")
        cycle = get_cell(row, "cycle")

        frequency_label = resolve_frequency_label(update_rate, cycle)
        file_type = get_file_type_from_url(attachment_link)
        if file_type == "unknown":
            file_type = get_file_type_from_name(attachment_name)

        doc = DocumentMeta(
            attachment_id=attachment_id,
            attachment_name=attachment_name,
            attachment_link=attachment_link,
            mine_code=mine_code,
            mine_name=mine_name,
            file_name_id=file_name_id,
            file_name=file_name,
            report_time=report_time,
            update_rate=update_rate,
            cycle=cycle,
            frequency_label=frequency_label,
            file_type=file_type,
            row_number=row_idx,
        )
        documents.append(doc)

    logger.info(
        f"Excel 解析完成: 总行数={total_rows}, 有效={len(documents)}, 跳过={len(skipped_rows)}"
    )

    return ExcelParseResult(
        success=True,
        documents=documents,
        skipped_rows=skipped_rows,
        total_rows=total_rows,
        valid_count=len(documents),
        invalid_count=len(skipped_rows),
    )
