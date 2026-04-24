"""Generic JSON file read/write utilities."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def ensure_dir(path: Path) -> None:
    """Create directory (and parents) if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any = None) -> Any:
    """Load JSON from *path*. Returns *default* on missing / corrupt file."""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load JSON from %s: %s", path, e)
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
