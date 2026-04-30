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

### Running Locally

```bash
# Clone the repository
git clone https://github.com/nitishkpandey/procuresignal.git
cd procuresignal

# Start all services
docker-compose up -d

# Wait for services to be ready (~30 seconds)
docker-compose logs -f api

# API will be available at http://localhost:8000
# Swagger docs: http://localhost:8000/docs
# Grafana: http://localhost:3000 (admin/admin)
```

### Stopping Services

```bash
docker-compose down
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
| PostgreSQL | 5432 | Data persistence |
| Redis | 6379 | Message broker & caching |
| FastAPI | 8000 | REST API & Swagger docs |
| Celery Worker | N/A | Background pipeline jobs |
| Grafana | 3000 | Metrics dashboards |
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

## Phases

This project is built incrementally across 14 phases. See [PHASES.md](docs/PHASES.md) for details.

- Phase 0: Project scaffold - Done
- Phase 1: Database layer
- Phase 2: News retrieval
- Phase 3: Normalization & filtering
- Phase 4: Signal engine
- Phase 5: LLM enrichment
- ...and more

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License — see [LICENSE](LICENSE) file.

## Author
- Nitish Kumar Pandey
