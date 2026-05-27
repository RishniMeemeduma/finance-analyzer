# Finance Analyzer

A personal finance pipeline that ingests invoices and receipts from Gmail
and Google Drive, extracts structured data with Claude, stores it in
Postgres, detects anomalies, and exposes everything as MCP tools for
natural-language querying.

## Architecture
Gmail/Drive  ─┐
├─→  Ingestion  ─→  Postgres  ─→  MCP Server  ─→  Claude Code
Manual entry ─┘                                                 (chat UI)
↑
Anomaly rules

## Components

- **Ingestion** (`src/ingestion/`): OAuth-based Gmail and Drive readers
- **Extraction** (`src/extraction/`): Vision + text LLM extraction with
  structured outputs via Anthropic tool calling, Pydantic validation,
  deterministic direction detection
- **Storage** (`src/storage/`): Postgres schema with SQLAlchemy ORM and
  Alembic migrations; content-hash deduplication
- **Anomaly detection** (`src/anomaly/`): Rules engine for duplicates,
  recurring drift, outliers, new vendors, missed bills
- **MCP server** (`src/mcp_server/`): Exposes the database as 8 tools
  consumable by Claude Code, Claude Desktop, or any MCP client

## Stack

- Python 3.12, Pydantic, SQLAlchemy, Alembic
- Postgres 16 + pgvector (Docker)
- Anthropic Claude (Haiku 4.5 default)
- Model Context Protocol (MCP) Python SDK
- Google API client libraries for Gmail / Drive

## Setup

See `docs/setup.md` for the full setup walkthrough. Short version:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in ANTHROPIC_API_KEY
docker compose up -d
alembic upgrade head
python scripts/check_setup.py
```

## Status

Work in progress. Built as a learning project for AI engineering patterns:
- Structured LLM extraction with validation
- Hybrid text + vision processing
- Deterministic post-processing of LLM output
- MCP server design with read and write tools
- Rules-based anomaly detection alongside LLM-based explanation
