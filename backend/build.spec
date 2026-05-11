# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Engineering Assistant Backend
Uses --onedir mode to avoid the 4GB CArchive limit of --onefile
and to dramatically improve startup speed (no extraction needed).
"""
from pathlib import Path

backend_dir = Path(SPECPATH)

# Heavy packages to collect (must be at Analysis level)
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'src', 'src.main',
]

# Collect heavy packages
for pkg in ['lancedb', 'fastembed', 'rapidocr_onnxruntime', 'fitz', 'pymupdf',
            'langchain_text_splitters', 'llama_index', 'llama_index_workflows',
            'kuzu']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

a = Analysis(
    ['run.py'],
    pathex=[str(backend_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'triton', 'torchvision', 'torchaudio',
        'tensorflow', 'keras',
        'transformers', 'accelerate', 'sentence_transformers',
        'scipy', 'sklearn', 'scikit-learn',
        'cv2', 'opencv_python',
        'datasets', 'sympy', 'matplotlib',
        'tkinter', '_tkinter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: binaries go in COLLECT, not EXE
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
