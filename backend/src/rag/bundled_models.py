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
    """Extract a bundled model zip to cache_dir.

    Looks for zip_name next to the exe (PyInstaller) or in the project root.
    Smart strip: removes a single wrapper directory if present.

    Args:
        zip_name: Name of the zip file (e.g. "embedding-model.zip").
        cache_dir: Where to extract to.
        model_dir_name: Expected directory name after extraction
            (e.g. "models--Qdrant--bge-small-zh-v1.5").
        model_file: A file that must exist in the snapshot to confirm valid extraction.

    Returns:
        Path to the snapshot directory containing model_file, or None.
    """
    # Check if already extracted and valid
    existing = _find_snapshot(cache_dir, model_dir_name, model_file)
    if existing:
        logger.info("模型已存在: %s", existing)
        return existing

    # Clean up any incomplete extraction
    partial = cache_dir / model_dir_name
    if partial.exists():
        logger.info("清理不完整目录: %s", partial)
        shutil.rmtree(partial, ignore_errors=True)

    # Find zip file
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / zip_name)
        candidates.append(exe_dir / "data" / zip_name)
    else:
        candidates.append(Path(__file__).parent.parent.parent / zip_name)

    for zip_path in candidates:
        if not zip_path.exists():
            continue

        logger.info("发现离线模型包: %s，正在解压...", zip_path)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
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
                    # Don't strip if the top dir IS the model dir
                    if not top_name.startswith("models--"):
                        should_strip = True

                logger.info("zip顶层: %s, strip=%s", top_dirs, should_strip)

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
                    target = cache_dir / rel
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            logger.info("离线模型包解压完成")

            snapshot = _find_snapshot(cache_dir, model_dir_name, model_file)
            if snapshot:
                logger.info("模型快照: %s", snapshot)
                onnx = snapshot / model_file
                logger.info(
                    "%s: 存在=%s, 大小=%s",
                    model_file, onnx.exists(),
                    onnx.stat().st_size if onnx.exists() else "N/A",
                )
                return snapshot

            logger.warning("解压完成但未找到 %s/%s", model_dir_name, model_file)

        except Exception as e:
            logger.warning("离线模型包解压失败: %s", e)

    logger.info("未找到离线模型包: %s", zip_name)
    return None


def _find_snapshot(
    cache_dir: Path, model_dir_name: str, model_file: str
) -> Path | None:
    """Find a valid snapshot directory containing model_file."""
    snapshots_root = cache_dir / model_dir_name / "snapshots"
    if not snapshots_root.exists():
        return None
    for snap in snapshots_root.iterdir():
        if snap.is_dir() and (snap / model_file).exists():
            return snap
    return None
