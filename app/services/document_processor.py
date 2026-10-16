"""
文档预处理服务
将各种格式文件统一转换为 PageIndex Local 可处理的带文字层 PDF

处理链：
  PDF(文字层)  → 直接使用
  PDF(扫描件)  → PaddleOCR-VL → 文字层PDF
  PDF(复杂图表/手写) → Qwen Vision → 文字层PDF
  Word (.doc/.docx)  → python-docx 提取 → 生成PDF
  Excel (.xls/.xlsx) → openpyxl 提取 → 生成PDF
"""
import base64
import io
import logging
import os
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import httpx
from openai import OpenAI

from app.config import get_settings
from app.utils.helpers import ensure_dir

logger = logging.getLogger(__name__)
settings = get_settings()


class DocumentProcessError(Exception):
    """文档处理失败异常"""
    pass


def get_processed_pdf_path(temp_dir: str) -> str:
    """获取预处理后 PDF 的目标路径"""
    return os.path.join(temp_dir, "processed.pdf")


def process_document(original_path: str, temp_dir: str) -> str:
    """
    将原始文件处理为带文字层的 PDF

    Args:
        original_path: 原始文件路径
        temp_dir: 临时目录（用于存放中间产物和结果）

    Returns:
        处理后的 PDF 文件路径

    Raises:
        DocumentProcessError: 处理失败时抛出
    """
    ensure_dir(temp_dir)
    output_path = get_processed_pdf_path(temp_dir)

    # 如果已处理过，直接返回
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        logger.info(f"已处理文件存在，跳过: {output_path}")
        return output_path

    ext = Path(original_path).suffix.lower()
    logger.info(f"开始处理文档: {original_path} (类型: {ext})")

    try:
        if ext == ".pdf":
            result = _process_pdf(original_path, output_path)
        elif ext in (".doc", ".docx"):
            result = _process_word(original_path, output_path)
        elif ext in (".xls", ".xlsx"):
            result = _process_excel(original_path, output_path)
        else:
            # 未知格式，尝试当 PDF 处理
            logger.warning(f"未知文件格式 {ext}，尝试当 PDF 处理")
            result = _process_pdf(original_path, output_path)

        logger.info(f"文档处理完成: {result}")
        return result
    except DocumentProcessError:
        raise
    except Exception as e:
        raise DocumentProcessError(f"文档处理失败: {e}") from e


# ------------------------------------------------------------------
# PDF 处理
# ------------------------------------------------------------------

def _process_pdf(input_path: str, output_path: str) -> str:
    """
    处理 PDF 文件
    - 检测是否有文字层
    - 无文字层则调用 OCR
    - 全部页面处理后输出为新 PDF
    """
    doc = fitz.open(input_path)
    total_pages = len(doc)
    logger.info(f"PDF 共 {total_pages} 页")

    # 检测文字层：统计全文档总字符数
    total_chars = sum(
        len(doc[i].get_text("text").strip())
        for i in range(min(total_pages, 5))  # 只检测前5页
    )
    avg_chars_per_page = total_chars / min(total_pages, 5) if total_pages > 0 else 0

    if avg_chars_per_page >= settings.pdf_text_threshold:
        # 有文字层，直接复制
        logger.info(f"PDF 有文字层（均{avg_chars_per_page:.0f}字/页），直接使用")
        doc.close()
        import shutil
        shutil.copy2(input_path, output_path)
        return output_path

    # 无文字层，需要 OCR
    logger.info(f"PDF 为扫描件（均{avg_chars_per_page:.0f}字/页），启动 OCR")
    doc.close()
    return _ocr_pdf(input_path, output_path)


def _ocr_pdf(input_path: str, output_path: str) -> str:
    """
    对扫描件 PDF 每页进行 OCR，将识别文字写入新 PDF
    优先使用 PaddleOCR-VL，未配置时回退到 Qwen Vision
    """
    doc = fitz.open(input_path)
    new_doc = fitz.open()  # 新建空白 PDF

    for page_num in range(len(doc)):
        page = doc[page_num]

        # 将页面渲染为图片（300 DPI 保证 OCR 质量）
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        logger.info(f"OCR 第 {page_num + 1}/{len(doc)} 页...")

        # 调用 OCR 模型识别文字
        ocr_text = _call_ocr(img_bytes, page_num + 1)

        # 创建新页面并写入识别到的文字
        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        if ocr_text:
            # 将 OCR 文字作为不可见文字层写入（原始图片 + 文字层叠加）
            new_page.insert_image(new_page.rect, stream=img_bytes)
            # 在透明文字层中写入 OCR 结果（供检索，不可见）
            new_page.insert_textbox(
                new_page.rect,
                ocr_text,
                fontsize=8,
                color=(1, 1, 1),  # 白色不可见
                overlay=False,
            )
        else:
            new_page.insert_image(new_page.rect, stream=img_bytes)

    doc.close()
    new_doc.save(output_path)
    new_doc.close()
    logger.info(f"OCR PDF 生成完成: {output_path}")
    return output_path


def _call_ocr(img_bytes: bytes, page_num: int) -> str:
    """
    调用 OCR 模型识别图片中的文字
    优先 PaddleOCR-VL，未配置时回退到 Qwen Vision
    """
    if settings.paddleocr_configured:
        try:
            return _call_paddleocr(img_bytes)
        except Exception as e:
            logger.warning(f"PaddleOCR 调用失败，回退到视觉模型: {e}")

    if settings.vision_configured:
        return _call_vision_model(img_bytes, page_num)

    logger.warning(f"OCR 和视觉模型均未配置，第 {page_num} 页将无文字层")
    return ""


def _call_paddleocr(img_bytes: bytes) -> str:
    """调用 PaddleOCR-VL API（OpenAI 兼容接口）"""
    client = OpenAI(
        base_url=settings.paddleocr_api_base_url,
        api_key=settings.paddleocr_api_key or "none",
        timeout=settings.paddleocr_request_timeout,
    )
    b64_image = base64.b64encode(img_bytes).decode("utf-8")
    response = client.chat.completions.create(
        model=settings.paddleocr_model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                    {
                        "type": "text",
                        "text": "请识别图片中的所有文字内容，保持原有格式和排版，直接输出文字，不要添加任何说明。",
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content or ""


def _call_vision_model(img_bytes: bytes, page_num: int) -> str:
    """调用 Qwen Vision 模型（OpenAI 兼容接口）"""
    client = OpenAI(
        base_url=settings.vision_api_base_url,
        api_key=settings.vision_api_key or "none",
        timeout=settings.vision_request_timeout,
    )
    b64_image = base64.b64encode(img_bytes).decode("utf-8")
    response = client.chat.completions.create(
        model=settings.vision_model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "请识别并提取图片中的所有文字内容，包括表格、手写文字和印刷文字。"
                            "保持原有格式，表格用 markdown 格式输出，直接输出内容，不要说明。"
                        ),
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content or ""


# ------------------------------------------------------------------
# Word 处理
# ------------------------------------------------------------------

def _process_word(input_path: str, output_path: str) -> str:
    """
    处理 Word 文档：提取文字内容，生成带文字层的 PDF
    """
    try:
        from docx import Document
        doc = Document(input_path)
    except Exception as e:
        raise DocumentProcessError(f"打开 Word 文件失败: {e}") from e

    # 提取所有文字内容
    content_parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            # 根据段落样式加前缀（简单的标题识别）
            style_name = para.style.name.lower() if para.style else ""
            if "heading" in style_name or "标题" in style_name:
                content_parts.append(f"\n{'#' * 2} {text}\n")
            else:
                content_parts.append(text)

    # 处理表格
    for table in doc.tables:
        table_lines = []
        for i, row in enumerate(table.rows):
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            table_lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                table_lines.append("|" + "|".join(["---"] * len(cells)) + "|")
        if table_lines:
            content_parts.append("\n" + "\n".join(table_lines) + "\n")

    full_text = "\n".join(content_parts)
    return _text_to_pdf(full_text, output_path)


# ------------------------------------------------------------------
# Excel 处理
# ------------------------------------------------------------------

def _process_excel(input_path: str, output_path: str) -> str:
    """
    处理 Excel 文件：提取所有 Sheet 内容，转为 markdown 格式 PDF
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    except Exception as e:
        raise DocumentProcessError(f"打开 Excel 文件失败: {e}") from e

    content_parts = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        content_parts.append(f"\n## 工作表：{sheet_name}\n")

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            content_parts.append("（空工作表）\n")
            continue

        # 过滤完全空白的行
        non_empty_rows = [
            row for row in rows
            if any(cell is not None and str(cell).strip() != "" for cell in row)
        ]

        if not non_empty_rows:
            content_parts.append("（空工作表）\n")
            continue

        # 生成 markdown 表格
        max_cols = max(len(row) for row in non_empty_rows)
        table_lines = []

        for i, row in enumerate(non_empty_rows):
            # 补齐列数
            cells = list(row) + [None] * (max_cols - len(row))
            cell_texts = [str(c).strip() if c is not None else "" for c in cells]
            table_lines.append("| " + " | ".join(cell_texts) + " |")
            if i == 0:
                table_lines.append("|" + "|".join(["---"] * max_cols) + "|")

        content_parts.append("\n".join(table_lines) + "\n")

    wb.close()
    full_text = "\n".join(content_parts)
    return _text_to_pdf(full_text, output_path)


# ------------------------------------------------------------------
# 文字转 PDF
# ------------------------------------------------------------------

def _text_to_pdf(text: str, output_path: str) -> str:
    """
    将文字内容转为 PDF（使用 pymupdf，支持中文）
    """
    doc = fitz.open()

    # 页面设置：A4
    page_width, page_height = 595, 842  # A4 points
    margin = 50
    line_height = 14
    font_size = 10

    lines = text.split("\n")
    current_lines = []

    def flush_page(lines_to_write: list[str]) -> None:
        """将一批行写入新页面"""
        page = doc.new_page(width=page_width, height=page_height)
        y = margin
        for line in lines_to_write:
            if y + line_height > page_height - margin:
                break
            try:
                page.insert_text(
                    (margin, y),
                    line,
                    fontsize=font_size,
                    color=(0, 0, 0),
                )
            except Exception:
                # 某些特殊字符可能导致插入失败，跳过该行
                pass
            y += line_height

    max_lines_per_page = (page_height - 2 * margin) // line_height

    for line in lines:
        current_lines.append(line)
        if len(current_lines) >= max_lines_per_page:
            flush_page(current_lines)
            current_lines = []

    if current_lines:
        flush_page(current_lines)

    if len(doc) == 0:
        # 至少创建一页
        doc.new_page(width=page_width, height=page_height)

    doc.save(output_path)
    doc.close()
    return output_path
