"""Entry point for PyInstaller bundling.
Uses absolute imports so PyInstaller can resolve the package structure."""
import sys
import os

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.main import app
import uvicorn

if __name__ == "__main__":
    # Required for PyInstaller + multiprocessing spawn
    import multiprocessing as mp
    mp.freeze_support()

    # Filter out multiprocessing-spawn arguments so argparse doesn't choke
    import sys
    sys.argv = [sys.argv[0]] + [
        a for a in sys.argv[1:]
        if not a.startswith("--multiprocessing-fork")
        and "parent_pid" not in a
        and "pipe_handle" not in a
    ]

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    port = args.port or int(os.environ.get("FORGE_PORT", 8765))
    uvicorn.run(app, host="127.0.0.1", port=port)
