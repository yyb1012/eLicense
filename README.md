# eLicense (N00~N04 Scaffold)

This repository now contains the first implementation stage for the LangGraph project:
- Baseline-aligned engineering skeleton
- FastAPI minimal service
- Empty executable orchestrator flow
- Infrastructure stubs (PostgreSQL / Redis / structured logging + trace_id)

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn src.interfaces.api.main:app --reload --port 8000
```

## Test

```bash
python3 -m pytest -q
```

## Implemented APIs

- `GET /health`
- `POST /api/v1/chat`
