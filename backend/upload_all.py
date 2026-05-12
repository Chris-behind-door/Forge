"""Simple upload script: upload all files, serial mode (max_concurrent=1)."""
import asyncio, glob, httpx, json, sys

API = "http://127.0.0.1:8765"
DIR = "/home/cbr/下载/结构技术标准"

async def main():
    files = sorted(glob.glob(f"{DIR}/*.*"))
    print(f"Found {len(files)} files")
    
    async with httpx.AsyncClient(timeout=300) as client:
        # Wait for backend
        for _ in range(30):
            try:
                r = await client.get(f"{API}/documents")
                if r.status_code == 200:
                    break
            except:
                pass
            await asyncio.sleep(2)
        
        # Clear existing
        docs = (await client.get(f"{API}/documents")).json()["documents"]
        for d in docs:
            await client.delete(f"{API}/documents/{d['id']}")
        print(f"Cleared {len(docs)} existing docs")
        
        # Upload all
        for i, fp in enumerate(files):
            r = await client.post(f"{API}/documents/upload", json={"file_path": fp})
            status = r.status_code
            name = fp.split("/")[-1]
            if status == 200:
                print(f"[{i+1}/{len(files)}] {name} -> queued")
            elif status == 409:
                print(f"[{i+1}/{len(files)}] {name} -> duplicate, skipped")
            else:
                print(f"[{i+1}/{len(files)}] {name} -> ERROR {status}: {r.text[:100]}")
        
        # Wait for all to finish
        print("\nAll uploaded, waiting for processing...")
        for attempt in range(3600):
            await asyncio.sleep(5)
            r = await client.get(f"{API}/documents")
            docs = r.json()["documents"]
            active = [d for d in docs if d["status"] in ("pending", "processing", "queued")]
            ready = sum(1 for d in docs if d["status"] == "ready")
            errors = sum(1 for d in docs if d["status"] == "error")
            if attempt % 12 == 0:  # every 60s
                print(f"  [{attempt*5}s] ready={ready}, active={len(active)}, errors={errors}")
            if not active:
                print(f"\nDone! ready={ready}, errors={errors}")
                break
        
        # Print summary
        r = await client.get(f"{API}/documents")
        docs = r.json()["documents"]
        for d in sorted(docs, key=lambda x: x["status"]):
            print(f"  {d['name'][:50]:50s} {d['status']:8s} {d.get('chunk_count') or '-':>6s} chunks")

asyncio.run(main())
