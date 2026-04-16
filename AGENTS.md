# AGENTS.md

## Repo status

This repository currently contains planning/baseline documents only. No runnable scaffold, dependency manifest, or verified local dev commands exist yet.

## Source of truth

- Primary baseline: `LangGraph项目实施与多角色子图_Harness合并文档 .md`
- Secondary execution guide: `LangGraph项目施工文档_软件工程_vibe版 .md`
- If the two documents conflict, follow the primary baseline and then sync the construction guide.

## Working workflow

- Read the primary baseline first to confirm what to build.
- Use the construction guide to confirm node breakdown, acceptance, and rollout order.
- Build in small loops: `Define -> Context Pack -> Generate -> Constrain -> Verify -> Record`.
- Do not move to the next loop until tests/verification for the current loop pass.
- Prioritize skeleton work first: `N00` to `N04`, then high-value nodes `N06` / `N07A` / `N09` / `N10` / `N12` / `N14`.

## Documented entrypoints

- User API: `POST /api/v1/chat`
- User API: `GET /api/v1/sessions/{session_id}/summary`
- Ops API: `POST /api/v1/ops/inspection/run`
- Ops API: `GET /api/v1/ops/inspection/reports`
- Ops API: `GET /api/v1/ops/incidents`
- Document API: `POST /api/v1/documents/upload`
- Document API: `GET /api/v1/documents/{asset_id}/ocr`

## Documented stack and operations

- Runtime target: Python `3.11+`, FastAPI, LangGraph
- Storage: PostgreSQL + pgvector, Redis, object storage
- Observability: OpenTelemetry + JSON logs, `trace_id` through the full chain
- Scheduling: APScheduler or Celery Beat
- OCR path: PaddleOCR
- Inspection cadence from the baseline: every 5 minutes, every 1 hour, and daily summary

## Commands

- TODO: add actual install, run, lint, and test commands after the project scaffold is committed. The current docs define APIs and workflows, but do not provide verified shell commands.
