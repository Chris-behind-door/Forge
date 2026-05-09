"""
Bundled model extraction utilities.

Shared by embedding and reranker modules for offline model loading.
"""

import logging
import shutil
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_bundled_zip(
    zip_name: str,
    cache_dir: Path,
    model_dir_name: str,
    model_file: str = "model_optimized.onnx",
) -> Path | None:
    """Extract a bundled model zip to cache_dir/model_dir_name.

    Looks for zip_name next to the exe (PyInstaller) or in the project root.
    Smart strip: removes a single wrapper directory if present.

    Args:
        zip_name: Name of the zip file (e.g. "embedding-model.zip").
        cache_dir: Where to extract to.
        model_dir_name: Target directory name under cache_dir
            (e.g. "models--Qdrant--bge-small-zh-v1.5").
        model_file: A file that must exist to confirm valid extraction.

    Returns:
        Path to the directory containing model_file, or None.
    """
    target_dir = cache_dir / model_dir_name
    logger.info("[DEBUG] target_dir = %s", target_dir)
    logger.info("[DEBUG] target_dir exists = %s", target_dir.exists())

    # Check if already extracted and valid
    existing = _find_model_file(target_dir, model_file)
    if existing:
        logger.info("模型已存在: %s", existing.parent)
        return existing.parent
    else:
        logger.info("[DEBUG] _find_model_file returned None for %s in %s", model_file, target_dir)
        if target_dir.exists():
            # List what's actually there
            logger.info("[DEBUG] target_dir contents:")
            for p in sorted(target_dir.rglob("*"))[:30]:
                size = p.stat().st_size if p.is_file() else "DIR"
                logger.info("[DEBUG]   %s (%s)", p.relative_to(target_dir), size)

    # Clean up any incomplete extraction
    if target_dir.exists():
        logger.info("清理不完整目录: %s", target_dir)
        shutil.rmtree(target_dir, ignore_errors=True)

    # Find zip file
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / zip_name)
        candidates.append(exe_dir / "data" / zip_name)
    else:
        candidates.append(Path(__file__).parent.parent.parent / zip_name)

    logger.info("[DEBUG] Looking for zip '%s', candidates:", zip_name)
    for c in candidates:
        logger.info("[DEBUG]   %s -> exists=%s", c, c.exists())

    for zip_path in candidates:
        if not zip_path.exists():
            continue

        logger.info("发现离线模型包: %s，正在解压...", zip_path)
        logger.info("[DEBUG] zip size = %s bytes", zip_path.stat().st_size)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Detect if zip has a single top-level wrapper dir
                top_dirs: set[str] = set()
                for info in zf.infolist():
                    parts = Path(info.filename).parts
                    if parts:
                        top_dirs.add(parts[0])

                should_strip = False
                if len(top_dirs) == 1:
                    top_name = next(iter(top_dirs))
                    should_strip = True
                    logger.info("zip顶层: %s, 将strip", top_name)
                else:
                    logger.info("zip有多个顶层目录，不strip")

                for info in zf.infolist():
                    parts = Path(info.filename).parts
                    if not parts:
                        continue
                    if should_strip and len(parts) > 1:
                        rel = str(Path(*parts[1:]))
                    else:
                        rel = info.filename
                    if not rel:
                        continue
                    dest = target_dir / rel
                    if info.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            logger.info("离线模型包解压完成")
            logger.info("[DEBUG] Post-extract target_dir contents:")
            for p in sorted(target_dir.rglob("*"))[:30]:
                size = p.stat().st_size if p.is_file() else "DIR"
                logger.info("[DEBUG]   %s (%s)", p.relative_to(target_dir), size)

            found = _find_model_file(target_dir, model_file)
            logger.info("[DEBUG] _find_model_file post-extract: %s", found)
            if found:
                logger.info("模型目录: %s", found.parent)
                logger.info(
                    "%s: 存在=%s, 大小=%s",
                    model_file, found.exists(),
                    found.stat().st_size if found.exists() else "N/A",
                )
                return found.parent

            logger.warning("解压完成但未找到 %s", model_file)

        except Exception as e:
            logger.warning("离线模型包解压失败: %s", e)

    logger.info("未找到离线模型包: %s", zip_name)
    return None


def _find_model_file(directory: Path, model_file: str) -> Path | None:
    """Find model_file in directory (may be nested in snapshots/)."""
    if not directory.exists():
        return None
    # Direct file
    if (directory / model_file).is_file():
        return directory / model_file
    # HF cache format: snapshots/<hash>/model_file
    snapshots = directory / "snapshots"
    if snapshots.exists():
        for snap in snapshots.iterdir():
            if snap.is_dir() and (snap / model_file).is_file():
                return snap / model_file
    return None
