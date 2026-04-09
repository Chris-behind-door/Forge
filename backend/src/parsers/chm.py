"""
CHM 解析模块

处理流程：
1. 使用 7z 解压 CHM 文件到临时目录
2. 遍历所有 HTML 文件
3. 使用 BeautifulSoup 提取文本内容
4. 使用 LangChain 进行文本分块

CHM 格式说明：
- CHM (Compiled HTML Help) 是 Windows 帮助文件格式
- 本质上是多个 HTML 文件的压缩包
- 通常包含目录结构，每个章节是独立的 HTML 文件
"""

import re
import shutil
import subprocess

from pathlib import Path

from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter


def _extract_chm(chm_path: str, output_dir: str) -> bool:
    """
    使用 7z 解压 CHM 文件

    Args:
        chm_path: CHM 文件路径
        output_dir: 输出目录

    Returns:
        是否成功
    """
    try:
        result = subprocess.run(
            ["7z", "x", "-y", f"-o{output_dir}", chm_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[CHM解析] 解压超时: {chm_path}")
        return False
    except Exception as e:
        print(f"[CHM解析] 解压失败: {e}")
        return False


def _detect_encoding(html_content: bytes) -> str:
    """
    检测 HTML 内容的编码

    优先级：
    1. HTML meta 标签中的 charset
    2. GBK（CHM 最常见的中文编码）
    3. UTF-8

    Args:
        html_content: 原始 HTML 字节

    Returns:
        编码名称
    """
    # 尝试从 meta 标签提取编码
    try:
        # 先用 ASCII 兼容方式解析前 1024 字节
        head = html_content[:1024].decode("ascii", errors="ignore")

        # 查找 charset
        import re

        match = re.search(r'charset=["\']?([^"\'>\s]+)', head, re.IGNORECASE)
        if match:
            charset = match.group(1).strip()
            # 常见编码别名映射
            encoding_map = {
                "gb2312": "gb18030",
                "gbk": "gb18030",
                "x-gbk": "gb18030",
            }
            return encoding_map.get(charset.lower(), charset)
    except Exception:
        pass

    # 默认使用 gb18030（GBK 的超集，兼容中文 CHM）
    return "gb18030"


def _extract_text_from_html(html_content: str) -> str:
    """
    从 HTML 内容中提取纯文本

    Args:
        html_content: HTML 内容

    Returns:
        纯文本
    """
    # 优先用 BeautifulSoup，失败时用正则 fallback
    try:
        return _extract_text_bs(html_content)
    except Exception:
        return _extract_text_regex(html_content)


def _extract_text_bs(html_content: str) -> str:
    """使用 BeautifulSoup 提取文本"""
    soup = BeautifulSoup(html_content, "html.parser")

    # 移除脚本和样式
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    lines = (line for line in lines if line)
    return "\n".join(lines)


def _extract_text_regex(html_content: str) -> str:
    """使用正则表达式暴力提取文本（fallback）"""
    import html as html_mod

    # 解码 HTML 实体
    text = html_mod.unescape(html_content)

    # 移除 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)

    # 移除 CSS 样式块
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
    )

    # 清理空白
    lines = (line.strip() for line in text.splitlines())
    lines = (line for line in lines if line)
    return "\n".join(lines)


def _find_html_files(directory: str) -> list[Path]:
    """
    递归查找所有 HTML 文件

    Args:
        directory: 目录路径

    Returns:
        HTML 文件路径列表（按路径排序）
    """
    html_files = []
    path = Path(directory)

    for ext in ["*.htm", "*.html", "*.HTM", "*.HTML"]:
        html_files.extend(path.rglob(ext))

    # 按路径排序，保持逻辑顺序
    html_files.sort(key=lambda p: str(p).lower())

    return html_files


def _extract_page_hint(filepath: Path, base_dir: Path) -> str | None:
    """
    从文件路径提取"页码"提示（实际上是文件路径/章节名）

    对于 CHM，没有真正的页码，我们用文件路径作为位置标识

    Args:
        filepath: 文件路径
        base_dir: 基础目录

    Returns:
        位置标识
    """
    try:
        relative = filepath.relative_to(base_dir)
        # 返回完整的 HTML 相对路径（如 "子目录/index.html"）
        return str(relative)
    except ValueError:
        return None


def _extract_location_tag(text: str) -> str | None:
    """
    从文本中提取 [位置: xxx] 标记的值。
    使用括号深度计数以正确处理 location 中的嵌套方括号
    （如 "建筑抗震设计规范[附条文说明]/xxx.html"）。
    """
    prefix = "[位置: "
    start = text.find(prefix)
    if start == -1:
        return None
    content_start = start + len(prefix)
    depth = 1
    i = content_start
    while i < len(text) and depth > 0:
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
        i += 1
    if depth == 0:
        return text[content_start : i - 1]
    return None


def parse_chm(
    chm_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    解析 CHM 文件：解压 + HTML提取 + 分块

    Args:
        chm_path: CHM 文件路径
        chunk_size: 目标分块大小（字符数）
        chunk_overlap: 分块重叠大小（字符数）

    Returns:
        分块列表
    """
    # 解压到持久目录（stored_path 同级的 {stem}_extracted/）
    chm_p = Path(chm_path)
    extract_dir = chm_p.parent / f"{chm_p.stem}_extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    try:
        if not _extract_chm(chm_path, str(extract_dir)):
            raise RuntimeError(f"无法解压 CHM 文件: {chm_path}")

        html_files = _find_html_files(str(extract_dir))

        if not html_files:
            print(f"[CHM解析] 未找到 HTML 文件: {chm_path}")
            return []

        print(f"[CHM解析] 找到 {len(html_files)} 个 HTML 文件")

        # 提取所有 HTML 的文本
        all_texts = []
        base_dir = extract_dir

        for html_file in html_files:
            try:
                # 先以二进制读取，检测编码后再解码
                with open(html_file, "rb") as f:
                    raw_content = f.read()

                encoding = _detect_encoding(raw_content)
                html_content = raw_content.decode(encoding, errors="replace")

                text = _extract_text_from_html(html_content)

                if text.strip():
                    # 获取位置标识
                    location = _extract_page_hint(html_file, base_dir)
                    all_texts.append((location, text))

            except Exception as e:
                print(f"[CHM解析] 解析 HTML 失败 {html_file}: {e}")
                continue

        # 合并文本，添加位置标记
        full_text = ""
        for location, text in all_texts:
            if location:
                full_text += f"\n\n[位置: {location}]\n\n{text}"
            else:
                full_text += f"\n\n{text}"

        full_text = full_text.strip()

        if not full_text:
            return []

        # 使用 LangChain 进行文本分块
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        )

        chunks = splitter.split_text(full_text)

        # 提取位置标记
        location_markers = []
        for i, chunk in enumerate(chunks):
            loc = _extract_location_tag(chunk)
            if loc:
                location_markers.append((i, loc))

        # 构建分块对象
        result = []
        for i, chunk in enumerate(chunks):
            # 从当前分块提取位置
            location = _extract_location_tag(chunk)
            if not location:
                # 当前分块没有位置标记，向前查找
                for marker_idx, marker_loc in reversed(location_markers):
                    if marker_idx < i:
                        location = marker_loc
                        break

            result.append(
                {
                    "chunk_id": i,
                    "text": chunk,
                    "page": None,  # CHM 没有页码
                    "location": location,  # 用 location 代替 page
                }
            )

        return result

    finally:
        pass  # 解压目录保留，用于后续 CHM HTML 查看
