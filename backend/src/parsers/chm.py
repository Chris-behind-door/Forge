"""
CHM 解析模块

处理流程：
1. 使用 7z 解压 CHM 文件到临时目录
2. 按一级子目录识别"文档"（每本规范/书籍）
3. 每个 HTML 文件作为一个"章节"，提取标题
4. 使用 BeautifulSoup 提取文本内容
5. 分块时保留层级信息（parent_title + chapter）

层级结构（CHM 特有）：
  CHM 根目录
  ├── 规范A/           ← 文档（parent）
  │   ├── 001.html     ← 章节（chapter）
  │   ├── 002.html
  │   └── ...
  ├── 规范B/
  │   ├── 001.html
  │   └── ...
  └── 单文件.html       ← 无子目录，扁平处理

分块输出格式：
  每个 chunk 携带 parent_title（所属规范名）和 chapter（章节名），
  编码到 text 中作为 [文档:xxx] 和 [章节:xxx] 标记。
"""

import os
import re
import shutil
import subprocess
import logging
import sys

from pathlib import Path

from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


def _sanitize_path(path: str) -> str:
    """Sanitize file path to prevent injection in subprocess calls."""
    resolved = Path(path).resolve()
    # Ensure no path traversal
    if ".." in str(resolved):
        raise ValueError(f"Path traversal detected: {path}")
    return str(resolved)


def _unblock_file_windows(file_path: str) -> None:
    """Remove Zone.Identifier (Windows "blocked" flag) from a file.

    Windows marks files from network/shares/downloads with a Zone.Identifier
    alternate data stream. hh.exe silently refuses to decompile such CHM files.
    """
    try:
        subprocess.run(
            ["powershell", "-Command",
             f"Unblock-File -Path '{file_path}' -ErrorAction SilentlyContinue"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        logger.debug("Unblock-File failed (non-critical)")


def _extract_chm_hh(chm_path: str, output_dir: str) -> bool:
    """Windows: use built-in hh.exe -decompile (no install needed)."""
    import time

    try:
        safe_chm = _sanitize_path(chm_path)
        safe_output = _sanitize_path(output_dir)
        # Ensure output dir exists
        Path(safe_output).mkdir(parents=True, exist_ok=True)
        # Try multiple hh.exe locations (Win10/11 may differ)
        hh_candidates = [
            str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'hh.exe'),
            'hh.exe',  # fallback to PATH
        ]
        hh_exe = None
        for candidate in hh_candidates:
            if Path(candidate).exists() or shutil.which(candidate):
                hh_exe = candidate
                break
        if not hh_exe:
            logger.debug('hh.exe not found on this system')
            return False

        # Remove Windows Zone.Identifier before decompiling
        _unblock_file_windows(safe_chm)

        logger.info('Using hh.exe: %s', hh_exe)
        result = subprocess.run(
            [hh_exe, '-decompile', safe_output, safe_chm],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # hh.exe may return before decompile finishes on some Windows versions.
        # Poll the output directory for up to 30 seconds.
        output_path = Path(safe_output)
        for attempt in range(30):
            if output_path.exists() and any(output_path.iterdir()):
                return True
            time.sleep(1)

        logger.warning('hh.exe produced empty output for: %s', chm_path)
        return False
    except FileNotFoundError:
        logger.debug('hh.exe not found (not Windows?)')
        return False
    except subprocess.TimeoutExpired:
        logger.warning('hh.exe timed out: %s', chm_path)
        return False
    except Exception as e:
        logger.debug('hh.exe decompile failed: %s', e)
        return False


def _extract_chm_7z(chm_path: str, output_dir: str) -> bool:
    """Use external archiver to extract CHM."""
    safe_chm = _sanitize_path(chm_path)
    safe_output = _sanitize_path(output_dir)
    Path(safe_output).mkdir(parents=True, exist_ok=True)

    candidates = []

    # 7z (standalone or p7zip)
    if shutil.which("7z"):
        candidates.append(("7z", ["7z", "x", "-y", f"-o{safe_output}", safe_chm]))
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for base in [pf, pf86]:
            p = Path(base) / "7-Zip" / "7z.exe"
            if p.exists():
                candidates.append(("7-Zip", [str(p), "x", "-y", f"-o{safe_output}", safe_chm]))
        for base in [pf, pf86]:
            p = Path(base) / "WinRAR" / "WinRAR.exe"
            if p.exists():
                candidates.append(("WinRAR", [str(p), "x", "-y", safe_chm, safe_output]))
        for base in [pf, pf86]:
            p = Path(base) / "Bandizip" / "bandizip.exe"
            if p.exists():
                candidates.append(("Bandizip", [str(p), "x", "-y", "-o:" + safe_output, safe_chm]))

    if not candidates:
        logger.debug("No external archiver found")
        return False

    for name, cmd in candidates:
        try:
            logger.info("尝试使用 %s 解压...", name)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0 and Path(safe_output).exists() and any(Path(safe_output).iterdir()):
                return True
            logger.debug("%s returned %d", name, result.returncode)
        except Exception as e:
            logger.debug("%s failed: %s", name, e)

    return False


def _extract_chm_pychm(chm_path: str, output_dir: str) -> bool:
    """Pure-Python CHM extraction using pychm library.

    This is the last-resort fallback when neither hh.exe nor 7z is available.
    Requires: pip install pychm
    """
    try:
        from chm.chm import CHMFile as _CHMFile  # type: ignore
    except ImportError:
        logger.debug("pychm not installed, skipping")
        return False

    try:
        safe_chm = _sanitize_path(chm_path)
        safe_output = _sanitize_path(output_dir)
        Path(safe_output).mkdir(parents=True, exist_ok=True)

        chm = _CHMFile(safe_chm)

        extracted = 0

        def _visitor(chm_file, ui, context, entry):
            nonlocal extracted
            path = entry.path
            # Skip directories and special CHM internal files
            if not path or path.endswith("/") or path.startswith("/#") or path.startswith("::"):
                return True

            # Clean leading slashes/backslashes
            clean = path.lstrip("/\\")
            if not clean:
                return True

            out_path = Path(safe_output) / clean
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                data = chm_file.retrieve_file(entry)
                if data:
                    out_path.write_bytes(data)
                    extracted += 1
            except Exception as e:
                logger.debug("pychm failed to extract %s: %s", path, e)

            return True

        chm.chm.chm_resolve_object("/")
        chm.chm.chm_walk(_visitor)

        if extracted > 0:
            logger.info("pychm extracted %d files from CHM", extracted)
            return True

        logger.warning("pychm extracted 0 files from: %s", chm_path)
        return False

    except Exception as e:
        logger.debug("pychm extraction failed: %s", e)
        return False


def _extract_chm(chm_path: str, output_dir: str) -> bool:
    """
    解压 CHM 文件，按优先级尝试多种工具：

    1. hh.exe -decompile（Windows 自带，无需安装）
    2. 7z（Linux 首选，Windows 上需安装 7-Zip）

    Args:
        chm_path: CHM 文件路径
        output_dir: 输出目录

    Returns:
        是否成功
    """
    # Windows: prefer built-in hh.exe
    if sys.platform == "win32":
        logger.info("尝试使用 hh.exe 反编译 CHM...")
        if _extract_chm_hh(chm_path, output_dir):
            logger.info("hh.exe 反编译成功")
            return True
        logger.warning("hh.exe 失败，回退到 7z...")

    # Try 7z (works everywhere if installed)
    logger.info("尝试使用 7z 解压 CHM...")
    if _extract_chm_7z(chm_path, output_dir):
        logger.info("7z 解压成功")
        return True

    # Last resort: Python-native CHM extraction via pychm
    logger.info("尝试使用 pychm 纯 Python 解压 CHM...")
    if _extract_chm_pychm(chm_path, output_dir):
        logger.info("pychm 解压成功")
        return True

    logger.error(
        "CHM 解压失败：所有方法均不可用。\n"
        "请尝试以下任一方案：\n"
        "  1. 安装 7-Zip (https://7-zip.org)\n"
        "  2. pip install pychm\n"
        "  3. 确认 hh.exe 未被安全策略阻止"
    )
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
        logger.debug("Failed to detect charset from HTML meta tag, using gb18030")

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
        logger.debug("BeautifulSoup extraction failed, falling back to regex")
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
    从文件路径提取位置标识

    对于 CHM，没有真正的页码，用文件路径作为位置标识

    Args:
        filepath: 文件路径
        base_dir: 基础目录

    Returns:
        位置标识
    """
    try:
        relative = filepath.relative_to(base_dir)
        return str(relative)
    except ValueError:
        return None


def _extract_location_tag(text: str) -> str | None:
    """
    从文本中提取 [位置: xxx] 标记的值。
    使用括号深度计数以正确处理 location 中的嵌套方括号。
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


def _extract_chapter_title(html_content: str) -> str | None:
    """从 HTML 中提取章节标题。

    优先级：<title> > <h1> > <h2> > <h3>
    """
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        if soup.title and soup.title.string:
            t = soup.title.string.strip()
            if t:
                return t[:200]
        for tag_name in ("h1", "h2", "h3"):
            tag = soup.find(tag_name)
            if tag:
                t = tag.get_text(strip=True)
                if t:
                    return t[:200]
    except Exception:
        logger.debug("Failed to extract chapter title from HTML")
    return None


def _is_system_dir(name: str) -> bool:
    """判断是否为 CHM 内部系统目录（非内容目录）。"""
    system_prefixes = ("$", "img", "images", "css", "style", "script", "js")
    return any(name.lower().startswith(p) for p in system_prefixes)


def _process_html_file(
    html_file: Path,
    base_dir: Path,
) -> tuple[str | None, str, str | None]:
    """解析单个 HTML 文件。

    Returns:
        (location, extracted_text, chapter_title)
    """
    with open(html_file, "rb") as f:
        raw_content = f.read()

    encoding = _detect_encoding(raw_content)
    html_content = raw_content.decode(encoding, errors="replace")

    text = _extract_text_from_html(html_content)
    location = _extract_page_hint(html_file, base_dir)
    chapter_title = _extract_chapter_title(html_content)

    return location, text, chapter_title


def parse_chm(
    chm_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    解析 CHM 文件：解压 + 层级识别 + HTML提取 + 分块

    层级策略：
    - 一级子目录 → "文档"（parent），目录名即文档标题
    - 每个 HTML 文件 → "章节"（chapter），从 <title> 或 <h1> 提取标题
    - 根目录下的 HTML → 扁平处理，无 parent

    每个 chunk 的 text 前会加上层级标记：
      [文档: 建筑抗震设计规范[附条文说明]]
      [章节: 5.2 场地抗震性能评价]
      [位置: 建筑抗震设计规范/005.html]
      实际内容...

    Args:
        chm_path: CHM 文件路径
        chunk_size: 目标分块大小（字符数）
        chunk_overlap: 分块重叠大小（字符数）

    Returns:
        分块列表
    """
    chm_p = Path(chm_path)
    extract_dir = chm_p.parent / f"{chm_p.stem}_extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    try:
        if not _extract_chm(chm_path, str(extract_dir)):
            raise RuntimeError(f"无法解压 CHM 文件: {chm_path}")

        # ---- 阶段 1：识别层级结构 ----
        subdirs: list[Path] = []
        root_htmls: list[Path] = []

        for child in sorted(extract_dir.iterdir()):
            if child.is_dir() and not _is_system_dir(child.name):
                subdirs.append(child)
            elif child.is_file() and child.suffix.lower() in (".htm", ".html"):
                root_htmls.append(child)

        # ---- 阶段 2：按文档分组提取 ----
        # 每个 section: (parent_title, chapter_title, location, text)
        sections: list[tuple[str | None, str | None, str | None, str]] = []

        for subdir in subdirs:
            parent_title = subdir.name
            html_files = _find_html_files(str(subdir))

            if not html_files:
                continue

            for html_file in html_files:
                try:
                    location, text, chapter_title = _process_html_file(
                        html_file, extract_dir
                    )
                    if text.strip():
                        sections.append((parent_title, chapter_title, location, text))
                except Exception as e:
                    logger.warning("Failed to parse HTML %s: %s", html_file, e)
                    continue

        for html_file in root_htmls:
            try:
                location, text, chapter_title = _process_html_file(
                    html_file, extract_dir
                )
                if text.strip():
                    sections.append((None, chapter_title, location, text))
            except Exception as e:
                logger.warning("Failed to parse HTML %s: %s", html_file, e)
                continue

        if not sections:
            logger.info("No valid text extracted from CHM: %s", chm_path)
            return []

        # ---- 阶段 3：按章节分块（保留层级标记） ----
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        )

        result: list[dict] = []
        chunk_id = 0

        for parent_title, chapter_title, location, text in sections:
            # 构建层级标记前缀
            header_parts: list[str] = []
            if parent_title:
                header_parts.append(f"[文档: {parent_title}]")
            if chapter_title:
                header_parts.append(f"[章节: {chapter_title}]")
            if location:
                header_parts.append(f"[位置: {location}]")

            header = "\n".join(header_parts)

            # 对章节文本分块
            chunks = splitter.split_text(text)

            for ci, chunk_text in enumerate(chunks):
                if ci == 0:
                    full_text = f"{header}\n{chunk_text}" if header else chunk_text
                else:
                    loc_tag = f"[位置: {location}]" if location else ""
                    full_text = f"{loc_tag}\n{chunk_text}" if loc_tag else chunk_text

                result.append(
                    {
                        "chunk_id": chunk_id,
                        "text": full_text,
                        "page": None,
                        "location": location,
                        "parent_title": parent_title,
                        "chapter": chapter_title,
                    }
                )
                chunk_id += 1

        logger.info(
            "%s: %d docs, %d sections, %d chunks",
            chm_p.name,
            len(subdirs),
            len(sections),
            len(result),
        )
        return result

    finally:
        pass  # 解压目录保留，用于后续 CHM HTML 查看
