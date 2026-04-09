# Engineer Assistant Backend

Python backend for the Engineering Assistant application.

## Setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
cd backend
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

## Running

```bash
uv run uvicorn src.main:app --reload
```

## API Endpoints

- `GET /health` - Health check
- `POST /query` - Query the knowledge base
- `POST /documents` - Upload documents

## Development

See `TECH_SPEC.md` for detailed architecture and implementation plan.
