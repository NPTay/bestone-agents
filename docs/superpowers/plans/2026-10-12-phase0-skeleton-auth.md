# Giai đoạn 0 — Khung dự án & Đăng nhập: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable skeleton of bestone-agents: config, full DB schema with migrations, prompt/knowledge loader, self-hosted login with roles `giam_doc`/`ke_toan`, health endpoint, Docker deployment (app + db + caddy) and daily backup.

**Architecture:** One FastAPI process (Jinja2 server-rendered pages) on SQLAlchemy 2 + Alembic. Auth is in-app: argon2 password hashes in `users`, opaque random session tokens (sha256 stored in `sessions`) in an HttpOnly cookie, HMAC CSRF tokens on every form. Models use portable types (JSON with JSONB variant, generic `Uuid`) so the test suite runs on SQLite locally (no Docker on the dev machine); production runs PostgreSQL 16 in Docker.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, psycopg 3, pydantic-settings, Jinja2, Tailwind CDN, argon2-cffi, httpx, pytest, respx, ruff, mypy.

**Spec:** `docs/07_BUILD_PLAN_TASKS.md` (Giai đoạn 0), `docs/08_LOGIN_DASHBOARD.md`, `docs/04_DATA_SCHEMA.md`, `docs/03_TECH_STACK_REPO_STRUCTURE.md`, `docs/06_DEPLOYMENT_VPS.md`, `CLAUDE.md`.

## Global Constraints

- Python 3.12; `ruff` + `mypy` clean; full type hints.
- UI text Vietnamese; code, identifiers, comments English (`CLAUDE.md` rule 7).
- No secret in git; `.env.example` holds variable names only (values only for non-secret defaults already listed in `docs/06`).
- Never log passwords, in any form, including error logs (`docs/08` §5).
- Roles exactly `giam_doc`, `ke_toan` — no others (`docs/08` §6).
- No self sign-up, no SSO, no 2FA, no email password reset (`docs/08` §6). `users.totp_secret` exists but is unused.
- All timestamps stored UTC (`timestamptz`), displayed `Asia/Ho_Chi_Minh`.
- Every table has `id` (uuid pk), `created_at`, `updated_at`.
- Single generic login error text: `Sai tên đăng nhập hoặc mật khẩu`.
- Lockout: 5 consecutive failures within 15 minutes → `locked_until = now + 15 min`, `audit_log` entry, Telegram alert level `warn`.
- Locked message: `Tài khoản tạm khóa, thử lại sau {HH:MM}` (local time of `locked_until`).
- Session: not remembered → browser-session cookie (no Max-Age) and server expiry after 8 h of inactivity (`SESSION_MAX_AGE_SECONDS=28800`); remembered → cookie Max-Age and server expiry 30 days (`SESSION_REMEMBER_DAYS=30`).
- Cookie flags: `HttpOnly`, `Secure` (configurable off only when `APP_ENV=dev`), `SameSite=Lax`; name from `SESSION_COOKIE_NAME` (default `bestone_session`).
- Login IP rate limit: max 10 POST `/login` per minute per client IP → HTTP 429.
- Post-login redirect: `giam_doc` → `/dashboard`, `ke_toan` → `/reports`. Wrong role → 403 (not silent). No session → 303 to `/login`.
- `AUTONOMY_LEVEL` default `draft_only`; seed `settings` rows `AUTONOMY_LEVEL=draft_only`, `KILL_SWITCH=false`.

## Review Focus

1. **Unknown username timing** — login with a non-existent username must still run one argon2 verify (dummy hash) and return the same message; test in Task 6 asserts identical response body for unknown user vs. wrong password.
2. **Deactivated user with live session** — setting `is_active=false` must invalidate access on the next request, not only at next login; test in Task 5.
3. **Password change / reset kills other sessions and unlocks** — after `reset_password` CLI or change-password, old session tokens stop working and `locked_until`/`failed_attempts` are cleared; tests in Tasks 4 and 7.
4. **Stale failure counter** — 4 failures, wait >15 min, 1 more failure must NOT lock (window restarts); test in Task 6.
5. **Proxy IP** — behind Caddy all requests come from the proxy IP; rate limit must key on the real client (`X-Forwarded-For` honoured only via uvicorn `--proxy-headers --forwarded-allow-ips` set to the Docker network); test in Task 6 sends two different forwarded IPs through a trusted-proxy setup and asserts independent limits.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore`, `.env.example` | deps, tooling, env names |
| `app/config.py` | `Settings` (pydantic-settings) + `get_settings()` |
| `app/clock.py` | `utcnow()` — single patch point for time in tests |
| `app/main.py` | `create_app()` factory, mounts routers, templates, exception handlers |
| `app/db/base.py` | `Base`, `TimestampMixin`, portable type aliases `JSONType` |
| `app/db/models.py` | all tables of `docs/04` |
| `app/db/session.py` | engine, `SessionLocal`, `get_db()` dependency |
| `migrations/` | Alembic env + initial revision (schema + settings seed) |
| `app/llm/prompts.py` | load ```prompt blocks from `agents/*.md`, load `knowledge/*.md` |
| `app/knowledge/ingest.py` | CLI validation of knowledge + agent prompts |
| `app/auth/passwords.py` | argon2 hash/verify, dummy verify |
| `app/auth/session.py` | create / resolve / destroy sessions, cookie helpers |
| `app/auth/csrf.py` | CSRF cookie + HMAC token, `verify_csrf` dependency |
| `app/auth/ratelimit.py` | in-memory sliding window per IP |
| `app/auth/dependencies.py` | `require_login`, `require_role` |
| `app/auth/service.py` | `authenticate()` with lockout logic |
| `app/audit.py` | `write_audit()` |
| `app/integrations/notify.py` | `send_alert()` → `alerts` row + Telegram |
| `app/routers/auth.py` | `/login`, `/logout`, `/account/change-password` |
| `app/routers/dashboard.py` | `/dashboard`, `/dashboard/users` (account management) |
| `app/routers/reports.py` | `/reports` placeholder |
| `app/routers/admin_api.py` | `/admin_api/ping` placeholder (giam_doc) |
| `app/routers/health.py` | `/health` |
| `app/cli/create_admin.py`, `app/cli/reset_password.py` | one-off account CLIs |
| `app/templates/` | `base.html`, `login.html`, `change_password.html`, `dashboard/index.html`, `dashboard/users.html`, `reports/index.html`, `error.html` |
| `deploy/` | `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `entrypoint.sh`, `backup.sh`, `bootstrap.sh`, `rollback.md` |
| `tests/conftest.py` | SQLite (or `TEST_DATABASE_URL`) engine, `client`, user factories, frozen clock |

Decisions made here (builder's call, documented): list columns (`hashtags`, `sources`, `kb_refs`) are JSON arrays, not PG `ARRAY`, for SQLite test portability; account management page for `giam_doc` lives at `/dashboard/users` (create `ke_toan` account, activate/deactivate, reset password) because `docs/06` step 5 says Kế toán is created from the dashboard.

---

### Task 1: Project skeleton, config, health

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `.env.example`, `app/__init__.py`, `app/config.py`, `app/clock.py`, `app/main.py`, `app/routers/__init__.py`, `app/routers/health.py`, `tests/__init__.py`, `tests/test_health.py`

**Interfaces:**
- Produces: `Settings` fields (all from `docs/06` env list + `APP_ENV: Literal["dev","prod"]="prod"`, `TRUSTED_PROXY_IPS: str = "127.0.0.1"`); `get_settings() -> Settings` (lru_cache); `utcnow() -> datetime` (tz-aware UTC); `create_app(settings: Settings | None = None) -> FastAPI`.

- [ ] **Step 1: `git init`, write `.gitignore`** (`.venv/`, `.env`, `__pycache__/`, `*.db`, `backups/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`). Do not ignore `Picture/` without asking — leave it untracked by adding `Picture/` and `Tai Lieu/` to `.gitignore` (binary company assets, not code).
- [ ] **Step 2: `pyproject.toml`** with deps: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2.0`, `alembic`, `psycopg[binary]>=3.1`, `pydantic-settings`, `jinja2`, `python-multipart`, `argon2-cffi`, `httpx`; extra `dev`: `pytest`, `respx`, `ruff`, `mypy`. ruff line-length 100; pytest `testpaths=["tests"]`.
- [ ] **Step 3: Create venv and install**

Run: `py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
Expected: install succeeds.

- [ ] **Step 4: `.env.example`** — exact list from `docs/06` plus `APP_ENV=prod`, `TRUSTED_PROXY_IPS=`, `APP_DOMAIN=`.
- [ ] **Step 5: Write failing test `tests/test_health.py`**

```python
def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}

def test_health_db_down(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.check_db", lambda db: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["db"] == "error"
```
(`client` fixture comes from Task 2's conftest; in this task create a minimal `tests/conftest.py` building the app with an in-memory SQLite `DATABASE_URL`; Task 2 extends it.)

- [ ] **Step 6: Run — expect FAIL** `.venv/Scripts/pytest tests/test_health.py -v`
- [ ] **Step 7: Implement** `config.py`, `clock.py`, `main.py`, `routers/health.py` (`check_db(db) -> bool` runs `SELECT 1`; scheduler and Meta-token checks are added in later phases).
- [ ] **Step 8: Run — expect PASS**, then `ruff check . && mypy app`
- [ ] **Step 9: Commit** `feat: project skeleton with config and /health`

### Task 2: Database models and Alembic

**Files:**
- Create: `app/db/__init__.py`, `app/db/base.py`, `app/db/models.py`, `app/db/session.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_initial.py`, `tests/test_models.py`, `tests/test_migrations.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces: `Base`; models `User, UserSession (table `sessions`), ResearchItem, Post, PostMetric, Contact, Conversation, Message, Lead, Job, Alert, LlmUsage, Setting, AuditLog` with columns exactly per `docs/04` (enums as `sqlalchemy.Enum(..., name=...)`); `Role` str-enum (`giam_doc`, `ke_toan`); `get_db() -> Iterator[orm.Session]`; `make_engine(url: str) -> Engine`.
- conftest produces fixtures: `engine`, `db` (orm.Session), `client` (TestClient with `get_db` overridden), `make_user(username="gd", password="Matkhau#2026", role=Role.giam_doc, is_active=True) -> User`, `frozen_now` (monkeypatches `app.clock.utcnow`, returns a mutable holder with `.advance(timedelta)`).

- [ ] **Step 1: Failing test `tests/test_models.py`**

```python
EXPECTED = {"users","sessions","research_items","posts","post_metrics","contacts",
            "conversations","messages","leads","jobs","alerts","llm_usage","settings","audit_log"}

def test_all_tables_exist(engine):
    assert EXPECTED <= set(sa.inspect(engine).get_table_names())

def test_unique_constraints(db):
    db.add(User(username="a", password_hash="x", role=Role.giam_doc)); db.commit()
    db.add(User(username="a", password_hash="y", role=Role.ke_toan))
    with pytest.raises(sa.exc.IntegrityError): db.commit()
```
Plus one uniqueness test each for `research_items.source_url`, `messages.fb_mid`, `contacts.fb_psid`.

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement models.** `TimestampMixin`: `id = Uuid pk default uuid4`, `created_at`/`updated_at` `DateTime(timezone=True)` defaulting to `app.clock.utcnow`, `updated_at` onupdate. `JSONType = JSON().with_variant(JSONB(), "postgresql")`. Indexes per `docs/04` "Chỉ mục bắt buộc".
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Alembic.** `env.py` reads `DATABASE_URL` from `get_settings()`, `target_metadata = Base.metadata`. Generate `0001_initial` with `alembic revision --autogenerate` against an empty SQLite file, then add `op.bulk_insert` seeding `settings`: `AUTONOMY_LEVEL=draft_only`, `KILL_SWITCH=false`.
- [ ] **Step 6: Test `tests/test_migrations.py`**

```python
def test_upgrade_head_matches_models(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path/'m.db'}"
    monkeypatch.setenv("DATABASE_URL", url); get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    eng = sa.create_engine(url)
    assert EXPECTED <= set(sa.inspect(eng).get_table_names())
    with eng.connect() as c:
        rows = dict(c.execute(sa.text("select key, value from settings")).all())
    assert rows == {"AUTONOMY_LEVEL": "draft_only", "KILL_SWITCH": "false"}
```
- [ ] **Step 7: Run all tests — expect PASS**; `alembic check` on the temp DB reports no drift.
- [ ] **Step 8: Commit** `feat: database schema and initial migration`

### Task 3: Prompt & knowledge loader

**Files:**
- Create: `app/llm/__init__.py`, `app/llm/prompts.py`, `app/knowledge/__init__.py`, `app/knowledge/ingest.py`, `tests/test_prompts.py`

**Interfaces:**
- Produces: `AGENT_FILES: dict[str, str]` (`orchestrator→a0_orchestrator.md`, `research→a1_research.md`, `content→a2_content.md`, `publisher→a3_publisher.md`, `care→a4_customer_care.md`); `load_agent_prompt(agent: str, root: Path = PROJECT_ROOT) -> str` (text inside the first ```` ```prompt ```` fence, stripped; raises `PromptNotFoundError` if absent); `load_knowledge(root: Path = PROJECT_ROOT) -> dict[str, str]` (filename → content for `knowledge/*.md`); `ingest.main() -> int` (0 when every agent has a prompt and `bestone_knowledge_base.md` is non-empty, prints one summary line per file; 1 otherwise).

- [ ] **Step 1: Failing tests**

```python
def test_all_agents_have_prompt():
    for agent in AGENT_FILES:
        assert len(load_agent_prompt(agent)) > 50

def test_care_prompt_content():
    assert "TUYỆT ĐỐI không: báo giá" in load_agent_prompt("care")

def test_missing_block_raises(tmp_path):
    (tmp_path/"agents").mkdir(); (tmp_path/"agents"/"a0_orchestrator.md").write_text("# no block", encoding="utf-8")
    with pytest.raises(PromptNotFoundError): load_agent_prompt("orchestrator", root=tmp_path)

def test_knowledge_loaded():
    kb = load_knowledge()
    assert {"bestone_knowledge_base.md","brand_voice.md","content_pillars.md","guardrails_compliance.md"} <= kb.keys()

def test_ingest_ok():
    assert ingest.main() == 0
```
- [ ] **Step 2: Run — FAIL. Step 3: Implement** (read files as UTF-8). **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat: load agent prompts and knowledge base`

### Task 4: Passwords and account CLIs

**Files:**
- Create: `app/auth/__init__.py`, `app/auth/passwords.py`, `app/audit.py`, `app/cli/__init__.py`, `app/cli/create_admin.py`, `app/cli/reset_password.py`, `tests/test_passwords.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `hash_password(plain: str) -> str`; `verify_password(hash_: str, plain: str) -> bool` (never raises on mismatch); `dummy_verify() -> None` (verifies against a module-level precomputed hash); `validate_new_password(plain: str) -> str | None` (Vietnamese error or None; rule: ≥ 10 chars); `write_audit(db, actor_id: UUID | None, action: str, entity: str, entity_id: str | None, detail: dict) -> None`; `create_admin.main(argv: list[str] | None = None) -> int` reads `INITIAL_ADMIN_USERNAME`/`INITIAL_ADMIN_PASSWORD`, refuses (exit 1) if any `giam_doc` already exists; `reset_password.main(argv) -> int` takes `--username`, reads new password via `getpass` (prompt `Mật khẩu mới: ` twice), sets hash, clears `failed_attempts`, `last_failed_at`, `locked_until`, deletes all that user's `sessions`, writes audit `password_reset_cli`.

- [ ] **Step 1: Failing tests**

```python
def test_hash_roundtrip():
    h = hash_password("Matkhau#2026"); assert h.startswith("$argon2")
    assert verify_password(h, "Matkhau#2026") and not verify_password(h, "sai")

def test_create_admin_once(db_url_env, monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME","giamdoc"); monkeypatch.setenv("INITIAL_ADMIN_PASSWORD","Matkhau#2026")
    assert create_admin.main([]) == 0
    assert create_admin.main([]) == 1

def test_reset_password_unlocks_and_kills_sessions(db, make_user, monkeypatch):
    u = make_user(); u.failed_attempts = 5; u.locked_until = utcnow() + timedelta(minutes=10)
    db.add(UserSession(user_id=u.id, token_hash="h", expires_at=utcnow()+timedelta(hours=1))); db.commit()
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Matkhaumoi#2026")
    assert reset_password.main(["--username", u.username]) == 0
    db.refresh(u)
    assert u.failed_attempts == 0 and u.locked_until is None
    assert db.query(UserSession).filter_by(user_id=u.id).count() == 0
```
(`db_url_env` fixture: points `DATABASE_URL` at the test engine's file DB and runs `create_all`.)

- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS**
- [ ] **Step 5: Commit** `feat: password hashing and account CLIs`

### Task 5: Sessions, CSRF, role dependencies

**Files:**
- Create: `app/auth/session.py`, `app/auth/csrf.py`, `app/auth/dependencies.py`, `tests/test_session.py`, `tests/test_csrf.py`

**Interfaces:**
- Produces:
  - `create_session(db, user: User, remember: bool, ip: str | None, user_agent: str | None) -> str` (returns raw token `secrets.token_urlsafe(32)`; stores sha256 hex; `expires_at = now + 30 days` if remember else `now + SESSION_MAX_AGE_SECONDS`).
  - `resolve_session(db, raw_token: str | None) -> User | None` — None if missing/expired/user inactive; on success, for non-remember sessions slides `expires_at = now + 8h` and sets `last_seen_at`.
  - `destroy_session(db, raw_token: str) -> None`; `destroy_user_sessions(db, user_id: UUID, except_token: str | None = None) -> None`.
  - `set_session_cookie(response, token: str, remember: bool) -> None`; `clear_session_cookie(response) -> None`.
  - `CSRF_COOKIE = "bestone_csrf"`; `ensure_csrf_cookie(request, response) -> str` (returns form token = HMAC-SHA256(`SESSION_SECRET_KEY`, cookie value) hex); `verify_csrf(request) -> None` FastAPI dependency for POST, reads form field `csrf_token`, raises 403 on mismatch.
  - `require_login(request, db) -> User` — raises `LoginRequired` (handled in `main.py` → 303 `/login`); `require_role(*roles: Role) -> Callable[..., User]` → 403 when role not allowed.

- [ ] **Step 1: Failing tests**

```python
def test_session_expires_after_8h_idle(db, make_user, frozen_now):
    u = make_user(); tok = create_session(db, u, remember=False, ip=None, user_agent=None)
    frozen_now.advance(timedelta(hours=7, minutes=59)); assert resolve_session(db, tok) == u
    frozen_now.advance(timedelta(hours=7, minutes=59)); assert resolve_session(db, tok) == u  # sliding
    frozen_now.advance(timedelta(hours=8, minutes=1)); assert resolve_session(db, tok) is None

def test_remember_lasts_30_days(db, make_user, frozen_now):
    u = make_user(); tok = create_session(db, u, remember=True, ip=None, user_agent=None)
    frozen_now.advance(timedelta(days=29)); assert resolve_session(db, tok) == u
    frozen_now.advance(timedelta(days=2)); assert resolve_session(db, tok) is None

def test_inactive_user_rejected_immediately(db, make_user):
    u = make_user(); tok = create_session(db, u, remember=False, ip=None, user_agent=None)
    u.is_active = False; db.commit()
    assert resolve_session(db, tok) is None

def test_token_stored_hashed(db, make_user):
    tok = create_session(db, make_user(), remember=False, ip=None, user_agent=None)
    assert db.query(UserSession).one().token_hash != tok

def test_cookie_flags():
    resp = Response(); set_session_cookie(resp, "t", remember=False)
    c = resp.headers["set-cookie"].lower()
    assert "httponly" in c and "secure" in c and "samesite=lax" in c and "max-age" not in c
```
`tests/test_csrf.py`: POST to a test-only route with missing token → 403; with wrong token → 403; with token from `ensure_csrf_cookie` → 200.

- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS**
- [ ] **Step 5: Commit** `feat: server-side sessions, CSRF and role guards`

### Task 6: Login, lockout, rate limit, logout

**Files:**
- Create: `app/auth/service.py`, `app/auth/ratelimit.py`, `app/integrations/__init__.py`, `app/integrations/notify.py`, `app/routers/auth.py`, `app/templates/base.html`, `app/templates/login.html`, `app/templates/error.html`, `tests/test_login.py`, `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 4 `verify_password`, `dummy_verify`, `write_audit`; Task 5 session/csrf functions.
- Produces:
  - `AuthResult` dataclass: `user: User | None`, `error: Literal["invalid","locked"] | None`, `locked_until: datetime | None`.
  - `authenticate(db, username: str, password: str) -> AuthResult` — order: user lookup (unknown → `dummy_verify()`, `invalid`); `locked_until > now` → `locked` (password not checked); inactive → verify then `invalid`; wrong password → if `last_failed_at` older than 15 min reset counter to 0, increment, set `last_failed_at`; on reaching 5 set `locked_until = now+15min`, `write_audit(action="account_locked")`, `send_alert("warn", ...)`; correct → reset counters, `last_login_at = now`, `write_audit(action="login_success")`.
  - `send_alert(db, level: Literal["info","warn","urgent"], message: str) -> None` — inserts `alerts` row; if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ADMIN_CHAT_ID` set, POSTs `https://api.telegram.org/bot{token}/sendMessage` (timeout 10 s, failure logged not raised) and sets `delivered_at`. Message never contains passwords.
  - `RateLimiter(max_hits: int = 10, window_s: int = 60).hit(key: str) -> bool` (False when exceeded).
  - Routes: `GET /login` (renders form, sets CSRF cookie; already logged in → redirect by role), `POST /login` (fields `username`, `password`, `remember_me`, `csrf_token`), `POST /logout`.
- `login.html` per `docs/08` §2: centered card 360–400 px on light grey, heading `C.G. Engineering — Bestone Console`, labels `Tên đăng nhập`, `Mật khẩu` (show/hide toggle button), checkbox `Ghi nhớ đăng nhập`, full-width button `Đăng nhập`, small text `Quên mật khẩu? Liên hệ Giám đốc`, mobile responsive, no social login.

- [ ] **Step 1: Failing tests `tests/test_login.py`**

```python
GENERIC = "Sai tên đăng nhập hoặc mật khẩu"

def login(client, u, p, remember=False):
    token = csrf_of(client)  # GET /login, parse hidden csrf_token
    return client.post("/login", data={"username": u, "password": p, "csrf_token": token,
                       **({"remember_me": "on"} if remember else {})}, follow_redirects=False)

def test_giam_doc_redirects_to_dashboard(client, make_user):
    make_user(username="gd", role=Role.giam_doc)
    r = login(client, "gd", "Matkhau#2026"); assert r.status_code == 303 and r.headers["location"] == "/dashboard"

def test_ke_toan_redirects_to_reports(client, make_user):
    make_user(username="kt", role=Role.ke_toan)
    assert login(client, "kt", "Matkhau#2026").headers["location"] == "/reports"

def test_unknown_user_and_wrong_password_same_response(client, make_user):
    make_user(username="gd")
    a = login(client, "khongco", "x"); b = login(client, "gd", "x")
    assert a.status_code == b.status_code == 200
    assert GENERIC in a.text and GENERIC in b.text
    assert strip_csrf(a.text) == strip_csrf(b.text)

def test_lock_after_5_failures(client, make_user, frozen_now, respx_mock, db):
    tg = respx_mock.post(url__regex=r"https://api\.telegram\.org/.*").respond(200, json={"ok": True})
    make_user(username="gd")
    for _ in range(5): login(client, "gd", "x")
    r = login(client, "gd", "Matkhau#2026")
    assert "Tài khoản tạm khóa, thử lại sau" in r.text
    assert tg.called
    assert db.query(AuditLog).filter_by(action="account_locked").count() == 1
    frozen_now.advance(timedelta(minutes=15, seconds=1))
    assert login(client, "gd", "Matkhau#2026").status_code == 303

def test_failure_window_restarts(client, make_user, frozen_now):
    make_user(username="gd")
    for _ in range(4): login(client, "gd", "x")
    frozen_now.advance(timedelta(minutes=16))
    login(client, "gd", "x")
    assert login(client, "gd", "Matkhau#2026").status_code == 303

def test_inactive_user_cannot_login(client, make_user):
    make_user(username="gd", is_active=False)
    assert GENERIC in login(client, "gd", "Matkhau#2026").text

def test_login_without_csrf_rejected(client, make_user):
    make_user(username="gd")
    assert client.post("/login", data={"username": "gd", "password": "Matkhau#2026"}).status_code == 403

def test_rate_limit_per_ip(client):
    codes = [login(client, "x", "x").status_code for _ in range(11)]
    assert codes[-1] == 429

def test_rate_limit_keys_on_forwarded_client(proxied_client):
    # proxied_client: app run with trusted proxy = testclient IP
    for _ in range(10): login(proxied_client(xff="1.1.1.1"), "x", "x")
    assert login(proxied_client(xff="2.2.2.2"), "x", "x").status_code == 200

def test_logout_clears_session(client, make_user):
    make_user(username="gd"); login(client, "gd", "Matkhau#2026")
    client.post("/logout", data={"csrf_token": csrf_of(client)})
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"

def test_password_never_logged(client, make_user, caplog):
    make_user(username="gd"); login(client, "gd", "BiMat-XYZ-123")
    assert "BiMat-XYZ-123" not in caplog.text
```
Helpers `csrf_of`, `strip_csrf`, `proxied_client` live in `tests/conftest.py`. Rate limiter instance must be reset per test (fixture).

`tests/test_notify.py`: with Telegram env set, `send_alert` inserts `alerts` row with `delivered_at` set; with Telegram returning 500, row exists with `delivered_at` None and no exception.

- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS** (uvicorn proxy trust is configured in Task 9; in-app the limiter keys on `request.client.host`, which uvicorn rewrites from `X-Forwarded-For` only for trusted proxies — `proxied_client` simulates that by wrapping the app in `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(trusted_hosts=["testclient"])`.)
- [ ] **Step 5: Commit** `feat: login with lockout, rate limit and logout`

### Task 7: Dashboard shells, account management, change password

**Files:**
- Create: `app/routers/dashboard.py`, `app/routers/reports.py`, `app/routers/admin_api.py`, `app/templates/dashboard/index.html`, `app/templates/dashboard/users.html`, `app/templates/reports/index.html`, `app/templates/change_password.html`, `tests/test_roles.py`, `tests/test_accounts.py`
- Modify: `app/routers/auth.py` (add `/account/change-password`), `app/main.py` (mount routers)

**Interfaces:**
- Consumes: `require_login`, `require_role`, `verify_csrf`, `hash_password`, `validate_new_password`, `destroy_user_sessions`, `write_audit`.
- Produces routes:
  - `GET /dashboard` — `giam_doc` only; shows placeholders (Bài chờ duyệt, Lead mới, `AUTONOMY_LEVEL` value read from `settings`) — real widgets come in Phase 1.
  - `GET /dashboard/users`, `POST /dashboard/users` (create; fields `username`, `full_name`, `password`, `role`), `POST /dashboard/users/{id}/toggle-active`, `POST /dashboard/users/{id}/reset-password` — `giam_doc` only; a `giam_doc` cannot deactivate themself; every action audited.
  - `GET /reports` — both roles; placeholder `Chưa có dữ liệu báo cáo`.
  - `GET /admin_api/ping` — `giam_doc` only, returns `{"ok": true}`.
  - `GET/POST /account/change-password` — both roles; requires current password; on success destroys the user's other sessions, writes audit `password_changed`.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/users", "/admin_api/ping"])
def test_ke_toan_forbidden(logged_in, path):
    assert logged_in(Role.ke_toan).get(path).status_code == 403

@pytest.mark.parametrize("role", [Role.giam_doc, Role.ke_toan])
def test_reports_allowed(logged_in, role):
    assert logged_in(role).get("/reports").status_code == 200

@pytest.mark.parametrize("path", ["/dashboard", "/reports", "/admin_api/ping"])
def test_anonymous_redirected(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"

def test_giam_doc_creates_ke_toan(logged_in, db):
    c = logged_in(Role.giam_doc)
    c.post("/dashboard/users", data={"username": "ketoan", "full_name": "Kế toán", "password": "Matkhau#2026",
                                     "role": "ke_toan", "csrf_token": csrf_of(c)})
    assert db.query(User).filter_by(username="ketoan", role=Role.ke_toan).one()

def test_cannot_deactivate_self(logged_in, db): ...
    # POST toggle-active on own id → 400, user still active

def test_change_password_kills_other_sessions(client_factory, make_user):
    # two clients logged in as same user; client A changes password;
    # client B GET /reports → 303 /login; client A still 200
```
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS**
- [ ] **Step 5: Commit** `feat: role-guarded dashboard shells and account management`

### Task 8: Docker deployment and backup

**Files:**
- Create: `deploy/Dockerfile`, `deploy/entrypoint.sh`, `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/backup.sh`, `deploy/bootstrap.sh`, `deploy/rollback.md`, `tests/test_deploy_files.py`

**Interfaces:**
- `Dockerfile`: `python:3.12-slim`, non-root user, installs package, `ENTRYPOINT ["/app/deploy/entrypoint.sh"]`.
- `entrypoint.sh`: `alembic upgrade head` then `exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "$TRUSTED_PROXY_IPS"`.
- `docker-compose.yml`: services `app` (env_file `.env`, `depends_on: db: condition: service_healthy`, `restart: unless-stopped`, logging json-file `max-size: 10m`, `max-file: "5"`), `db` (`postgres:16`, volume `pgdata`, healthcheck `pg_isready`, no `ports`), `caddy` (`caddy:2`, ports 80/443, volumes `caddy_data`, `caddy_config`); fixed network subnet `172.28.0.0/24` so `TRUSTED_PROXY_IPS` can be the Caddy container IP `172.28.0.10`.
- `Caddyfile`: `{$APP_DOMAIN}` reverse_proxy `app:8000`.
- `backup.sh`: `pg_dump -Fc` via `docker compose exec -T db`, file `backups/bestone-YYYYmmdd-HHMM.dump`, keep 7 daily + 4 weekly (Sunday) files, upload to S3 when `BACKUP_S3_*` set (using `aws`-compatible CLI in a throwaway container `amazon/aws-cli`), exit non-zero on any failure.
- `bootstrap.sh`: steps 1–6 of `docs/06` for Ubuntu 24.04, idempotent, generates `POSTGRES_PASSWORD` and `SESSION_SECRET_KEY` with `openssl rand -hex 32` only if empty, installs cron `0 2 * * * deploy/backup.sh`.
- `rollback.md`: Vietnamese, copy-paste steps: `git checkout <tag>`, `docker compose up -d --build`, restore DB with `pg_restore --clean`.

- [ ] **Step 1: Test `tests/test_deploy_files.py`** — parse compose YAML (add `pyyaml` to dev deps): services == {"app","db","caddy"}; only `caddy` has `ports`; `db` image starts with `postgres:16`; every variable referenced in compose/entrypoint exists in `.env.example`; `.env.example` contains no non-empty value for names ending in `_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`.
- [ ] **Step 2: FAIL → Step 3: Write files → Step 4: PASS**
- [ ] **Step 5: Manual verification (needs Docker — Docker Desktop on this PC or the VPS):**

Run: `cp .env.example .env` (fill `POSTGRES_PASSWORD`, `SESSION_SECRET_KEY`, `APP_DOMAIN=localhost`, `APP_ENV=dev`), `docker compose -f deploy/docker-compose.yml up -d --build`, `docker compose exec app python -m app.cli.create_admin`, `curl -k https://localhost/health`
Expected: `{"status":"ok","db":"ok"}`; login works in browser; `deploy/backup.sh` creates a dump; `pg_restore` into a scratch DB succeeds. Also run `TEST_DATABASE_URL=postgresql+psycopg://... pytest -q` once against the container DB — all green.
- [ ] **Step 6: Commit** `feat: docker deployment, bootstrap and backup scripts`

### Task 9: Docs and status update

**Files:**
- Modify: `CLAUDE.md` (Lệnh thường dùng: real commands incl. `.venv` setup, `docker compose -f deploy/docker-compose.yml ...`; add "Trạng thái: Giai đoạn 0 xong" line), `docs/07_BUILD_PLAN_TASKS.md` (no change unless acceptance differs).

- [ ] **Step 1:** Run full suite `.venv/Scripts/pytest -q`, `ruff check .`, `mypy app` — all clean.
- [ ] **Step 2:** Update `CLAUDE.md`.
- [ ] **Step 3: Commit** `docs: phase 0 status and commands`

## Acceptance (from `docs/07` Giai đoạn 0 + `docs/08` §7)

| Criterion | Proven by |
|---|---|
| `/health` = 200 | Task 1 tests, Task 8 Step 5 |
| `pytest` green | Task 9 Step 1 |
| Login with 2 accounts, correct permissions | Tasks 6–7 tests |
| Lock after 5 wrong, Telegram alert, unlock after 15 min / password change | Task 6, Task 4 |
| Same message for unknown user / wrong password | Task 6 |
| Session expiry | Task 5 |
| CSRF rejection | Tasks 5–6 |
| Logout clears session | Task 6 |
| `docker compose up` local + backup/restore | Task 8 Step 5 (needs Docker) |
