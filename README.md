# ProcureSignal

**AI-powered procurement intelligence agent**

A production-grade system that brings personalized, context-aware market intelligence directly into procurement workflows. Built with Python, FastAPI, Celery, PostgreSQL, and modern AI.

[![CI](https://github.com/nitishkpandey/procuresignal/actions/workflows/ci.yml/badge.svg)](https://github.com/nitishkpandey/procuresignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Personalized feed** — procurement signals ranked by relevance, each showing priority, category, source, date, and detected suppliers/regions
- **Signal engine** — rule-based classification (supplier risk, tariffs, M&A, logistics disruption, regulatory) with risk scoring
- **LLM enrichment** — OpenAI-powered summaries and signal tagging
- **Feed-grounded chat** — ask questions about your signals; answers are grounded in your preferences and recent feed
- **Per-user preferences** — interested/excluded categories, suppliers, regions, and signal types
- **EUR currency monitor** — tracks EUR against key supplier-market currencies for procurement timing
- **Scheduled operations** — optional APScheduler orchestration with idempotent job registration and retention cleanup

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Git

### Running Locally (full stack)

```bash
# 1. Configure secrets
cp .env.example .env
#   edit .env and set OPENAI_API_KEY and NEWSAPI_KEY

# 2. Build and start the whole stack
docker compose up -d --build

# 3. Wait for the API to be healthy, then verify end-to-end
pip install httpx websockets   # one-time, for the smoke test
python scripts/smoke_test.py --wait
```

### Service URLs / ports

| Service     | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3002        |
| API + docs  | http://localhost:8000/docs   |
| Grafana     | http://localhost:3001 (admin/admin) |
| Flower      | http://localhost:5555        |
| Prometheus  | http://localhost:9090        |
| Postgres    | localhost:5433               |
| Redis       | localhost:6379               |

Migrations run automatically (the `migrate` service runs `alembic upgrade head`
before the API starts). The one-shot `bootstrap` service triggers the
retrieval → enrichment → personalization pipeline once so the feed populates
with real articles over the following minutes (requires `NEWSAPI_KEY` /
`OPENAI_API_KEY`; optionally set `OPENAI_MODEL`).

### Scheduling, freshness, and retention

ProcureSignal can run scheduled jobs in two ways:

- Celery beat (`beat` service) is enabled in Docker Compose and runs retrieval every 6 hours, normalization/enrichment every 2 hours, and personalization hourly.
- API-owned APScheduler is available by setting `ENABLE_APSCHEDULER=true`; use this instead of Celery beat if the API should own the schedule.

Scheduled job IDs are stable and registered with `replace_existing=True`, `coalesce=True`, and `max_instances=1`, so repeated API starts do not duplicate jobs. Retention cleanup runs daily at 02:15 UTC and keeps raw articles for 14 days, processed articles for 30 days, and user-facing feed rows for 14 days.

If a user has no saved preferences, feed generation falls back to general category-level procurement news. Saved preferences live in PostgreSQL and include supplier, location, category, misc signal filters, exclusions, and platform language. The currency monitor calls Frankfurter's latest EUR rates endpoint and displays daily central-bank exchange rates for procurement timing.

### Stopping Services

```bash
docker compose down
```

## Architecture

```
External News Sources (NewsAPI, GDELT, RSS)
        ↓
Retrieval Layer (httpx, async)
        ↓
Normalization & Quality Gate
        ↓
Procurement Signal Engine (NLP + rule-based scoring)
        ↓
LLM Enrichment (OpenAI Responses API)
        ↓
PostgreSQL (persistent storage)
        ↓
Personalization Layer
        ↓
REST API (FastAPI) ← Consumed by Frontend
        ↓
Frontend (Next.js)
```

### Services

| Service | Port | Purpose |
|---------|------|---------|
| Frontend | 3002 | Next.js web UI |
| PostgreSQL | 5433 | Data persistence |
| Redis | 6379 | Message broker & caching |
| FastAPI | 8000 | REST API & Swagger docs |
| Celery Worker | N/A | Background pipeline jobs |
| Grafana | 3001 | Metrics dashboards |
| Prometheus | 9090 | Metrics collection |

## Development

### Installing Dependencies

```bash
poetry install
```

### Running Tests

```bash
pytest tests/ -v --cov=api --cov=worker --cov=shared
```

### Code Quality

```bash
# Format code
black . && ruff check . --fix

# Type checking
mypy api worker

# Pre-commit hooks (automatic on git commit)
pre-commit run --all-files
```

## Project Structure

```
procuresignal/
├── api/                     # FastAPI service
│   ├── main.py              # App, lifespan, router wiring
│   ├── dependencies.py      # Shared FastAPI dependencies
│   ├── routers/             # feed, preferences, articles, search, signals, chat, health
│   └── schemas/             # Pydantic request/response models
├── worker/                  # Celery worker
│   ├── main.py              # Celery app
│   ├── celery_config.py     # Queues + beat schedule
│   ├── tasks.py             # Retrieval → normalization → enrichment → personalization
│   └── signal_tasks.py      # Signal detection & storage
├── shared/procuresignal/    # Shared library (installed as a package)
│   ├── config/              # Settings & database
│   ├── models/              # SQLAlchemy models
│   ├── retrieval/           # News providers (NewsAPI, GDELT, RSS) + persistence
│   ├── normalization/       # Cleaning, quality gate, dedup
│   ├── signals/             # Classifier, entity resolver, risk scorer
│   ├── enrichment/          # OpenAI LLM enrichment
│   ├── personalization/     # Feed matching + preference manager
│   └── chat/                # Feed-grounded chat client + context builder
├── frontend/                # Next.js web UI (feed, preferences, chat)
├── migrations/              # Alembic migrations
├── tests/                   # unit + integration
├── scripts/                 # smoke test and pipeline bootstrap
├── docker-compose.yml       # Full local stack
├── Dockerfile.api           # API & migrate & bootstrap image
├── Dockerfile.worker        # Worker & beat image
└── pyproject.toml           # Poetry (single workspace)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License — see [LICENSE](LICENSE) file.

## Author
- Nitish Kumar Pandey
