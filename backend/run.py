"""Entry point for PyInstaller bundling.
Uses absolute imports so PyInstaller can resolve the package structure."""
import sys
import os

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
