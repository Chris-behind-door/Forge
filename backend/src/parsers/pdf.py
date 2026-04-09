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
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import fitz  # PyMuPDF
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 强制离线模式（国内网络环境）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from rapidocr_onnxruntime import RapidOCR  # noqa: E402

# 判断是否需要 OCR 的阈值：每页最少字符数
MIN_TEXT_CHARS_FOR_SKIP_OCR = 50

# 并行 OCR 的最大线程数
MAX_OCR_WORKERS = min(4, (os.cpu_count() or 4))

# 每个线程的 OCR 引擎（懒加载）
_ocr_engines: dict[int, RapidOCR] = {}
_ocr_lock = threading.Lock()


def _cleanup_ocr_engines() -> None:
    """清理所有 OCR 引擎，避免内存损坏警告"""
    global _ocr_engines
    with _ocr_lock:
        _ocr_engines.clear()


# 注册退出时的清理函数
atexit.register(_cleanup_ocr_engines)


def _get_ocr_engine() -> RapidOCR:
    """获取当前线程的 OCR 引擎（线程安全）"""
    thread_id = threading.get_ident()
    with _ocr_lock:
        if thread_id not in _ocr_engines:
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
    """
    解析 PDF 文件：文字提取/OCR + 分块

    性能优化：
    - 原生 PDF 直接提取，跳过 OCR
    - OCR 页面使用线程池并行处理
    - 动态调整线程数

    Args:
        pdf_path: PDF 文件路径
        chunk_size: 目标分块大小（字符数）
        chunk_overlap: 分块重叠大小（字符数）

    Returns:
        分块列表
    """
    start_time = datetime.now()

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    # ========== 第一遍：快速扫描，识别需要 OCR 的页面 ==========
    pages_needing_ocr = []
    pages_text = ["" for _ in range(total_pages)]

    for i in range(total_pages):
        page = doc[i]
        direct_text = _extract_text_directly(page)

        if len(direct_text.strip()) >= MIN_TEXT_CHARS_FOR_SKIP_OCR:
            pages_text[i] = direct_text
        else:
            pages_needing_ocr.append(i)

    scan_elapsed = (datetime.now() - start_time).total_seconds()

    # ========== 第二遍：并行处理需要 OCR 的页面 ==========
    if pages_needing_ocr:
        ocr_start = datetime.now()

        # 准备任务
        pages_to_process = [(i, doc[i]) for i in pages_needing_ocr]

        # 使用线程池并行处理
        num_workers = min(MAX_OCR_WORKERS, len(pages_needing_ocr))

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # 提交所有任务
            future_to_idx = {
                executor.submit(_process_page_with_ocr, page): idx
                for idx, page in pages_to_process
            }

            # 收集结果
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    pages_text[idx] = future.result()
                except Exception as e:
                    print(f"[PDF解析] 页面 {idx + 1} OCR 失败: {e}")
                    # 使用之前直接提取的结果（如果有）

        ocr_elapsed = (datetime.now() - ocr_start).total_seconds()
    else:
        ocr_elapsed = 0

    doc.close()

    total_elapsed = (datetime.now() - start_time).total_seconds()

    # 性能日志
    if total_elapsed > 1.0:
        print(
            f"[PDF解析] 总页数: {total_pages}, OCR页数: {len(pages_needing_ocr)}, "
            f"扫描: {scan_elapsed:.2f}s, OCR: {ocr_elapsed:.2f}s, "
            f"总计: {total_elapsed:.2f}s"
        )

    # ========== 合并文本并分块 ==========
    full_text = ""
    for i, text in enumerate(pages_text):
        full_text += f"\n\n[第 {i + 1} 页]\n\n{text}"

    full_text = full_text.strip()

    # 使用 LangChain 进行文本分块
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )

    chunks = splitter.split_text(full_text)

    # 提取页码标记
    page_markers = []
    for i, chunk in enumerate(chunks):
        match = re.search(r"\[第 (\d+) 页\]", chunk)
        if match:
            page_markers.append((i, int(match.group(1))))

    # 构建分块对象
    result = []
    for i, chunk in enumerate(chunks):
        # 从当前分块提取页码
        page_hint = None
        match = re.search(r"\[第 (\d+) 页\]", chunk)
        if match:
            page_hint = int(match.group(1))
        else:
            # 当前分块没有页码标记，向前查找最近的页码
            for marker_idx, marker_page in reversed(page_markers):
                if marker_idx < i:
                    page_hint = marker_page
                    break

        result.append(
            {
                "chunk_id": i,
                "text": chunk,
                "page": page_hint,
            }
        )

    return result
