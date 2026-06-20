# PROCURESIGNAL
## Technical Requirements Document (TRD)

**Version:** 1.0  
**Date:** June 2026  
**Status:** APPROVED  
**Author:** Technical Architecture Team

---

## Executive Summary

This document specifies the complete technical architecture, technology stack, data models, API specifications, and deployment strategy for ProcureSignal. The system is designed to be scalable, fault-tolerant, and maintainable using a modern microservices approach with containerized deployment.

---

## 1. Architecture Overview

### 1.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                              │
├──────────────────────┬──────────────────────┬────────────────────┤
│   Next.js Frontend   │   Mobile App (TBD)   │   External API     │
│   (http://3000)      │   (React Native)     │   (REST)           │
└──────────────────────┴──────────────────────┴────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      API Layer (FastAPI)                         │
├──────────────────────────────────────────────────────────────────┤
│  REST Endpoints: /api/feed, /preferences, /search, /articles    │
│  WebSocket: /ws/chat/{user_id}/{conversation_id}               │
│  Health: /health                                                 │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────┬──────────────────────┬────────────────────┐
│   Retrieval Layer    │   Enrichment Layer   │  Personalization   │
│   (NewsAPI, GDELT,   │   (Groq LLM)        │  (ML Matching)     │
│    RSS)              │                      │                    │
└──────────────────────┴──────────────────────┴────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Background Processing (Celery)                  │
├───────────────────┬──────────────────┬──────────────────────────┤
│  Retrieval Tasks  │  Normalization   │  Enrichment Jobs       │
│  (every 6h)       │  (every 2h)      │  (every 2h)            │
│                   │                  │  Personalization       │
│                   │                  │  (every 1h)            │
└───────────────────┴──────────────────┴──────────────────────────┘
                              ↓
┌──────────────────────┬──────────────────────┬────────────────────┐
│   PostgreSQL DB      │   Redis Cache        │   ChromaDB         │
│   (Data Storage)     │   (Session, Queue)   │   (Embeddings)     │
└──────────────────────┴──────────────────────┴────────────────────┘
```

### 1.2 Architecture Principles

| Principle | Implementation |
|-----------|-----------------|
| Separation of Concerns | Microservices (API, Worker, Frontend) |
| Scalability | Horizontal scaling via Docker + K8s |
| Fault Tolerance | Retry logic, circuit breakers, fallbacks |
| Determinism | Rule-based signal detection (no blackbox AI) |
| Extensibility | Plugin-based providers, modular design |
| Cost Efficiency | Open source stack, free APIs (Groq, NewsAPI) |

---

## 2. Technology Stack

### 2.1 Backend Services

| Component | Technology | Version | Rationale |
|-----------|-----------|---------|-----------|
| **API Server** | FastAPI | 0.104+ | Fast, async, auto-docs (OpenAPI) |
| **Language** | Python | 3.11+ | Rich ML/data libraries, fast dev |
| **ORM** | SQLAlchemy | 2.0+ | Async support, migrations (Alembic) |
| **Task Queue** | Celery | 5.3+ | Distributed, fault-tolerant tasks |
| **Task Scheduler** | Celery Beat | 5.3+ | Periodic task scheduling |
| **Message Broker** | Redis | 5.0+ | Fast, in-memory, pub/sub |
| **Database** | PostgreSQL | 14+ | ACID compliance, full-text search |
| **Vector DB** | ChromaDB | Latest | Semantic search (future phase) |
| **HTTP Client** | httpx | 0.24+ | Async HTTP, connection pooling |
| **LLM Provider** | Groq API | Latest | Free Llama 3.1, fast inference |
| **NLP** | spaCy | 3.7+ | Named entity recognition (NER) |
| **Language Detection** | langdetect | 1.0+ | Multi-language support |
| **Validation** | Pydantic | 2.0+ | Data validation, serialization |
| **Logging** | structlog | Latest | Structured JSON logs |
| **Monitoring** | Prometheus | Latest | Metrics collection |
| **Visualization** | Grafana | Latest | Metrics dashboards |
| **Task Monitoring** | Flower | 2.0+ | Celery task monitoring UI |

### 2.2 Frontend

| Component | Technology | Version | Rationale |
|-----------|-----------|---------|-----------|
| **Framework** | Next.js | 14+ | React, SSR, static generation |
| **Language** | TypeScript | 5.0+ | Type safety, better DX |
| **Styling** | Tailwind CSS | 3.0+ | Utility-first, responsive design |
| **UI Components** | shadcn/ui | Latest | Pre-built, customizable components |
| **HTTP Client** | Axios | 1.4+ | Promise-based, interceptors |
| **State Management** | Zustand | Latest | Lightweight, simple state |
| **WebSocket** | Native WS | Browser API | Real-time chat |
| **Build Tool** | Webpack (Next.js) | Latest | Bundling, optimization |
| **Linting** | ESLint | 8.0+ | Code quality |

### 2.3 Infrastructure

| Component | Technology | Version | Rationale |
|-----------|-----------|---------|-----------|
| **Containerization** | Docker | 24+ | Consistent deployment |
| **Orchestration** | Docker Compose | 2.0+ | Multi-container orchestration |
| **Cloud** | AWS/GCP/Azure | Latest | Deployment options |
| **Container Registry** | Docker Hub | Latest | Image storage |
| **CI/CD** | GitHub Actions | Latest | Built-in, free for public repos |
| **Reverse Proxy** | Nginx | 1.24+ | Load balancing, HTTPS |
| **VCS** | Git/GitHub | Latest | Version control |

### 2.4 Development Tools

| Tool | Version | Purpose |
|------|---------|---------|
| Poetry | 1.7+ | Dependency management |
| pytest | 7.4+ | Unit/integration testing |
| pytest-asyncio | Latest | Async test support |
| testcontainers | Latest | Container-based integration tests |
| Pre-commit | 3.4+ | Git hooks (linting, formatting) |
| Black | 23.0+ | Code formatting |
| Ruff | 0.1+ | Fast linting |
| mypy | 1.5+ | Static type checking |
| Bandit | 1.7+ | Security linting |

---

## 3. Data Models

### 3.1 Core Entities

#### NewsArticleRaw
```python
NewsArticleRaw {
  id: int,
  provider: str,  # "newsapi", "gdelt", "rss"
  provider_article_id: str,
  query_group: str,  # "supplier_risk", "tariff_changes", etc.
  title: str,
  description: str,
  content_snippet: str,
  article_url: str,
  canonical_url: str,
  source_name: str,
  source_url: str,
  published_at: datetime,
  language: str,  # "en", "de", "fr", etc.
  ingest_hash: str,  # SHA256(title+source+date)
  raw_payload_json: dict,
  created_at: datetime,
  updated_at: datetime,
}

# Indexes
- provider + provider_article_id (unique)
- ingest_hash (unique)
- created_at (for time-based queries)
- source_name (for filtering)
```

#### NewsArticleProcessed
```python
NewsArticleProcessed {
  id: int,
  raw_article_id: int,  # FK to NewsArticleRaw
  normalized_title: str,
  summary: str,  # 3-5 sentence summary from LLM
  top_level_category: str,  # "automotive", "electronics", etc.
  signal_tags: list[str],  # ["bankruptcy", "tariff", "strike"]
  priority_signal: str | null,  # "bankruptcy" if high-priority signal
  detected_suppliers: list[str],  # Named entities (NER)
  detected_regions: list[str],
  detected_categories: list[str],
  signal_score: float,  # 0.0-1.0 overall signal strength
  processing_status: str,  # "completed", "failed", "pending"
  llm_model: str,  # "groq/llama-3.1-8b"
  language: str,
  processed_at: datetime,
  created_at: datetime,
  updated_at: datetime,
}

# Indexes
- raw_article_id (FK)
- top_level_category
- signal_tags
- processed_at
```

#### UserNewsPreference
```python
UserNewsPreference {
  id: int,
  user_id: str,  # "user123", email, or UUID
  interested_categories: list[str],  # ["automotive", "manufacturing"]
  interested_suppliers: list[str],  # ["Bosch", "Siemens"]
  interested_regions: list[str],  # ["Germany", "Poland"]
  interested_signals: list[str],  # ["bankruptcy", "tariff"]
  excluded_categories: list[str],
  excluded_suppliers: list[str],
  excluded_regions: list[str],
  excluded_signals: list[str],
  created_at: datetime,
  updated_at: datetime,
}

# Indexes
- user_id (unique)
```

#### UserNewsFeed
```python
UserNewsFeed {
  id: int,
  user_id: str,
  article_id: int,  # FK to NewsArticleProcessed
  relevance_score: float,  # 0.0-1.0
  rank: int,  # 1, 2, 3... position in feed
  match_breakdown: dict,  # {category: 0.9, supplier: 0.8, region: 0.7, signal: 1.0}
  added_to_feed_at: datetime,
  read_at: datetime | null,
  created_at: datetime,
}

# Indexes
- user_id + created_at (for feed queries)
- article_id
```

#### ChatMessage
```python
ChatMessage {
  id: int,
  user_id: str,
  conversation_id: str,
  role: str,  # "user" or "assistant"
  content: str,
  tokens_used: int,  # For LLM cost tracking
  created_at: datetime,
  updated_at: datetime,
}

# Indexes
- user_id + conversation_id (for history)
- conversation_id
- created_at
```

#### ChatConversation
```python
ChatConversation {
  id: int,
  user_id: str,
  conversation_id: str,  # UUID
  title: str,  # Auto-generated from first user message
  message_count: int,
  last_message_at: datetime | null,
  created_at: datetime,
  updated_at: datetime,
}

# Indexes
- user_id + last_message_at (for conversation list)
- conversation_id (unique)
```

### 3.2 Database Schema

```sql
-- Core tables
CREATE TABLE news_articles_raw (
  id SERIAL PRIMARY KEY,
  provider VARCHAR(50),
  provider_article_id VARCHAR(255),
  query_group VARCHAR(100),
  title TEXT NOT NULL,
  description TEXT,
  content_snippet TEXT,
  article_url VARCHAR(2000) NOT NULL,
  canonical_url VARCHAR(2000),
  source_name VARCHAR(200),
  source_url VARCHAR(2000),
  published_at TIMESTAMP NOT NULL,
  language VARCHAR(10),
  ingest_hash VARCHAR(64) UNIQUE,
  raw_payload_json JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (provider, provider_article_id)
);

CREATE TABLE news_articles_processed (
  id SERIAL PRIMARY KEY,
  raw_article_id INTEGER REFERENCES news_articles_raw(id),
  normalized_title VARCHAR(500),
  summary TEXT,
  top_level_category VARCHAR(50),
  signal_tags TEXT[],
  priority_signal VARCHAR(100),
  detected_suppliers TEXT[],
  detected_regions TEXT[],
  detected_categories TEXT[],
  signal_score FLOAT,
  processing_status VARCHAR(50),
  llm_model VARCHAR(100),
  language VARCHAR(10),
  processed_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_news_preferences (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(100) UNIQUE NOT NULL,
  interested_categories TEXT[],
  interested_suppliers TEXT[],
  interested_regions TEXT[],
  interested_signals TEXT[],
  excluded_categories TEXT[],
  excluded_suppliers TEXT[],
  excluded_regions TEXT[],
  excluded_signals TEXT[],
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_news_feed (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(100) NOT NULL,
  article_id INTEGER REFERENCES news_articles_processed(id),
  relevance_score FLOAT,
  rank INTEGER,
  match_breakdown JSONB,
  added_to_feed_at TIMESTAMP,
  read_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE chat_messages (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(100),
  conversation_id VARCHAR(100),
  role VARCHAR(20),
  content TEXT NOT NULL,
  tokens_used INTEGER,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE chat_conversations (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(100),
  conversation_id VARCHAR(100) UNIQUE,
  title VARCHAR(200),
  message_count INTEGER,
  last_message_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_raw_articles_created ON news_articles_raw(created_at);
CREATE INDEX idx_raw_articles_source ON news_articles_raw(source_name);
CREATE INDEX idx_processed_category ON news_articles_processed(top_level_category);
CREATE INDEX idx_processed_signals ON news_articles_processed USING GIN(signal_tags);
CREATE INDEX idx_user_feed_user ON user_news_feed(user_id, created_at);
CREATE INDEX idx_chat_messages_conv ON chat_messages(conversation_id, created_at);
```

---

## 4. API Specifications

### 4.1 REST API Endpoints

#### Feed Endpoints

**GET /api/feed**
```
Query Parameters:
  - user_id (required): str, length 1-100
  - limit (optional): int, default 50, range 1-200
  - days (optional): int, default 7, range 1-30

Response:
  {
    "user_id": "user123",
    "articles": [
      {
        "id": 1,
        "title": "Bosch announces new facility in Poland",
        "summary": "...",
        "category": "manufacturing",
        "signal_tags": ["expansion"],
        "priority_signal": null,
        "source_name": "Reuters",
        "published_at": "2026-06-20T10:00:00Z",
        "article_url": "https://...",
        "relevance_score": 0.85,
        "rank": 1
      }
    ],
    "total_count": 42,
    "generated_at": "2026-06-20T10:00:00Z",
    "days_included": 7
  }

Response Codes:
  200: Success
  400: Invalid parameters
  500: Server error
```

#### Preference Endpoints

**POST /api/preferences**
```
Request:
  {
    "user_id": "user123",
    "interested_categories": ["automotive", "manufacturing"],
    "interested_suppliers": ["Bosch", "Siemens"],
    "interested_regions": ["Germany", "Poland"],
    "interested_signals": ["bankruptcy", "tariff"],
    "excluded_categories": ["general"],
    "excluded_suppliers": [],
    "excluded_regions": [],
    "excluded_signals": []
  }

Response:
  {
    "user_id": "user123",
    "interested_categories": ["automotive", "manufacturing"],
    ...
  }

Response Codes:
  200: Success
  400: Invalid data
  500: Server error
```

**GET /api/preferences**
```
Query Parameters:
  - user_id (required): str

Response:
  {
    "user_id": "user123",
    "interested_categories": ["automotive"],
    ...
  }

Response Codes:
  200: Success
  404: Preferences not found
  500: Server error
```

#### Article Endpoints

**GET /api/articles/{id}**
```
Response:
  {
    "id": 1,
    "title": "...",
    "summary": "...",
    "category": "automotive",
    "signal_tags": ["tariff"],
    "priority_signal": "tariff",
    "detected_suppliers": ["Bosch"],
    "detected_regions": ["Germany"],
    "source_name": "Reuters",
    "published_at": "2026-06-20T10:00:00Z",
    "processed_at": "2026-06-20T11:00:00Z",
    "language": "en",
    "llm_model": "groq/llama-3.1-8b"
  }

Response Codes:
  200: Success
  404: Article not found
  500: Server error
```

#### Search Endpoints

**GET /api/search**
```
Query Parameters:
  - q (required): str, length 1-200
  - limit (optional): int, default 20, range 1-100
  - days (optional): int, default 7, range 1-30

Response:
  {
    "query": "tariff",
    "total_results": 15,
    "results": [
      {
        "id": 1,
        "title": "...",
        "summary": "...",
        "category": "manufacturing",
        "published_at": "2026-06-20T10:00:00Z",
        "relevance": 0.95
      }
    ],
    "search_time_ms": 125.5
  }

Response Codes:
  200: Success
  400: Invalid query
  500: Server error
```

#### Health Endpoint

**GET /health**
```
Response:
  {
    "status": "healthy",
    "service": "api",
    "timestamp": "2026-06-20T10:00:00Z",
    "database": "connected",
    "cache": "connected"
  }

Response Codes:
  200: Healthy
  503: Unhealthy
```

### 4.2 WebSocket API

**WS /api/ws/chat/{user_id}/{conversation_id}**

Client → Server (send):
```json
{
  "message": "What does the tariff mean for my supply chain?"
}
```

Server → Client (receive):
```json
{
  "type": "start",
  "content": "Processing your message..."
}
```

```json
{
  "type": "stream",
  "content": "The tariff increases costs by 10-15% "
}
```

```json
{
  "type": "end",
  "content": "Response complete"
}
```

---

## 5. Integration Points

### 5.1 External API Integrations

#### NewsAPI
```
Endpoint: https://newsapi.org/v2/everything
Rate Limit: 100 requests/day (free tier)
Auth: API key in query params
Timeout: 10 seconds
Retry: Exponential backoff (2, 4, 8 seconds)
```

#### GDELT
```
Endpoint: https://api.gdelt.org/api/v2/search
Rate Limit: Unlimited
Auth: None required
Timeout: 30 seconds
Retry: Exponential backoff
```

#### RSS Feeds
```
Sources: Reuters, Bloomberg, government feeds
Format: Standard RSS/Atom
Timeout: 20 seconds
Update Frequency: 6 hours
Fallback: If feed unavailable, skip for this cycle
```

#### Groq API
```
Endpoint: https://api.groq.com/v1/messages
Model: llama-3.1-8b-instant
Rate Limit: 6000 requests/minute
Auth: Bearer token
Timeout: 60 seconds
Retry: Exponential backoff + circuit breaker
```

### 5.2 Third-Party Services

| Service | Purpose | Cost | Fallback |
|---------|---------|------|----------|
| Groq API | LLM inference | Free | Cache summaries |
| NewsAPI | News source | Free | Use GDELT + RSS only |
| spaCy | NER | Open source | Keyword matching |
| PostgreSQL | Database | Self-hosted | None |
| Redis | Cache/broker | Self-hosted | None |

---

## 6. Performance Requirements

### 6.1 Latency Requirements

| Operation | Target | Threshold | Measurement |
|-----------|--------|-----------|-------------|
| GET /api/feed | <2s (p95) | <5s (p99) | Server logs |
| POST /api/preferences | <1s (p95) | <3s (p99) | Server logs |
| GET /api/articles/{id} | <500ms (p95) | <2s (p99) | Server logs |
| GET /api/search | <2s (p95) | <5s (p99) | Server logs |
| WS chat response | <3s (p95) | <10s (p99) | Client metrics |

### 6.2 Throughput Requirements

| Operation | Target | Capacity |
|-----------|--------|----------|
| News articles/day | 100-1000 | 10,000 |
| Concurrent users | 100 | 10,000 |
| API requests/second | 10 | 1,000 |
| LLM enrichment jobs | 100/hour | 10,000/hour |

### 6.3 Availability Requirements

| Service | Target | Calculation |
|---------|--------|-------------|
| API Server | 99.9% | <43 minutes downtime/month |
| Database | 99.95% | <21 minutes downtime/month |
| Overall | 99.9% | <43 minutes downtime/month |

### 6.4 Optimization Strategies

| Strategy | Target | Implementation |
|----------|--------|-----------------|
| Caching | 70% cache hit rate | Redis (user feeds, articles) |
| Database indexing | <50ms query time | Composite indexes on foreign keys |
| Connection pooling | 100 connections | SQLAlchemy pool configuration |
| Async processing | 500ms response | FastAPI async endpoints |
| Batch processing | 10 articles/batch | Celery task batching |

---

## 7. Security Requirements

### 7.1 Authentication & Authorization

| Requirement | Implementation | Status |
|-------------|-----------------|--------|
| User authentication | API key / JWT (future) | Planned (Phase 2) |
| Role-based access control | RBAC middleware | Planned (Phase 3) |
| API rate limiting | Per-user quota | Planned (Phase 2) |
| Session management | Redis sessions | To implement |

### 7.2 Data Security

| Requirement | Implementation |
|-------------|-----------------|
| Encryption at rest | PostgreSQL with pgcrypto |
| Encryption in transit | HTTPS/TLS 1.3 |
| Data masking | PII redaction in logs |
| Backup & recovery | Daily automated backups |
| Data retention | Delete after 2 years (GDPR) |

### 7.3 Application Security

| Requirement | Implementation |
|-------------|-----------------|
| SQL injection prevention | SQLAlchemy ORM (parameterized) |
| XSS prevention | React/Next.js escaping |
| CSRF protection | SameSite cookies |
| Input validation | Pydantic validation |
| Output encoding | JSON serialization |
| Dependency scanning | Dependabot + security audits |

### 7.4 Infrastructure Security

| Requirement | Implementation |
|-------------|-----------------|
| Network isolation | Private subnets (if cloud) |
| Firewall rules | Ingress: ports 80, 443 only |
| Secrets management | Environment variables / Vaults |
| DDoS protection | Cloudflare / AWS Shield (if cloud) |
| Logging & monitoring | Prometheus + structured logs |

---

## 8. Scalability

### 8.1 Horizontal Scaling Strategy

```
Load Balancer (Nginx)
        ↓
┌────────┴────────────────┬───────────────────┐
↓                         ↓                   ↓
API Pod 1              API Pod 2         API Pod N
(FastAPI)              (FastAPI)         (FastAPI)
        ↓                 ↓                   ↓
            PostgreSQL (single, replicated)
            Redis (cluster)
            
Worker Pods (Celery)
↓    ↓    ↓    ↓
W1   W2   W3   W4 (scales 1-100+)
```

### 8.2 Database Scaling

| Approach | Rationale | When |
|----------|-----------|------|
| Read replicas | 80% queries are reads | >1000 concurrent users |
| Partitioning | Split by date/user | >1B records |
| Caching | Reduce DB queries | >100 req/sec |
| Archive | Move old data | 2+ years of data |

### 8.3 Application Scaling

| Component | Scaling Method | Trigger |
|-----------|-----------------|---------|
| API server | Horizontal (load balancer) | >100 requests/sec |
| Celery worker | Add worker pods | >50 tasks/sec |
| Redis | Cluster mode | >10K connections |
| PostgreSQL | Read replicas | >500 QPS |

---

## 9. Deployment Architecture

### 9.1 Deployment Stages

```
Stage 1: Development (Local)
├─ docker-compose up
├─ Services: API, Worker, Beat, DB, Redis
└─ Endpoint: http://localhost:8000

Stage 2: Staging (Docker)
├─ docker build
├─ Services: API, Worker, Beat, DB, Redis (containerized)
├─ Registry: Docker Hub / ECR
└─ Endpoint: staging.procuresignal.com

Stage 3: Production (Kubernetes or ECS)
├─ Helm charts / CloudFormation
├─ Services: Replicated API, Workers, DB (RDS), Redis (ElastiCache)
├─ CDN: CloudFront / Cloudflare
├─ Monitoring: Prometheus + Grafana + CloudWatch
└─ Endpoint: procuresignal.com
```

### 9.2 Container Definitions

**API Container (Dockerfile.api)**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml poetry.lock .
RUN poetry install --no-dev
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Worker Container (Dockerfile.worker)**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml poetry.lock .
RUN poetry install --no-dev
COPY . .
CMD ["celery", "-A", "worker.main", "worker", "--loglevel=info"]
```

**Frontend Container (Dockerfile.frontend)**
```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY frontend/package*.json .
RUN npm install
COPY frontend . 
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

### 9.3 Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@postgres:5432/procuresignal

# Cache
REDIS_URL=redis://redis:6379/0

# APIs
GROQ_API_KEY=<from groq.com>
NEWSAPI_KEY=<from newsapi.org>

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# Logging
LOG_LEVEL=info
```

---

## 10. Monitoring & Observability

### 10.1 Metrics to Monitor

| Metric | Type | Target | Alert Threshold |
|--------|------|--------|------------------|
| API response time (p95) | Latency | <2s | >5s |
| API error rate | Error | <0.1% | >1% |
| Database connections | Resource | <100 | >150 |
| Redis memory | Resource | <1GB | >2GB |
| Worker queue depth | Queue | <10 | >100 |
| Task success rate | Reliability | >99% | <95% |

### 10.2 Logging Strategy

```
Level | Destination | Retention | Sampling |
------|-------------|-----------|----------|
DEBUG | Local only  | 1 day     | 10%      |
INFO  | CloudWatch  | 30 days   | 100%     |
WARN  | CloudWatch  | 90 days   | 100%     |
ERROR | CloudWatch  | 1 year    | 100%     |
```

### 10.3 Alerting

| Alert | Condition | Action |
|-------|-----------|--------|
| High Error Rate | >5% errors for 5 min | Page on-call |
| Database Down | No connection for 1 min | Page on-call + email |
| Worker Queue High | >500 tasks for 10 min | Scale workers |
| API Latency High | p95 > 5s for 5 min | Auto-scale + investigate |

---

## 11. Testing Strategy

### 11.1 Test Coverage

| Layer | Test Type | Target Coverage | Tools |
|-------|-----------|-----------------|-------|
| Unit | Functions | 80%+ | pytest |
| Integration | APIs, DB | 60%+ | pytest + testcontainers |
| E2E | Full workflows | 40%+ | Selenium / Playwright |
| Load | Performance | Key paths | Locust / K6 |

### 11.2 Test Environments

```
Development (local)
└─ Unit tests: pytest
  Integration tests: Docker containers
  
Staging (CI/CD)
└─ All unit + integration tests
  Smoke tests (API health checks)
  
Production (post-deploy)
└─ Synthetic monitoring
  Real user monitoring (RUM)
```

---

## 12. Disaster Recovery & Business Continuity

### 12.1 RTO & RPO

| Component | RTO (Recovery Time Objective) | RPO (Recovery Point Objective) |
|-----------|-------------------------------|-------------------------------|
| Database | 1 hour | 15 minutes |
| API servers | 10 minutes | N/A |
| Cache | 5 minutes | 5 minutes |

### 12.2 Backup Strategy

```
Daily: Full database backup to S3
  - Retention: 30 days
  - Time: 2:00 AM UTC

Weekly: Full system snapshot
  - Retention: 12 weeks
  - Time: Sunday 2:00 AM UTC

Monthly: Archive to Glacier
  - Retention: 7 years
  - Time: 1st of month
```

---

## 13. Implementation Phases

### Phase 1: MVP (Weeks 1-8) ✅ COMPLETE
- [x] Retrieval (NewsAPI, GDELT, RSS)
- [x] Normalization & quality gates
- [x] Signal detection (20+ types)
- [x] LLM enrichment
- [x] Basic personalization
- [x] REST API
- [x] WebSocket chat
- [x] Next.js frontend

### Phase 2: Enhancement (Weeks 9-16)
- [ ] Advanced NLP (sentiment, aspect extraction)
- [ ] Custom alerts & webhooks
- [ ] Email digests
- [ ] Multi-language support
- [ ] Team collaboration

### Phase 3: Scale (Weeks 17-24)
- [ ] Enterprise auth (SSO, SAML)
- [ ] Advanced analytics
- [ ] Mobile app
- [ ] API marketplace
- [ ] White-label edition

---

## 14. Technology Decisions & Rationale

### 14.1 Why FastAPI?

| Decision | Rationale | Alternative |
|----------|-----------|-------------|
| FastAPI | Async, auto-docs, Pydantic validation | Django, Flask |
| PostgreSQL | ACID, full-text search, JSON support | MongoDB (no ACID), MySQL |
| Celery | Distributed, fault-tolerant, scalable | APScheduler, RQ |
| Next.js | SSR, static export, great DX | Vue, Svelte |
| Redis | In-memory, pub/sub, fast | Memcached, DynamoDB |

### 14.2 Why Groq?

| Reason | Benefit |
|--------|---------|
| **Free tier** | No LLM costs during growth phase |
| **Speed** | 300 tokens/sec vs GPT-4's 60 tokens/sec |
| **Model quality** | Llama 3.1 8B competitive with GPT-3.5 |
| **Deterministic** | Good for consistent output |
| **Quota generous** | 6000 req/min supports 1000+ users |

---

## 15. Glossary

| Term | Definition |
|------|-----------|
| **ACID** | Atomicity, Consistency, Isolation, Durability |
| **RTO** | Recovery Time Objective (how long to restore) |
| **RPO** | Recovery Point Objective (how much data can be lost) |
| **p95** | 95th percentile (95% of requests faster than this) |
| **QPS** | Queries Per Second |
| **NER** | Named Entity Recognition (extract entities like "Bosch") |
| **RBAC** | Role-Based Access Control |
| **SLA** | Service Level Agreement |

---

**Document Approved By:** CTO  
**Date:** June 2026  
**Next Review:** September 2026
