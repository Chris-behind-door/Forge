#!/usr/bin/env pwsh
# build-local.ps1 — 一键本地打包 Engineering Assistant (Windows)
#
# 前置要求（一次性安装）：
#   1. Node.js 20+   → https://nodejs.org
#   2. Rust + MSVC    → https://rustup.rs
#   3. Python 3.11+   → https://python.org（安装时勾选 "Add to PATH"）
#   4. 7-Zip          → https://7-zip.org
#   5. Visual Studio Build Tools（C++ 桌面开发工作负载）
#
# 模型文件：
#   在 Linux 宿主机上预下载，放入共享文件夹，通过 -ModelDir 参数指定。
#   需要的文件：
#     embedding-model.zip   （Qdrant/bge-small-zh-v1.5 完整模型）
#     reranker-model.zip    （onnx-community/bge-reranker-v2-m3-ONNX 的
#                            model_quantized.onnx + tokenizer.json）
#
# 用法：
#   .\build-local.ps1                    # 模型在当前目录的 model-cache 子目录
#   .\build-local.ps1 -ModelDir Z:\models  # 模型在共享文件夹

param(
    [string]$ModelDir = ".\model-cache",
    [switch]$SkipRust = $false
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

# ── 0. 检查工具 ──────────────────────────────────────────────
Write-Step "检查环境"

$tools = @("node", "rustc", "python", "pip")
foreach ($t in $tools) {
    $v = & $t --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ❌ $t 未安装" -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✅ $t $v"
}

if (-not (Test-Path "C:\Program Files\7-Zip\7z.exe")) {
    Write-Host "  ❌ 7-Zip 未安装在默认路径" -ForegroundColor Red
    exit 1
}
Write-Host "  ✅ 7-Zip"

# ── 1. 准备 bundled tools (7z) ───────────────────────────────
Write-Step "准备 7-Zip"

New-Item -ItemType Directory -Force -Path backend\bundled_tools | Out-Null
Copy-Item "C:\Program Files\7-Zip\7z.exe" backend\bundled_tools/ -Force
Copy-Item "C:\Program Files\7-Zip\7z.dll" backend\bundled_tools/ -Force
Write-Host "  ✅ 已复制到 backend/bundled_tools/"

# ── 2. 安装后端依赖 ─────────────────────────────────────────
Write-Step "安装后端 Python 依赖"

Push-Location backend
pip install uv
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
# 不再需要 torch！
uv pip install pyinstaller
# Replace CPU-only onnxruntime with DirectML variant (works with any GPU on Windows)
uv pip install onnxruntime-directml
Pop-Location

# ── 3. 准备模型文件 ─────────────────────────────────────────
Write-Step "准备模型文件"

$embZip = Join-Path $ModelDir "embedding-model.zip"
$rerZip = Join-Path $ModelDir "reranker-model.zip"

if ((Test-Path $embZip) -and (Test-Path $rerZip)) {
    Write-Host "  从 $ModelDir 复制预下载模型..."
    Copy-Item $embZip backend/embedding-model.zip -Force
    Copy-Item $rerZip backend/reranker-model.zip -Force
    Write-Host "  ✅ 模型已复制"
} else {
    Write-Host "  ⚠ 未找到预下载模型，尝试从 hf-mirror.com 下载..." -ForegroundColor Yellow
    Write-Host "    需要: $embZip"
    Write-Host "    需要: $rerZip"

    Push-Location backend
    .\.venv\Scripts\Activate.ps1
    $env:HF_ENDPOINT = "https://hf-mirror.com"

    # Download embedding model
    python -c @"
import os, zipfile
from pathlib import Path
from huggingface_hub import snapshot_download

cache_dir = Path('model-cache')
cache_dir.mkdir(parents=True, exist_ok=True)
snapshot_download('Qdrant/bge-small-zh-v1.5', cache_dir=str(cache_dir))

model_dir = cache_dir / 'models--Qdrant--bge-small-zh-v1.5'
with zipfile.ZipFile('embedding-model.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(model_dir.rglob('*')):
        if f.is_file():
            zf.write(f, f.relative_to(cache_dir))
sz = os.path.getsize('embedding-model.zip') / 1024 / 1024
print(f'Created embedding-model.zip ({sz:.0f} MB)')
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ❌ Embedding 模型下载失败" -ForegroundColor Red
        exit 1
    }

    # Download reranker model
    python -c @"
import os, zipfile, shutil
from pathlib import Path
from huggingface_hub import hf_hub_download

out = Path('reranker-onnx')
out.mkdir(parents=True, exist_ok=True)

files = [
    ('onnx/model_quantized.onnx', 'model_quantized.onnx'),
    ('tokenizer.json', 'tokenizer.json'),
]
for remote_path, local_name in files:
    path = hf_hub_download(
        repo_id='onnx-community/bge-reranker-v2-m3-ONNX',
        filename=remote_path,
        local_dir=str(out),
    )
    print(f'Downloaded {remote_path}')

if Path(str(out) + '/onnx/model_quantized.onnx').exists():
    shutil.move(str(out) + '/onnx/model_quantized.onnx', str(out) + '/model_quantized.onnx')
    Path(str(out) + '/onnx').rmdir()

with zipfile.ZipFile('reranker-model.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(out.rglob('*')):
        if f.is_file():
            zf.write(f, f.relative_to(out))
sz = Path('reranker-model.zip').stat().st_size / 1024 / 1024
print(f'Created reranker-model.zip ({sz:.0f} MB)')
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ❌ Reranker 模型下载失败" -ForegroundColor Red
        exit 1
    }

    Pop-Location
    Write-Host "  ✅ 模型已下载"
}

# ── 4. PyInstaller 打包后端 ──────────────────────────────────
Write-Step "PyInstaller 打包后端"

Push-Location backend
.\.venv\Scripts\Activate.ps1
pyinstaller build.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ PyInstaller 打包失败" -ForegroundColor Red
    exit 1
}
Pop-Location

$totalMB = [math]::Round((Get-ChildItem backend\dist\backend\ -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "  ✅ Backend onedir: $totalMB MB"

# ── 5. 暂存到 src-tauri/backend-bundle ───────────────────────
Write-Step "暂存后端到 Tauri bundle"

Remove-Item -Recurse -Force src-tauri\backend-bundle -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path src-tauri\backend-bundle | Out-Null
Copy-Item -Recurse backend\dist\backend\* src-tauri\backend-bundle\
Copy-Item backend\embedding-model.zip src-tauri\backend-bundle\
Copy-Item backend\reranker-model.zip src-tauri\backend-bundle\

$totalMB = [math]::Round((Get-ChildItem src-tauri\backend-bundle\ -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "  ✅ backend-bundle: $totalMB MB"
Get-ChildItem src-tauri\backend-bundle\ | ForEach-Object {
    Write-Host "    $($_.Name) ($([math]::Round($_.Length/1MB)) MB)"
}

# ── 6. 安装前端依赖 ─────────────────────────────────────────
Write-Step "安装前端依赖"

npm install
npm install --prefix frontend

# ── 7. 构建前端 ──────────────────────────────────────────────
Write-Step "构建前端"

Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ 前端构建失败" -ForegroundColor Red
    exit 1
}
Pop-Location
Write-Host "  ✅ 前端构建完成"

# ── 8. 构建 Tauri 应用 ───────────────────────────────────────
Write-Step "构建 Tauri 应用（这可能需要几分钟）"

npx tauri build
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ❌ Tauri 构建失败" -ForegroundColor Red
    exit 1
}

# ── 9. 完成 ──────────────────────────────────────────────────
Write-Step "构建完成！"

$exeFiles = Get-ChildItem src-tauri\target\release\bundle\* -Recurse -Include "*.exe","*.msi"
foreach ($f in $exeFiles) {
    $szMB = [math]::Round($f.Length / 1MB)
    Write-Host "  📦 $($f.FullName) ($szMB MB)"
}

Write-Host "`n安装包在 src-tauri\target\release\bundle\ 下" -ForegroundColor Green
