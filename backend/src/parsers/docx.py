"""
DOCX 解析模块

处理流程：
1. 使用 python-docx 打开 .docx 文件
2. 预提取所有图片资源到字典 {rId: bytes}
3. 按 body 元素顺序遍历（段落和表格交错）
4. 段落：提取文字，检测内联图片 → OCR → 插入 OCR 文本
5. 表格：格式化为结构化文本
6. 使用 LangChain RecursiveCharacterTextSplitter 进行文本分块

OCR 复用 pdf.py 中的 _get_ocr_engine()，支持 GPU 加速。
"""

import logging
import re
from collections.abc import Generator

from docx import Document
from docx.oxml.ns import qn
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


def _extract_images(doc) -> dict[str, bytes]:
    """从文档关系中提取所有图片资源。

    Args:
        doc: python-docx Document 对象

    Returns:
        {rId: image_bytes} 字典
    """
    images: dict[str, bytes] = {}
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            images[rel.rId] = rel.target_part.blob
    return images


def _ocr_image_bytes(image_bytes: bytes) -> str:
    from .ocr import ocr_image
    return ocr_image(image_bytes)


def _get_inline_image_rids(paragraph_element) -> list[str]:
    """提取段落中所有内联图片的关系 ID。

    Args:
        paragraph_element: 段落的 XML 元素（lxml）

    Returns:
        关系 ID 列表
    """
    rids: list[str] = []
    for blip in paragraph_element.findall('.//' + qn('a:blip')):
        rid = blip.get(qn('r:embed'))
        if rid:
            rids.append(rid)
    return rids


def _format_table(table) -> str:
    """将表格格式化为文本。

    Args:
        table: docx.table.Table 对象

    Returns:
        格式化后的表格文本
    """
    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _is_heading(style_val: str) -> bool:
    """判断样式值是否为标题样式（不区分大小写）。

    Args:
        style_val: w:pStyle 的 val 属性值

    Returns:
        是否为标题样式
    """
    lower = style_val.lower().replace(" ", "")
    return lower.startswith("heading") or lower.startswith("标题")


def _get_paragraph_text(paragraph_element) -> str:
    """从段落 XML 元素提取完整文本。

    Args:
        paragraph_element: 段落的 XML 元素

    Returns:
        段落文本
    """
    text_parts: list[str] = []
    for run_elem in paragraph_element.findall('.//' + qn('w:r')):
        t = run_elem.find(qn('w:t'))
        if t is not None and t.text:
            text_parts.append(t.text)
    return "".join(text_parts)


def parse_docx(
    docx_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """解析 DOCX 文件，返回所有分块。

    详见 :func:`parse_docx_iter` 的文档了解处理流程。
    """
    result: list[dict] = []
    for batch in parse_docx_iter(docx_path, chunk_size, chunk_overlap):
        result.extend(batch)
    return result


def parse_docx_iter(
    docx_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    yield_every: int = 100,
) -> Generator[list[dict], None, None]:
    """流式解析 DOCX 文件，按批次 yield 分块。

    按文档 body 元素顺序遍历段落和表格，提取文字和图片 OCR 内容，
    使用最近的标题作为 location 元数据。

    Args:
        docx_path: DOCX 文件路径
        chunk_size: 分块大小
        chunk_overlap: 分块重叠
        yield_every: 每批 yield 的分块数

    Yields:
        分块字典列表
    """
    from docx.table import Table

    doc = Document(docx_path)
    images = _extract_images(doc)

    text_parts: list[str] = []

    for child in doc.element.body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

        if tag == 'p':
            para_text = _get_paragraph_text(child)

            pPr = child.find(qn('w:pPr'))
            if pPr is not None:
                pStyle = pPr.find(qn('w:pStyle'))
                if pStyle is not None:
                    style_val = pStyle.get(qn('w:val'), '')
                    if _is_heading(style_val) and para_text.strip():
                        text_parts.append(f"\n[章节: {para_text.strip()}]\n")

            # 提取内联图片并 OCR
            rids = _get_inline_image_rids(child)
            for rid in rids:
                if rid in images:
                    ocr_text = _ocr_image_bytes(images[rid])
                    if ocr_text:
                        text_parts.append(f"\n[图片内容]\n{ocr_text}\n")

            # 添加段落文本
            if para_text.strip():
                text_parts.append(para_text)

        elif tag == 'tbl':
            table = Table(child, doc)
            table_text = _format_table(table)
            if table_text.strip():
                text_parts.append(f"\n[表格]\n{table_text}\n")

    # 合并所有文本
    full_text = "\n\n".join(part for part in text_parts if part.strip())

    if not full_text.strip():
        return

    # 分块
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    chunks = splitter.split_text(full_text)

    # 提取章节标记用于 location 元数据
    heading_markers: list[tuple[int, str]] = []
    for i, chunk_text in enumerate(chunks):
        match = re.search(r"\[章节: ([^\]]+)\]", chunk_text)
        if match:
            heading_markers.append((i, match.group(1)))

    batch: list[dict] = []
    for i, chunk_text in enumerate(chunks):
        # 从当前 chunk 或之前的最近标记中提取 location
        location = None
        for marker_idx, heading in reversed(heading_markers):
            if marker_idx <= i:
                location = heading
                break

        batch.append({
            "chunk_id": i,
            "text": chunk_text,
            "page": None,
            "location": location,
        })
        if len(batch) >= yield_every:
            yield batch
            batch = []

    if batch:
        yield batch
