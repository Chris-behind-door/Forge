# 工程设计工作台 (Engineering Assistant)

A desktop application for engineering design professionals to query technical specifications and meeting notes with citation tracking.

## Features

- **Technical Document RAG** - Knowledge base retrieval with citation tracking
- **Meeting Notes Management** - Timeline view with resolution extraction via LLM
- **Resolution Relationship Graph** - Track SUPERSEDES/AMENDS/SUPPLEMENTS chains
- **Async Import Queue** - Background processing with status tracking and retry
- **BYOK** - Bring your own LLM API key (智谱/DeepSeek/Ollama etc.)
- **Cross-platform** - macOS, Windows, Linux support

## Tech Stack

- **Desktop Framework**: Tauri 2.0
- **Frontend**: React + Vite + Ant Design
- **Backend**: FastAPI + Python
- **RAG Framework**: LlamaIndex + Workflow
- **Vector Database**: LanceDB
- **Graph Database**: Kùzu
- **Document Parsing**: PyMuPDF + RapidOCR
- **Embedding**: fastembed + bge-small-zh

## Project Structure

```
engineer_assistant/
├── backend/            # Python FastAPI backend
│   ├── src/
│   │   ├── routers/    # API routes (thin HTTP layer)
│   │   ├── services/   # Business logic
│   │   ├── graph/      # Kùzu graph DB
│   │   ├── llm/        # LLM + Agent
│   │   ├── rag/        # Vector search
│   │   └── parsers/    # PDF/CHM parsing
│   └── tests/          # pytest (59 tests)
├── frontend/           # React + Vite + Ant Design
│   └── src/
│       ├── views/      # Main views
│       └── components/ # Reusable components
├── src-tauri/          # Tauri configuration
├── TECH_SPEC.md        # Technical specification
└── README.md           # This file
```

## Prerequisites

- **Rust** (for Tauri): Install from https://rustup.rs/
- **Node.js** (v18+): Install from https://nodejs.org/
- **uv** (Python package manager): Install from https://docs.astral.sh/uv/

## Development Setup

### 1. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 2. Install Backend Dependencies

```bash
cd backend
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

### 3. Run Development Servers

**Backend:**
```bash
cd backend
uv run uvicorn src.main:app --reload --port 8765
```

**Frontend:**
```bash
cd frontend
npm run dev
```

**Tauri (requires Rust):**
```bash
cd src-tauri
cargo tauri dev
```

## Building

### Backend (PyInstaller)

```bash
cd backend
uv run pyinstaller build.spec
```

### Frontend

```bash
cd frontend
npm run build
```

### Tauri Application

```bash
# Copy backend executable to sidecar directory
cp backend/dist/backend src-tauri/binaries/backend-x86_64-unknown-linux-gnu

# Build Tauri application
cd src-tauri
cargo tauri build
```

## Documentation

See [TECH_SPEC.md](./TECH_SPEC.md) for detailed technical specification.

## License

MIT

## Authors

克里斯 + 小爪
