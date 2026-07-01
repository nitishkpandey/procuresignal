# ProcureSignal

🚀 **AI-powered procurement intelligence agent**

A production-grade system that brings personalized, context-aware market intelligence directly into procurement workflows. Built with Python, FastAPI, Celery, PostgreSQL, and modern AI.

[![CI](https://github.com/nitishkpandey/procuresignal/actions/workflows/ci.yml/badge.svg)](https://github.com/nitishkpandey/procuresignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Git

### Running Locally (full stack)

```bash
# 1. Configure secrets
cp .env.example .env
#   edit .env and set GROQ_API_KEY and NEWSAPI_KEY

# 2. Build and start the whole stack
docker compose up -d --build

# 3. Wait for the API to be healthy, then verify end-to-end
pip install httpx websockets   # one-time, for the smoke test
python scripts/smoke_test.py --wait
```

### Service URLs / ports

| Service     | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3000        |
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
`GROQ_API_KEY`).

### Stopping Services

```bash
docker compose down
```

## Architecture
External News Sources (NewsAPI, GDELT, RSS)
↓
Retrieval Layer (httpx, async)
↓
Normalization & Quality Gate
↓
Procurement Signal Engine (NLP + rule-based scoring)
↓
LLM Enrichment (Groq API)
↓
PostgreSQL (persistent storage)
↓
Personalization Layer
↓
REST API (FastAPI) ← Consumed by Frontend
↓
Frontend (Next.js)

### Services

| Service | Port | Purpose |
|---------|------|---------|
| Frontend | 3000 | Next.js web UI |
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
procuresignal/
├── api/                          # FastAPI service
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   ├── routers/             # API endpoints
│   │   ├── schemas/             # Pydantic models
│   │   └── dependencies/        # FastAPI dependencies
│   └── pyproject.toml
├── worker/                       # Celery worker service
│   ├── worker/
│   │   ├── main.py              # Celery app
│   │   └── tasks/               # Task definitions
│   └── pyproject.toml
├── shared/                       # Shared code
│   ├── procuresignal/
│   │   ├── config/              # Settings & config
│   │   ├── models/              # SQLAlchemy models
│   │   └── utils/               # Utilities
│   └── pyproject.toml
├── tests/                        # Test suite
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions CI/CD
├── docker-compose.yml           # Local development stack
├── Dockerfile.api
├── Dockerfile.worker
├── pyproject.toml               # Poetry workspace config
├── .pre-commit-config.yaml      # Pre-commit hooks
├── .env.example                 # Environment variables template
└── README.md

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License — see [LICENSE](LICENSE) file.

## Author
- Nitish Kumar Pandey
