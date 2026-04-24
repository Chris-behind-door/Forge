"""
Common paths for the backend.
"""

from pathlib import Path

# Backend root directory
BACKEND_DIR = Path(__file__).parent.parent.parent

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
