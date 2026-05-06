"""
Common paths for the backend.
Handles both development and PyInstaller frozen environments.
"""

import sys
from pathlib import Path


def _resolve_backend_dir() -> Path:
    """Resolve the backend root directory.

    - Development: parent of src/ (where __file__ lives)
    - PyInstaller: directory containing the exe
    """
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: use exe directory as backend root
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


# Backend root directory
BACKEND_DIR = _resolve_backend_dir()

# Data storage
DATA_DIR = BACKEND_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
VECTOR_DIR = DATA_DIR / "vectors"
METADATA_FILE = DATA_DIR / "documents.json"

# Schema version (increment when vector schema changes)
SCHEMA_VERSION_FILE = DATA_DIR / "schema_version.txt"
CURRENT_SCHEMA_VERSION = 4  # v4: added status/error to Meeting


def ensure_dirs() -> None:
    """Create data directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)


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
