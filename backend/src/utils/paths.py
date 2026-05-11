"""
Common paths for the backend.
Handles both development and PyInstaller frozen environments.

Dev mode:    <project>/backend/data/
Prod mode:   XDG standard (~/.local/share/engineer-assistant/ on Linux,
             %APPDATA%/engineer-assistant/ on Windows)
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "engineer-assistant"


def _resolve_backend_dir() -> Path:
    """Resolve the backend root directory (for dev mode, where source lives)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: exe directory (only used for reference)
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def _resolve_data_dir() -> Path:
    """Resolve the data storage directory.

    - Development (not frozen): <project>/backend/data/
    - Production (PyInstaller):
        - Linux/macOS: $XDG_DATA_HOME/engineer-assistant/ (default ~/.local/share/)
        - Windows:     %APPDATA%/engineer-assistant/
    - Can be overridden with ENGINEER_ASSISTANT_DATA env var.
    """
    # Allow explicit override
    env_data = os.environ.get("ENGINEER_ASSISTANT_DATA")
    if env_data:
        return Path(env_data)

    if getattr(sys, "frozen", False):
        # Production: use platform-specific data directory
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            # XDG_DATA_HOME default: ~/.local/share
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / APP_NAME

    # Development: keep data in project tree
    return _resolve_backend_dir() / "data"


BACKEND_DIR = _resolve_backend_dir()
DATA_DIR = _resolve_data_dir()
UPLOADS_DIR = DATA_DIR / "uploads"
METADATA_FILE = DATA_DIR / "documents.json"

# LanceDB vectors: use exe-adjacent path on Windows to avoid
# lance Rust bug that drops drive letter from file:// URLs
# (C:\Users\... → file:///Data/Users/... missing the C:)
if getattr(sys, "frozen", False) and sys.platform == "win32":
    _LANCE_DIR = BACKEND_DIR / "data" / "vectors"
else:
    _LANCE_DIR = DATA_DIR / "vectors"
VECTOR_DIR = _LANCE_DIR

# Schema version (increment when vector schema changes)
SCHEMA_VERSION_FILE = DATA_DIR / "schema_version.txt"
CURRENT_SCHEMA_VERSION = 4  # v4: added status/error to Meeting


def ensure_dirs() -> None:
    """Create data directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)


def migrate_from_legacy_path() -> None:
    """One-time migration: move data from exe-adjacent 'data/' to XDG path.

    Only runs in frozen (PyInstaller) mode when the new data dir is empty
    but the old data dir next to the executable has content.
    """
    if not getattr(sys, "frozen", False):
        return

    legacy_dir = BACKEND_DIR / "data"
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return

    # Skip if new data dir already has content
    if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
        return

    print(f"[Forge] Migrating data from {legacy_dir} -> {DATA_DIR}")
    ensure_dirs()

    for item in legacy_dir.iterdir():
        dest = DATA_DIR / item.name
        if dest.exists():
            continue
        try:
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                shutil.copytree(item, dest)
        except OSError as e:
            print(f"[Forge] Warning: failed to migrate {item.name}: {e}")

    print("[Forge] Migration complete.")


def get_schema_version() -> int:
    """Get current schema version from file."""
    if SCHEMA_VERSION_FILE.exists():
        try:
            return int(SCHEMA_VERSION_FILE.read_text().strip())
        except (ValueError, OSError):
            return 0
    return 0


def set_schema_version(version: int) -> None:
    """Save schema version to file."""
    ensure_dirs()
    SCHEMA_VERSION_FILE.write_text(str(version))
