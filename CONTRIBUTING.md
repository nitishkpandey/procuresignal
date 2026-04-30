# Contributing to ProcureSignal

## Development Workflow

### 1. Create a phase branch

```bash
git checkout -b phase/N-description
```

### 2. Make atomic commits

```bash
git commit -m "feat(scope): description"
git commit -m "test(scope): add tests"
```

### 3. Before pushing, run quality checks

```bash
poetry install
black . && ruff check . --fix
mypy api worker
pytest tests/ -v
```

### 4. Push and open PR

```bash
git push origin phase/N-description
```

Go to GitHub and open a PR with a detailed description.

### 5. Wait for CI

GitHub Actions will run:
- Linting (Ruff + Black)
- Type checking (MyPy)
- Tests (pytest)
- Build (Docker images)

All must pass before merge.

## Code Quality Standards

- ✓ Type hints required (`mypy` must pass)
- ✓ Tests required (aim for 70%+ coverage)
- ✓ Conventional commits (`feat:`, `fix:`, `test:`, etc.)
- ✓ No `print()` or `console.log()` in production code
- ✓ Docstrings for all public functions

## Running Locally

```bash
# Start services
docker-compose up -d

# Install dependencies
poetry install

# Run tests
pytest tests/ -v

# Run API
poetry run uvicorn api.main:app --reload

# Run worker
poetry run celery -A worker.tasks worker --loglevel=info
```

## Questions?

Open an issue or refer to [GITHUB_WORKFLOW_CHECKLIST.md](GITHUB_WORKFLOW_CHECKLIST.md).
