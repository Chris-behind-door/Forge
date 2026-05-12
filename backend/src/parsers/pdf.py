"""
PDF 解析模块

处理流程：
1. 尝试直接提取 PDF 文字（对于原生 PDF 很快）
2. 如果页面文字太少（可能是扫描件），才做 OCR
3. 使用 LangChain 进行文本分块

性能优化：
- 原生 PDF 直接提取文字，跳过 OCR
- OCR 使用线程池并行处理（ONNX Runtime 会释放 GIL）
- 每个线程独立的 OCR 引擎，避免竞争
"""

import atexit
import logging
import os
import re
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import fitz  # PyMuPDF
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# 强制离线模式（国内网络环境）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Minimum ratio of extractable text to page area to skip OCR.
# Pages with very little direct text (headers, footers, page numbers)
# but mostly images/formulas still need OCR.  A page with < 200 chars
# of direct text is almost certainly missing most of its content.
MIN_TEXT_CHARS_FOR_SKIP_OCR = 200

# 并行 OCR 的最大线程数
MAX_OCR_WORKERS = min(4, (os.cpu_count() or 4))

# 每个线程的 OCR 引擎（懒加载）
_ocr_engines: dict = {}
_ocr_lock = threading.Lock()


def _cleanup_ocr_engines() -> None:
    """清理所有 OCR 引擎，避免内存损坏警告"""
    global _ocr_engines
    with _ocr_lock:
        _ocr_engines.clear()


# 注册退出时的清理函数
atexit.register(_cleanup_ocr_engines)


def _get_ocr_engine():
    """获取当前线程的 OCR 引擎（线程安全，首次调用时才 import rapidocr）"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        raise RuntimeError(
            f"OCR engine not available (rapidocr_onnxruntime import failed: {e}). "
            "PDF pages requiring OCR will be skipped."
        ) from e
    thread_id = threading.get_ident()
    with _ocr_lock:
        if thread_id not in _ocr_engines:
            logger.info("Initializing OCR engine for thread %s", thread_id)
            _ocr_engines[thread_id] = RapidOCR()
        return _ocr_engines[thread_id]


def _extract_text_directly(page: fitz.Page) -> str:
    """
    直接从 PDF 页面提取文字（不使用 OCR）

    Args:
        page: PyMuPDF 页面对象

    Returns:
        提取的文字
    """
    blocks = page.get_text("blocks")

    if not blocks:
        return ""

    # 按位置排序
    text_blocks = []
    for block in blocks:
        if block[6] != 0:  # 跳过图片块
            continue
        text = block[4].strip()
        if text:
            text_blocks.append((block[1], block[0], text))

    # 按 Y 坐标排序
    line_tolerance = 10
    text_blocks.sort(key=lambda b: (round(b[0] / line_tolerance), b[1]))

    return "\n".join(t[2] for t in text_blocks)


def _ocr_page(page: fitz.Page) -> str:
    """
    对 PDF 页面进行 OCR 识别

    Args:
        page: PyMuPDF 页面对象

    Returns:
        OCR 识别的文字
    """
    # 渲染页面为图像
    mat = fitz.Matrix(150 / 72, 150 / 72)  # 150 DPI
    pix = page.get_pixmap(matrix=mat)
    img = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img.reshape(pix.height, pix.width, pix.n)

    # OCR 识别
    ocr = _get_ocr_engine()
    result, _ = ocr(img)

    if not result:
        return ""

    # 按阅读顺序排序
    blocks = []
    for item in result:
        box, text, conf = item
        y_center = (box[0][1] + box[2][1]) / 2
        x_left = box[0][0]
        blocks.append((y_center, x_left, text))

    line_height_tolerance = 15
    blocks.sort(key=lambda b: (round(b[0] / line_height_tolerance), b[1]))

    # 合并为行
    lines = []
    current_y = None
    current_line = []

    for y, x, text in blocks:
        if current_y is None or abs(y - current_y) < line_height_tolerance:
            current_line.append(text)
            current_y = y
        else:
            lines.append(" ".join(current_line))
            current_line = [text]
            current_y = y

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def _process_page_with_ocr(page: fitz.Page) -> str:
    """
    处理单个页面：先尝试直接提取，必要时 OCR

    Args:
        page: PyMuPDF 页面对象

    Returns:
        页面文字
    """
    # 先尝试直接提取
    direct_text = _extract_text_directly(page)

    if len(direct_text.strip()) >= MIN_TEXT_CHARS_FOR_SKIP_OCR:
        return direct_text

    # 文字太少，使用 OCR
    ocr_text = _ocr_page(page)

    # 取更好的结果
    if len(ocr_text.strip()) > len(direct_text.strip()):
        return ocr_text

    return direct_text


def parse_pdf(
    pdf_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """解析 PDF 文件，返回所有分块。

    详见 :func:`parse_pdf_iter` 的文档了解性能优化策略。
    """
    result: list[dict] = []
    for batch in parse_pdf_iter(pdf_path, chunk_size, chunk_overlap):
        result.extend(batch)
    return result


def parse_pdf_iter(
    pdf_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    pages_per_batch: int = 20,
) -> Generator[list[dict], None, None]:
    """Streaming variant of parse_pdf.

    Yields batches of chunks grouped by page ranges
    (``pages_per_batch`` pages at a time) so the caller can embed +
    write to DB incrementally, keeping peak memory bounded.
    """
    start_time = datetime.now()
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )

    chunk_id = 0

    for page_start in range(0, total_pages, pages_per_batch):
        page_end = min(page_start + pages_per_batch, total_pages)
        pages_text: list[str] = [""] * (page_end - page_start)
        pages_needing_ocr: list[tuple[int, object]] = []

        for offset in range(page_end - page_start):
            page_idx = page_start + offset
            page = doc[page_idx]
            direct_text = _extract_text_directly(page)
            if len(direct_text.strip()) >= MIN_TEXT_CHARS_FOR_SKIP_OCR:
                pages_text[offset] = direct_text
            else:
                pages_needing_ocr.append((offset, page))

        # OCR for this batch
        if pages_needing_ocr:
            num_workers = min(MAX_OCR_WORKERS, len(pages_needing_ocr))
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_to_offset = {
                    executor.submit(_process_page_with_ocr, page): offset
                    for offset, page in pages_needing_ocr
                }
                for future in as_completed(future_to_offset):
                    offset = future_to_offset[future]
                    try:
                        pages_text[offset] = future.result()
                    except Exception as e:
                        logger.warning("页面 %d OCR 失败: %s", page_start + offset + 1, e)

        # Build text with page markers
        full_text = ""
        for offset, text in enumerate(pages_text):
            full_text += f"\n\n[第 {page_start + offset + 1} 页]\n\n{text}"
        full_text = full_text.strip()

        del pages_text

        if not full_text.strip():
            continue

        chunks = splitter.split_text(full_text)
        del full_text

        # Extract page markers for this batch
        page_markers: list[tuple[int, int]] = []
        for i, chunk in enumerate(chunks):
            match = re.search(r"\[第 (\d+) 页\]", chunk)
            if match:
                page_markers.append((i, int(match.group(1))))

        batch: list[dict] = []
        for i, chunk in enumerate(chunks):
            page_hint = None
            match = re.search(r"\[第 (\d+) 页\]", chunk)
            if match:
                page_hint = int(match.group(1))
            else:
                for marker_idx, marker_page in reversed(page_markers):
                    if marker_idx < i:
                        page_hint = marker_page
                        break
            batch.append({
                "chunk_id": chunk_id,
                "text": chunk,
                "page": page_hint,
            })
            chunk_id += 1

        yield batch

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        "[PDF解析] 总页数: %d, 分批处理完成, 耗时: %.2fs",
        total_pages, elapsed,
    )
    doc.close()
