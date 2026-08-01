# Phase 1: Authentication, Tenancy, RBAC, and Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace caller-asserted identity with authenticated identity, so a user can reach their
own data and nothing else.

**Architecture:** Organizations own users through memberships that carry a role. Access is a
short-lived HS256 JWT; refresh is an opaque rotating token stored hashed and revocable. Every
request resolves identity server-side and re-checks that the user is still active, so revocation
is immediate. Domain tables keep their existing `user_id` string column, now holding
`users.public_id`, which keeps the migration additive for every downstream query.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic, PyJWT, argon2-cffi, Next.js 14,
Zustand, Axios, Pytest, Vitest.

## Global Constraints

- Identity is never accepted from the client. No `user_id` query parameter, body field, or path
  segment may determine whose data is returned.
- Every authenticated request re-checks `is_active` and `token_version` against the database, so
  revocation takes effect on the next request rather than at token expiry.
- Passwords are hashed with argon2id. Plaintext passwords are never logged, returned, or stored.
- Authentication failures return an identical response and take comparable time whether the email
  exists or not. No endpoint reveals account existence.
- Access tokens live 15 minutes; refresh tokens live 30 days, rotate on every use, and a reused
  refresh token revokes its entire family.
- The refresh token is delivered as an httpOnly, Secure, SameSite=Lax cookie. The access token is
  held in browser memory only, never in localStorage or sessionStorage.
- Audit records are append-only. No code path updates or deletes an `audit_log` row.
- Existing REST, WebSocket, and frontend contracts may change shape only where identity was
  previously a parameter. Response bodies otherwise stay backward compatible.
- Backend gate for every task: `pytest tests/ -q`, `black --check .`, `ruff check .`,
  `mypy api worker shared`. Frontend tasks additionally run `npm run test:run`,
  `npm run typecheck`, `npm run lint`, `npm run build`.
- Run pytest with `PYTHONPATH="$PWD/shared:$PWD"` outside a Poetry shell.
- Commit messages describe intent in plain language. No AI attribution trailers.

## Threat Model — What This Phase Closes

Verified present on `main` at the time of writing:

| Vulnerability | Location | Impact |
|---|---|---|
| Feed readable for any user | `api/routers/feed.py:49` | Any caller reads any user's personalized feed |
| Conversation messages unprotected | `api/routers/chat.py:102` | **No identity check whatsoever** — any conversation ID returns its full message history |
| Preferences writable for any user | `api/schemas/preference.py:30` | `user_id` is a request-body field; any caller overwrites any user's preferences |
| Chat WebSocket impersonation | `api/routers/chat.py:209` | `user_id` is a path segment on an unauthenticated socket |
| Article read-state forgeable | `api/routers/articles.py:68` | Any caller marks any user's articles read |
| Risk events readable for any user | `api/routers/risk_events.py:28` | Preference-derived risk feed exposed |
| CORS wildcard with credentials | `api/main.py:44` | `allow_origins=["*"]` with `allow_credentials=True` |

## File Structure

- `shared/procuresignal/models/auth.py`: Organization, User, Membership, RefreshToken, Role ORM models.
- `shared/procuresignal/models/audit.py`: AuditLog ORM model.
- `shared/procuresignal/auth/passwords.py`: argon2id hash and verify.
- `shared/procuresignal/auth/tokens.py`: access-token encode/decode, refresh-token mint/hash/rotate.
- `shared/procuresignal/auth/service.py`: registration, login, refresh, logout, session revocation.
- `shared/procuresignal/auth/audit.py`: append-only audit writer.
- `api/dependencies.py`: `get_current_user`, `require_role`, `get_client_context`.
- `api/routers/auth.py`: register, login, refresh, logout, me, revoke-all-sessions.
- `api/schemas/auth.py`: auth request/response contracts.
- `migrations/versions/g1h2i3_add_auth_tenancy_audit.py`: schema plus legacy identity backfill.
- `frontend/lib/auth.ts`: access-token memory store, refresh coordination, axios interceptor.
- `frontend/components/auth-gate.tsx`: login and registration UI replacing the email gate.
- `frontend/store/user.ts`: authenticated user state replacing the free-text `userId`.

---

### Task 1: Auth And Audit Schema

**Files:**
- Create: `shared/procuresignal/models/auth.py`
- Create: `shared/procuresignal/models/audit.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Create: `migrations/versions/g1h2i3_add_auth_tenancy_audit.py`
- Test: `tests/unit/test_auth_models.py`
- Test: `tests/integration/test_auth_migration.py`

**Interfaces:**
- Produces: `Organization`, `User`, `Membership`, `RefreshToken`, `AuditLog`, `Role` (StrEnum with
  `OWNER`, `ADMIN`, `MEMBER`, `VIEWER`). `User.public_id: str`, `User.token_version: int`,
  `User.is_active: bool`, `User.password_hash: str | None`.

**Design notes for the implementer:**

Domain tables (`user_news_preferences`, `user_news_feed`, `chat_conversations`, `chat_messages`)
keep their `user_id: String(100)` column. It now holds `users.public_id`, a uuid4 hex string.
This keeps the change additive for every existing query.

The migration must rewrite legacy values. Existing rows hold email addresses. For each distinct
legacy `user_id`, create a placeholder `User` with that email, a fresh `public_id`,
`password_hash = NULL`, and `is_active = False`, then rewrite the four domain tables to the new
`public_id`.

Placeholders are deliberately inactive and registration must **not** auto-claim them. Claiming a
placeholder by registering its email would let anyone inherit a colleague's feed and chat history.
Linking is a deliberate admin action, added only if it is ever needed.

- [ ] **Step 1: Write the failing model test**

```python
# tests/unit/test_auth_models.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Membership, Organization, Role, User


async def test_membership_is_unique_per_user_and_org(session: AsyncSession) -> None:
    org = Organization(public_id="o1", name="Acme", slug="acme")
    user = User(public_id="u1", email="buyer@acme.com", password_hash="x")
    session.add_all([org, user])
    await session.flush()

    session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.MEMBER))
    await session.flush()

    session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.ADMIN))
    with pytest.raises(Exception):
        await session.flush()


async def test_user_defaults_are_secure(session: AsyncSession) -> None:
    user = User(public_id="u2", email="new@acme.com")
    session.add(user)
    await session.flush()

    assert user.password_hash is None
    assert user.is_active is True
    assert user.token_version == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/unit/test_auth_models.py -q --no-cov`
Expected: FAIL with `ImportError: cannot import name 'Organization'`

- [ ] **Step 3: Write the models**

```python
# shared/procuresignal/models/auth.py
"""Identity, tenancy, and session models."""

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Organization(BaseModel):
    __tablename__ = "organizations"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class User(BaseModel):
    __tablename__ = "users"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumping this invalidates every outstanding access token for the user.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("idx_users_email", "email"),)


class Membership(BaseModel):
    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default=Role.MEMBER, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
        Index("idx_membership_user", "user_id"),
    )


class RefreshToken(BaseModel):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Only the hash is stored, so a database leak does not yield usable sessions.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Rotation family: reuse of a rotated token revokes every descendant.
    family_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("idx_refresh_user", "user_id"),
        Index("idx_refresh_family", "family_id"),
    )
```

```python
# shared/procuresignal/models/audit.py
"""Append-only audit trail."""

from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AuditLog(BaseModel):
    """One recorded action. Rows are inserted and never updated or deleted."""

    __tablename__ = "audit_log"

    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Recorded separately so the trail survives actor deletion.
    actor_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("idx_audit_org_created", "organization_id", "created_at"),
        Index("idx_audit_actor", "actor_user_id"),
        Index("idx_audit_action", "action"),
    )
```

Export all six names from `shared/procuresignal/models/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/unit/test_auth_models.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Write the migration test**

```python
# tests/integration/test_auth_migration.py
async def test_legacy_user_ids_are_rewritten_to_public_ids(migrated_session) -> None:
    """Legacy email identities become inactive placeholder users, and domain rows follow them."""
    users = (await migrated_session.execute(select(User))).scalars().all()
    placeholder = next(u for u in users if u.email == "legacy@acme.com")

    assert placeholder.is_active is False
    assert placeholder.password_hash is None
    assert placeholder.public_id != "legacy@acme.com"

    pref = (await migrated_session.execute(select(UserNewsPreference))).scalars().one()
    assert pref.user_id == placeholder.public_id
```

- [ ] **Step 6: Write the migration**

Create tables, then backfill in the same transaction: select distinct `user_id` from each of the
four domain tables, insert a placeholder user per distinct value, and `UPDATE` each domain table
to the new `public_id`. Provide a working `downgrade()` that drops the new tables; the identity
rewrite is not reversible, and `downgrade()` must say so in a comment rather than pretend.

- [ ] **Step 7: Run the full gate and commit**

```bash
PYTHONPATH="$PWD/shared:$PWD" pytest tests/ -q --no-cov
black --check . && ruff check . && mypy api worker shared
git add shared/procuresignal/models migrations/versions tests/
git commit -m "Add organizations, users, memberships, sessions, and audit trail"
```

---

### Task 2: Password Hashing And Token Service

**Files:**
- Create: `shared/procuresignal/auth/passwords.py`
- Create: `shared/procuresignal/auth/tokens.py`
- Modify: `pyproject.toml` (add `pyjwt`, `argon2-cffi`)
- Test: `tests/unit/test_auth_passwords.py`
- Test: `tests/unit/test_auth_tokens.py`

**Interfaces:**
- Produces: `hash_password(str) -> str`, `verify_password(str, str | None) -> bool`,
  `encode_access_token(AccessClaims) -> str`, `decode_access_token(str) -> AccessClaims`,
  `mint_refresh_token() -> tuple[str, str]` (plaintext, sha256 hex), `hash_refresh_token(str) -> str`.
- `AccessClaims` is a frozen dataclass: `subject`, `organization`, `role`, `token_version`, `jti`.

**Design notes:**

`pyjwt` 2.12.1 already resolves in `poetry.lock` as a transitive dependency, but relying on that is
fragile — declare it explicitly. Poetry is not installed globally; use an isolated environment:

```bash
python -m venv /tmp/poetry-env && /tmp/poetry-env/bin/pip install "poetry==2.2.1"
/tmp/poetry-env/bin/poetry add pyjwt argon2-cffi
```

`verify_password` must accept `None` (placeholder users have no password) and must still perform a
dummy hash comparison in that case, so a missing password takes the same time as a wrong one.
Without this, response timing reveals which accounts exist.

`decode_access_token` must pin `algorithms=["HS256"]`. Accepting the token's own `alg` header is the
classic algorithm-confusion vulnerability.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_auth_passwords.py
from procuresignal.auth.passwords import hash_password, verify_password


def test_hash_is_argon2id_and_salted() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2id$")
    assert first != second  # distinct salts
    assert verify_password("correct horse", first)
    assert not verify_password("wrong", first)


def test_absent_password_never_verifies() -> None:
    """Placeholder users carry no password and must not be loggable-in."""
    assert not verify_password("anything", None)
    assert not verify_password("anything", "")
```

```python
# tests/unit/test_auth_tokens.py
import pytest

from procuresignal.auth.tokens import (
    AccessClaims, decode_access_token, encode_access_token, hash_refresh_token, mint_refresh_token,
)

CLAIMS = AccessClaims(subject="u1", organization="o1", role="member", token_version=3, jti="j1")


def test_access_token_round_trips() -> None:
    assert decode_access_token(encode_access_token(CLAIMS)) == CLAIMS


def test_rejects_alg_none_confusion(monkeypatch) -> None:
    """A token signed with 'none' must never be accepted."""
    import jwt
    forged = jwt.encode({"sub": "attacker", "tv": 0}, key="", algorithm="none")
    with pytest.raises(Exception):
        decode_access_token(forged)


def test_refresh_token_is_stored_only_as_a_hash() -> None:
    plaintext, digest = mint_refresh_token()
    assert len(plaintext) >= 43           # >= 256 bits, urlsafe base64
    assert digest == hash_refresh_token(plaintext)
    assert plaintext not in digest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/unit/test_auth_passwords.py tests/unit/test_auth_tokens.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'procuresignal.auth'`

- [ ] **Step 3: Implement both modules**

```python
# shared/procuresignal/auth/passwords.py
"""Argon2id password hashing."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()
# Compared against when no password exists, so absent and wrong cost the same time.
_DUMMY_HASH = _hasher.hash("procuresignal-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify a password, taking comparable time whether or not a hash exists."""
    candidate = stored_hash or _DUMMY_HASH
    try:
        _hasher.verify(candidate, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return bool(stored_hash)
```

```python
# shared/procuresignal/auth/tokens.py
"""Access-token encoding and refresh-token minting."""

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import jwt

_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)


@dataclass(frozen=True)
class AccessClaims:
    subject: str
    organization: str
    role: str
    token_version: int
    jti: str


def _secret() -> str:
    secret = os.getenv("AUTH_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise RuntimeError("AUTH_SECRET_KEY must be set to at least 32 characters")
    return secret


def encode_access_token(claims: AccessClaims, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": claims.subject,
            "org": claims.organization,
            "role": claims.role,
            "tv": claims.token_version,
            "jti": claims.jti,
            "iat": issued,
            "exp": issued + ACCESS_TOKEN_TTL,
        },
        _secret(),
        algorithm=_ALGORITHM,
    )


def decode_access_token(token: str) -> AccessClaims:
    # algorithms is pinned; trusting the token's own alg header allows algorithm confusion.
    payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    return AccessClaims(
        subject=payload["sub"],
        organization=payload["org"],
        role=payload["role"],
        token_version=int(payload["tv"]),
        jti=payload["jti"],
    )


def hash_refresh_token(plaintext: str) -> str:
    return sha256(plaintext.encode("utf-8")).hexdigest()


def mint_refresh_token() -> tuple[str, str]:
    """Return (plaintext, hash). Only the hash is ever persisted."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_refresh_token(plaintext)
```

- [ ] **Step 4: Run tests to verify they pass, then run the full gate and commit**

```bash
PYTHONPATH="$PWD/shared:$PWD" pytest tests/ -q --no-cov
black --check . && ruff check . && mypy api worker shared
git commit -am "Add argon2 password hashing and signed access tokens"
```

---

### Task 3: Authentication Dependencies And Audit Writer

**Files:**
- Create: `shared/procuresignal/auth/audit.py`
- Modify: `api/dependencies.py`
- Test: `tests/unit/test_auth_dependencies.py`
- Test: `tests/unit/test_audit_log.py`

**Interfaces:**
- Consumes: `decode_access_token`, `AccessClaims` (Task 2); `User`, `Membership`, `AuditLog` (Task 1).
- Produces: `AuthenticatedUser` frozen dataclass (`id: int`, `public_id: str`, `email: str`,
  `organization_id: int`, `organization_public_id: str`, `role: Role`);
  `get_current_user(...) -> AuthenticatedUser`; `require_role(*roles) -> Callable`;
  `record_audit(session, *, action, actor, outcome, ...) -> None`.

**Design notes:**

`get_current_user` decodes the token, then loads the user and membership from the database and
rejects the request if `is_active` is false or `token_version` does not match the `tv` claim. This
costs one indexed query per request and is what makes revocation immediate rather than
delayed until token expiry. That trade is deliberate.

`require_role` compares against an ordered hierarchy — `OWNER > ADMIN > MEMBER > VIEWER` — so
`require_role(Role.MEMBER)` admits admins and owners. Equality checks would force every call site
to list every superior role, which drifts.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_auth_dependencies.py
import pytest
from fastapi import HTTPException

from api.dependencies import get_current_user


async def test_rejects_token_when_version_was_bumped(session, active_user, token_for) -> None:
    """Bumping token_version revokes outstanding access tokens on the next request."""
    token = token_for(active_user)
    active_user.token_version += 1
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=token, session=session)
    assert exc.value.status_code == 401


async def test_rejects_deactivated_user(session, active_user, token_for) -> None:
    token = token_for(active_user)
    active_user.is_active = False
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=token, session=session)
    assert exc.value.status_code == 401


async def test_viewer_is_refused_member_only_route(session, viewer_user) -> None:
    from procuresignal.models import Role
    from api.dependencies import require_role

    with pytest.raises(HTTPException) as exc:
        await require_role(Role.MEMBER)(current_user=viewer_user)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run to verify failure, then implement**

`get_current_user` reads the bearer credential via `fastapi.security.HTTPBearer`, decodes it, and
loads user plus membership in one joined query. Every rejection path raises
`HTTPException(401, "Not authenticated")` with an identical body.

`record_audit` inserts an `AuditLog` row and never updates one. It must accept a `detail` dict and
scrub any key named `password`, `token`, `secret`, or `authorization` before persisting.

- [ ] **Step 3: Write the audit scrubbing test**

```python
# tests/unit/test_audit_log.py
async def test_audit_detail_never_persists_credentials(session, actor) -> None:
    await record_audit(
        session, action="user.login", actor=actor, outcome="success",
        detail={"email": "a@b.com", "password": "hunter2", "token": "abc"},
    )
    row = (await session.execute(select(AuditLog))).scalars().one()
    assert row.detail["email"] == "a@b.com"
    assert "hunter2" not in str(row.detail)
    assert "abc" not in str(row.detail)
```

- [ ] **Step 4: Run the full gate and commit**

```bash
git commit -am "Resolve request identity server-side and record audited actions"
```

---

### Task 4: Authentication Router

**Files:**
- Create: `api/routers/auth.py`
- Create: `api/schemas/auth.py`
- Create: `shared/procuresignal/auth/service.py`
- Modify: `api/main.py`
- Test: `tests/integration/test_auth_api.py`

**Interfaces:**
- Produces: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`,
  `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/revoke-all-sessions`.

**Design notes:**

Registration creates an organization and an `OWNER` membership when the email's domain is new, and
a `MEMBER` membership in the existing organization otherwise. Registration must never activate an
existing placeholder user — return the same generic success either way, and audit the attempt.

`/refresh` reads the token from the httpOnly cookie, not the body. On rotation, mark the presented
token revoked and issue a new one in the same family. If a **revoked** token is presented, revoke
the entire family — that is the signature of a stolen token being replayed.

Login and register both set the refresh cookie with `httponly=True`, `secure=True`,
`samesite="lax"`, and `path="/api/auth"`.

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_auth_api.py
async def test_login_response_is_identical_for_unknown_and_wrong_password(client) -> None:
    """Neither status nor body may reveal whether an account exists."""
    unknown = await client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "p"})
    wrong = await client.post("/api/auth/login", json={"email": "real@x.com", "password": "bad"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_refresh_token_reuse_revokes_the_whole_family(client, registered) -> None:
    first = await client.post("/api/auth/refresh")
    assert first.status_code == 200
    # Replay the original, already-rotated cookie.
    replayed = await client.post("/api/auth/refresh", cookies=registered.original_cookie)
    assert replayed.status_code == 401
    # The legitimately rotated token is now dead too.
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_refresh_token_is_httponly_and_not_in_body(client) -> None:
    resp = await client.post("/api/auth/login", json={"email": "real@x.com", "password": "good"})
    cookie = resp.cookies.jar._cookies
    assert "refresh" not in resp.json()
    assert 'HttpOnly' in resp.headers["set-cookie"]
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -am "Add registration, login, refresh rotation, and logout"
```

---

### Task 5: Move Existing Routes Onto Authenticated Identity

**Files:**
- Modify: `api/routers/feed.py`, `api/routers/articles.py`, `api/routers/chat.py`,
  `api/routers/preferences.py`, `api/routers/risk_events.py`, `api/routers/signals.py`
- Modify: `api/schemas/preference.py` (remove `user_id` field)
- Test: `tests/integration/test_tenant_isolation.py`

**This task closes every vulnerability in the threat model table above.**

Replace `user_id: str = Query(...)` with `current_user: AuthenticatedUser = Depends(get_current_user)`
and use `current_user.public_id`. Remove `user_id` from `PreferenceUpdate` and every other request
schema — identity comes from the token, never the payload.

`GET /api/chat/conversations/{conversation_id}/messages` currently has no ownership check at all.
It must load the conversation, compare `conversation.user_id` to `current_user.public_id`, and
return **404** — not 403 — when they differ, so the endpoint does not confirm that a conversation
ID exists.

- [ ] **Step 1: Write the failing isolation test — one case per vulnerability**

```python
# tests/integration/test_tenant_isolation.py
import pytest

CROSS_TENANT_READS = [
    ("get", "/api/feed", None),
    ("get", "/api/risk-events", None),
    ("get", "/api/preferences", None),
]


@pytest.mark.parametrize(("method", "path", "body"), CROSS_TENANT_READS)
async def test_routes_never_return_another_users_data(client, alice, bob, method, path, body):
    """Alice's token must return Alice's rows regardless of any parameter Bob's data uses."""
    resp = await getattr(client, method)(path, headers=alice.headers)
    assert resp.status_code == 200
    assert bob.public_id not in resp.text


async def test_conversation_messages_reject_other_users(client, alice, bob_conversation):
    resp = await client.get(
        f"/api/chat/conversations/{bob_conversation.id}/messages", headers=alice.headers
    )
    # 404, not 403: a 403 would confirm the conversation exists.
    assert resp.status_code == 404


async def test_preferences_cannot_be_written_for_another_user(client, alice, bob):
    resp = await client.post(
        "/api/preferences",
        headers=alice.headers,
        json={"user_id": bob.public_id, "interested_categories": ["logistics"]},
    )
    # The field is gone from the schema, so it is ignored rather than honoured.
    assert resp.status_code in (200, 422)
    assert await bob.preferences() != ["logistics"]


async def test_every_user_scoped_route_requires_a_token(client):
    for method, path, _ in CROSS_TENANT_READS:
        assert (await getattr(client, method)(path)).status_code == 401
```

- [ ] **Step 2: Run to confirm failures, migrate each router, verify green**

- [ ] **Step 3: Run the full gate and commit**

```bash
git commit -am "Serve user data from the authenticated session instead of a query parameter"
```

---

### Task 6: WebSocket Authentication

**Files:**
- Modify: `api/routers/chat.py:209`
- Test: `tests/integration/test_chat_ws.py`

**Design notes:**

The route is `/ws/chat/{user_id}/{conversation_id}` — identity in the path on an unauthenticated
socket. Change it to `/ws/chat/{conversation_id}` and authenticate before `websocket.accept()`.

Browsers cannot set `Authorization` headers on WebSocket connections. Accept the access token via
the `Sec-WebSocket-Protocol` header rather than a query parameter, because query strings land in
access logs and proxy logs. Reject with close code 4401 before accepting when the token is absent,
invalid, or the conversation belongs to someone else.

- [ ] **Step 1: Write the failing tests**

```python
async def test_socket_closes_unauthenticated_connections(ws_client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect("/ws/chat/conv-1"):
            pass
    assert exc.value.code == 4401


async def test_socket_rejects_another_users_conversation(ws_client, alice_token, bob_conversation):
    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(
            f"/ws/chat/{bob_conversation.id}", subprotocols=["bearer", alice_token]
        ):
            pass
    assert exc.value.code == 4401
```

- [ ] **Step 2: Implement, verify green, run the full gate, and commit**

```bash
git commit -am "Authenticate chat sockets before accepting the connection"
```

---

### Task 7: Frontend Authentication

**Files:**
- Create: `frontend/lib/auth.ts`
- Create: `frontend/components/auth-gate.tsx`
- Modify: `frontend/store/user.ts`, `frontend/lib/api.ts`, `frontend/components/app-shell.tsx`,
  `frontend/lib/ws.ts`
- Test: `frontend/__tests__/auth-gate.test.tsx`, `frontend/__tests__/auth.test.ts`

**Design notes:**

The access token lives in a module-level variable, never in `localStorage` — anything in
`localStorage` is readable by any XSS payload. The refresh cookie is httpOnly, so JavaScript cannot
read it by design, and the browser attaches it automatically.

The axios response interceptor retries a single time on 401 after refreshing. Concurrent 401s must
share one in-flight refresh promise, or a page with six parallel requests fires six rotations and
the reuse detector revokes the family — logging the user out for behaving normally. This is the
subtle failure mode in this task; the test below exists specifically for it.

`frontend/store/user.ts` currently persists a free-text `userId` to `localStorage`. Remove that
field entirely — identity now comes from `GET /api/auth/me`. Keep `platformLanguage` persisted.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/__tests__/auth.test.ts
it("shares one refresh across concurrent 401s", async () => {
  const refresh = vi.fn().mockResolvedValue({ access: "new" });
  const results = await Promise.all([call(), call(), call()]);
  expect(refresh).toHaveBeenCalledTimes(1);   // not three
  expect(results.every((r) => r.ok)).toBe(true);
});

it("never writes the access token to storage", async () => {
  await login("a@b.com", "pw");
  expect(JSON.stringify(localStorage)).not.toContain("access");
  expect(JSON.stringify(sessionStorage)).not.toContain("access");
});

it("stops retrying after one failed refresh", async () => {
  const refresh = vi.fn().mockRejectedValue(new Error("expired"));
  await expect(call()).rejects.toThrow();
  expect(refresh).toHaveBeenCalledTimes(1);   // no infinite loop
});
```

- [ ] **Step 2: Implement, verify green**

- [ ] **Step 3: Run the frontend gate and commit**

```bash
cd frontend && npm run test:run && npm run typecheck && npm run lint && npm run build
git commit -am "Replace the email gate with real sign-in and token refresh"
```

---

### Task 8: CORS Lockdown And Login Rate Limiting

**Files:**
- Modify: `api/main.py:44`
- Create: `api/rate_limit.py`
- Modify: `.env.example`, `docker-compose.yml`
- Test: `tests/unit/test_cors.py`, `tests/unit/test_rate_limit.py`

**Design notes:**

`allow_origins=["*"]` with `allow_credentials=True` is invalid for credentialed requests — browsers
reject the combination outright, so cookie-based refresh cannot work until this is fixed. Read
allowed origins from `CORS_ALLOWED_ORIGINS`, defaulting to `http://localhost:3000`.

Rate limiting is an in-process sliding window keyed on client IP plus submitted email. This is
single-process only and resets on restart; that is an accepted Phase 1 limit, replaced by the
Redis-backed limiter in Phase 3. Mark it:

```python
# ponytail: in-process window, single worker only. Redis-backed limiter lands in Phase 3.
```

Both `AUTH_SECRET_KEY` and `CORS_ALLOWED_ORIGINS` go in `.env.example` and all three
retrieval-capable services in `docker-compose.yml`. The API must refuse to start when
`AUTH_SECRET_KEY` is missing — a default secret in production is worse than no auth, because it
looks like auth.

- [ ] **Step 1: Write the failing tests**

```python
def test_wildcard_origin_is_never_allowed_with_credentials(client):
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") != "*"
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


def test_api_refuses_to_start_without_auth_secret(monkeypatch):
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        build_app()


def test_repeated_failed_logins_are_throttled(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert client.post(
        "/api/auth/login", json={"email": "a@b.com", "password": "wrong"}
    ).status_code == 429
```

- [ ] **Step 2: Implement, verify green, run the full gate, commit, and push**

```bash
git commit -am "Restrict CORS to configured origins and throttle failed logins"
git push origin main
```

---

## Self-Review

**Spec coverage:** every row of the threat model maps to Task 5 (REST identity), Task 6 (socket
identity), or Task 8 (CORS). Roadmap D1 — self-hosted, SSO-shaped — is satisfied by the
organization/user/membership split in Task 1; an SSO adapter later populates the same tables
without touching the schema. Token revocation is Task 1 (`token_version`) plus Task 3 (per-request
check). Audit logging is Tasks 1 and 3.

**Deliberately out of scope, with reasons:**

- **Organization columns on `user_news_feed` / `user_news_preferences` / chat tables.** Every
  user-scoped query already filters by `user_id`, so authenticating that identity is what enforces
  isolation. Org columns become necessary in Phase 4 when watchlists are shared across a team, and
  adding them then is additive.
- **SSO and SCIM.** Adapters over the Task 1 schema, gated on a customer and an IdP tenant.
- **Redis-backed rate limiting.** Phase 3, alongside the rest of the shared operational furniture.
- **Password reset by email.** Requires the SMTP transport that Phase 4 introduces. Until then an
  admin resets a password directly, and this is a genuine gap for real users — the first thing to
  build in Phase 4.

**Type consistency:** `AuthenticatedUser.public_id` is the string written to and compared against
every domain table's `user_id`. `Role` is the same `StrEnum` in the model, the dependency, and the
membership column. `AccessClaims.token_version` is the `int` compared against `User.token_version`.
