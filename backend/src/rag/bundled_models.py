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

    # Clean up any incomplete extraction.
    # Be conservative: don't delete if another process might be extracting.
    if target_dir.exists():
        if _find_model_file(target_dir, model_file):
            logger.info("模型已由另一个进程解压完成: %s", target_dir)
            return _find_model_file(target_dir, model_file)
        # Only clean up if the zip exists AND the target dir is truly empty/stale
        # (skip cleanup to avoid deleting a concurrent extraction)

    # Find zip file
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / zip_name)
        candidates.append(exe_dir / "data" / zip_name)
        # Tauri resource dir on Windows: <resource_dir>/backend-bundle/
        # The exe may be inside backend-bundle/ already, but also check parent
        candidates.append(exe_dir.parent / zip_name)
        candidates.append(exe_dir.parent / "data" / zip_name)
    else:
        candidates.append(Path(__file__).parent.parent.parent / zip_name)
        # Embedded Python mode: backend-bundle/backend/src/rag/ -> backend-bundle/
        candidates.append(Path(__file__).parent.parent.parent.parent / zip_name)

    logger.info("[DEBUG] Looking for zip '%s', __file__=%s", zip_name, Path(__file__).resolve())
    logger.info("[DEBUG] candidates:")
    for c in candidates:
        logger.info("[DEBUG]   %s -> exists=%s", c, c.exists())

    for zip_path in candidates:
        if not zip_path.exists():
            continue

        for attempt in range(2):  # up to 2 attempts (initial + 1 retry)
            logger.info("发现离线模型包: %s，正在解压...%s", zip_path,
                        f" (重试 {attempt})" if attempt > 0 else "")
            logger.info("[DEBUG] zip size = %s bytes", zip_path.stat().st_size)
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    top_dirs: set[str] = set()
                    for info in zf.infolist():
                        parts = Path(info.filename).parts
                        if parts:
                            top_dirs.add(parts[0])

                    should_strip = len(top_dirs) == 1
                    if should_strip:
                        logger.info("zip顶层: %s, 将strip", next(iter(top_dirs)))
                    else:
                        logger.info("zip有多个顶层目录，不strip")

                    for info in zf.infolist():
                        parts = Path(info.filename).parts
                        if not parts:
                            continue
                        rel = str(Path(*parts[1:])) if should_strip and len(parts) > 1 else info.filename
                        if not rel:
                            continue
                        dest = target_dir / rel
                        if info.is_dir():
                            dest.mkdir(parents=True, exist_ok=True)
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(info) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                break  # success, exit retry loop
            except OSError as e:
                if attempt == 0:
                    logger.warning("解压冲突 (%s)，1秒后重试...", e)
                    import time
                    time.sleep(1)
                else:
                    raise

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

    logger.info("未找到离线模型包: %s", zip_name)
    return None


def _find_model_file(directory: Path, model_file: str) -> Path | None:
    """Find model_file in directory (may be nested in snapshots/ or a wrapper dir)."""
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
    # Double-nested (old extraction without strip): wrapper/snapshots/<hash>/model_file
    for subdir in directory.iterdir():
        if subdir.is_dir():
            inner_snapshots = subdir / "snapshots"
            if inner_snapshots.exists():
                for snap in inner_snapshots.iterdir():
                    if snap.is_dir() and (snap / model_file).is_file():
                        return snap / model_file
    return None
