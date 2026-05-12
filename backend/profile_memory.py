"""Profile memory usage during document processing.

Strategy:
1. Start backend on port 8765
2. Upload files one by one (serial first, then concurrent)
3. Record RSS before/after each file, and peak RSS during processing
4. Output a CSV with results
"""

import asyncio
import csv
import json
import os
import time
from pathlib import Path

import psutil
import httpx

API = "http://127.0.0.1:8765"
TEST_DIR = Path("/home/cbr/下载/结构技术标准")
OUTPUT_CSV = Path("~/programming/engineer_assistant/backend/profile_results.csv").expanduser()


async def wait_for_backend(client: httpx.AsyncClient):
    for _ in range(60):
        try:
            r = await client.get(f"{API}/documents")
            if r.status_code == 200:
                print("Backend ready")
                return
        except Exception:
            pass
        await asyncio.sleep(2)
    raise RuntimeError("Backend did not start")


async def upload_file(client: httpx.AsyncClient, filepath: Path) -> dict:
    r = await client.post(f"{API}/documents/upload", json={"file_path": str(filepath)})
    if r.status_code not in (200, 409):
        print(f"  Upload failed: {r.status_code} {r.text[:200]}")
    return r.json()


async def wait_until_ready(client: httpx.AsyncClient, timeout: int = 1800):
    """Wait until all documents are ready/error."""
    start = time.time()
    while time.time() - start < timeout:
        r = await client.get(f"{API}/documents")
        docs = r.json()["documents"]
        active = [d for d in docs if d["status"] in ("pending", "processing", "queued")]
        if not active:
            return docs
        await asyncio.sleep(1)
    raise RuntimeError("Timeout waiting for documents")


async def clear_all(client: httpx.AsyncClient):
    r = await client.get(f"{API}/documents")
    for doc in r.json()["documents"]:
        await client.delete(f"{API}/documents/{doc['id']}")
    print("Cleared all documents")


def get_rss_mb() -> float:
    """Get current process RSS in MB (find the uvicorn/python backend process)."""
    # Find the backend process
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "uvicorn" in cmdline or ("python" in cmdline.lower() and "8765" in cmdline):
                return proc.info["memory_info"].rss / (1024 ** 2)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return 0.0


async def profile_serial():
    """Upload files one at a time, measure each."""
    async with httpx.AsyncClient(timeout=300) as client:
        await wait_for_backend(client)
        await clear_all(client)

        files = sorted(TEST_DIR.iterdir(), key=lambda f: f.stat().st_size)
        results = []

        for i, fp in enumerate(files):
            if not fp.is_file():
                continue
            fsize_mb = fp.stat().st_size / (1024 ** 2)
            ftype = fp.suffix.lower().lstrip(".")
            print(f"\n[{i+1}/{len(list(files))}] {fp.name} ({fsize_mb:.1f} MB, {ftype})")

            rss_before = get_rss_mb()
            print(f"  RSS before: {rss_before:.0f} MB")

            doc = await upload_file(client, fp)
            if "id" not in doc:
                print(f"  Skipped (status: {doc.get('detail', 'unknown')})")
                continue

            # Poll until this doc finishes
            t0 = time.time()
            peak_rss = rss_before
            while True:
                await asyncio.sleep(2)
                rss_now = get_rss_mb()
                peak_rss = max(peak_rss, rss_now)
                r = await client.get(f"{API}/documents/{doc['id']}")
                status = r.json()["status"]
                elapsed = time.time() - t0
                if status in ("ready", "error"):
                    break
                if elapsed > 600:
                    print(f"  Timeout after {elapsed:.0f}s")
                    break

            rss_after = get_rss_mb()
            delta = rss_after - rss_before
            peak_delta = peak_rss - rss_before
            elapsed = time.time() - t0
            chunks = r.json().get("chunk_count")

            print(f"  Status: {status}, Chunks: {chunks}, Time: {elapsed:.1f}s")
            print(f"  RSS after: {rss_after:.0f} MB (delta: {delta:+.0f} MB, peak delta: {peak_delta:+.0f} MB)")

            results.append({
                "filename": fp.name,
                "type": ftype,
                "size_mb": round(fsize_mb, 1),
                "chunks": chunks,
                "status": status,
                "time_s": round(elapsed, 1),
                "rss_before_mb": round(rss_before, 0),
                "rss_after_mb": round(rss_after, 0),
                "rss_delta_mb": round(delta, 0),
                "rss_peak_mb": round(peak_rss, 0),
                "rss_peak_delta_mb": round(peak_delta, 0),
            })

            # Delete after measuring so next file starts clean
            await client.delete(f"{API}/documents/{doc['id']}")
            await asyncio.sleep(1)  # let GC settle

        return results


async def profile_concurrent_2():
    """Upload 2 files at once and measure."""
    async with httpx.AsyncClient(timeout=300) as client:
        await wait_for_backend(client)
        await clear_all(client)

        # Pick one large CHM + one large PDF
        files = sorted(TEST_DIR.iterdir(), key=lambda f: f.stat().st_size, reverse=True)
        chm = next(f for f in files if f.suffix.lower() == ".chm")
        pdf = next(f for f in files if f.suffix.lower() == ".pdf")
        pair = [chm, pdf]

        print(f"\n=== Concurrent test: {chm.name} + {pdf.name} ===")
        for f in pair:
            print(f"  {f.name} ({f.stat().st_size / (1024**2):.1f} MB)")

        rss_before = get_rss_mb()
        print(f"RSS before: {rss_before:.0f} MB")

        # Upload both simultaneously
        docs = await asyncio.gather(*[upload_file(client, f) for f in pair])

        t0 = time.time()
        peak_rss = rss_before
        while True:
            await asyncio.sleep(2)
            rss_now = get_rss_mb()
            peak_rss = max(peak_rss, rss_now)
            r = await client.get(f"{API}/documents")
            statuses = {d["name"]: d["status"] for d in r.json()["documents"]}
            if all(s in ("ready", "error") for s in statuses.values()):
                break
            if time.time() - t0 > 1200:
                break

        elapsed = time.time() - t0
        rss_after = get_rss_mb()
        peak_delta = peak_rss - rss_before
        print(f"Done in {elapsed:.1f}s")
        print(f"RSS after: {rss_after:.0f} MB, peak: {peak_rss:.0f} MB (peak delta: {peak_delta:+.0f} MB)")
        for d in r.json()["documents"]:
            print(f"  {d['name']}: {d['status']} ({d.get('chunk_count')} chunks)")

        await clear_all(client)

        return {
            "test": "concurrent_2",
            "files": [f.name for f in pair],
            "time_s": round(elapsed, 1),
            "rss_before_mb": round(rss_before, 0),
            "rss_after_mb": round(rss_after, 0),
            "rss_peak_mb": round(peak_rss, 0),
            "rss_peak_delta_mb": round(peak_delta, 0),
        }


async def main():
    print("=" * 60)
    print("Phase 1: Serial profiling (one file at a time)")
    print("=" * 60)
    serial_results = await profile_serial()

    # Write CSV
    if serial_results:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=serial_results[0].keys())
            w.writeheader()
            w.writerows(serial_results)
        print(f"\nSerial results saved to {OUTPUT_CSV}")

    print("\n" + "=" * 60)
    print("Phase 2: Concurrent profiling (2 files)")
    print("=" * 60)
    conc_result = await profile_concurrent_2()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if serial_results:
        deltas = [r["rss_peak_delta_mb"] for r in serial_results if r["rss_peak_delta_mb"] > 0]
        if deltas:
            print(f"Peak memory per file (serial): min={min(deltas):.0f} MB, max={max(deltas):.0f} MB, avg={sum(deltas)/len(deltas):.0f} MB")
    print(f"Concurrent peak delta: {conc_result['rss_peak_delta_mb']:.0f} MB")


if __name__ == "__main__":
    asyncio.run(main())
