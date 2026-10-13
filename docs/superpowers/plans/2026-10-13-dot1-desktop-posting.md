# Đợt 1 — Desktop Posting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows desktop program that drafts 2 Fanpage posts a day (09:00 news post with stock/AI image, 16:30 post from `Tai Lieu` + `Picture`), gets each approved or revised on Telegram, publishes on time, adds a fixed promo comment, and shows a read-only "Hôm nay" page.

**Architecture:** One Python process started by Windows Task Scheduler at logon. A 60-second `tick(now)` loop derives every action from DB state + local time (idempotent, survives restarts and late power-on). A second thread long-polls Telegram. A FastAPI app on `127.0.0.1` serves the "Hôm nay" page. SQLite file, `create_all` at startup (no migrations in Đợt 1).

**Tech Stack:** Python 3.12, SQLAlchemy 2, SQLite, FastAPI + uvicorn + Jinja2, httpx, anthropic, google-genai, beautifulsoup4, pytest + respx, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-13-local-fanpage-agents-design.md` (Đợt 1 = mục 6.6). Read it before starting.

## Global Constraints

- Timezone `Asia/Ho_Chi_Minh`. DB stores UTC (`app.clock.utcnow()`); schedule logic uses local time.
- Fixed times (local): morning draft `08:00`, morning publish `09:00`, morning draft cutoff `12:00`, afternoon draft `15:00`, afternoon publish `16:30`, day end `20:00`.
- Nothing is posted to Facebook without a Telegram approval, except the fixed promo comment that follows an approved post.
- Approved before slot time → publish at slot time; approved after → publish on the next tick. Not approved by 20:00 → `expired`, never carried to the next day.
- Facts, numbers, project names, certifications only from `knowledge/bestone_knowledge_base.md`. No price, warranty, lifetime, or TCVN claims.
- Morning images: licensed stock (Pexels) or Gemini-generated illustration only; never images from news articles. Gemini images must not depict a real named project or test result.
- Afternoon images: from `Picture/` only (`.jpg`, `.jpeg`, `.png`; skip video), minus `config/picture_exclude.txt`.
- A project folder may be named in a post only if its KB subsection exists and contains no `[GĐ BỔ SUNG` marker.
- Secrets only in `.env` (gitignored). Never in HTML, logs, or exception messages (Telegram URL embeds the bot token; Graph calls carry the page token).
- Telegram: only updates from `TELEGRAM_ADMIN_CHAT_ID` are acted on.
- UI, prompts, posts, Telegram copy: Vietnamese. Code, identifiers, comments: English.
- `DRY_RUN=true` → no Graph API writes (log what would be posted); default `true` in `.env.example`.
- Only one instance may run (a second start exits).
- Commands (Git Bash, repo root): tests `.venv/Scripts/python -m pytest -q`, lint `.venv/Scripts/ruff check .`, types `.venv/Scripts/mypy app`.

## Review Focus

1. **Computer switched on late (e.g. 10:40) or restarted mid-day** → morning draft created immediately if before 12:00, approved posts whose time passed publish now, nothing already done is redone. (Test in Task 10.)
2. **Crash between Graph publish and saving `fb_post_id`** → a post left in `publishing` is never auto-retried (would double-post); director is alerted to check the Page. (Test in Task 9.)
3. **Two posts pending at once and director types free-text feedback without replying to a specific message** → bot asks them to reply to the post they mean; feedback is never applied to a guessed post. (Test in Task 8.)
4. **Director presses an old button (from a previous revision, or a post already published/expired)** → no action, short Telegram answer explaining why. (Test in Task 8.)
5. **No usable image (Pexels key missing, Gemini error) or no news found** → draft still goes to Telegram with a clear warning, or a Telegram alert says the slot was skipped; the loop keeps running. (Tests in Tasks 4 and 10.)

---

### Task 1: Reset repo to the desktop stack

Branch from the current HEAD (`phase1-content-pipeline`, which holds the spec): `git switch -c desktop-dot1`.

**Files:**
- Restore from HEAD (`git checkout HEAD -- <path>`): `app/__init__.py`, `app/clock.py`, `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`, `app/guardrails/`, `app/integrations/__init__.py`, `app/integrations/notify.py`, `app/jobs.py`, `app/llm/`, `knowledge/`, `tests/__init__.py`, `tests/test_guardrail_rules.py`, `tests/test_guardrail_judge.py`, `tests/test_llm_client.py`, `tests/test_jobs.py`, `tests/test_notify.py`, `tests/test_prompts.py`, `pyproject.toml`, `.gitattributes`
- Commit as deleted (`git rm`): everything else in the current `git status` deletion list (auth, cli, routers, templates, web, main, settings_store, audit, knowledge/ingest, deploy/, migrations/, alembic.ini, requirements.lock, docs/08, remaining tests). `docs/06_DEPLOYMENT_VPS.md` also removed.
- Rewrite: `app/config.py`, `app/db/models.py`, `tests/conftest.py`, `.gitignore`, `.env.example`, `pyproject.toml`
- Create: `app/db/init.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - `Settings` fields (all `str` unless noted, default `""`): `ANTHROPIC_API_KEY`, `LLM_TIMEOUT_SECONDS: int = 120`, `MODEL_QUALITY = "claude-sonnet-5-5"`, `MODEL_FAST = "claude-haiku-5-5"`, `META_APP_ID`, `META_APP_SECRET`, `META_PAGE_ID`, `META_PAGE_ACCESS_TOKEN`, `META_GRAPH_VERSION` (builder looks up the current Graph API version at build time and pins it as the default), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `PEXELS_API_KEY`, `GEMINI_API_KEY`, `GEMINI_IMAGE_MODEL` (builder pins a current Gemini image model), `DATABASE_URL = "sqlite:///data/bestone.db"`, `DATA_DIR = "data"`, `PICTURE_DIR = "Picture"`, `DOCS_DIR = "Tai Lieu"`, `DASHBOARD_PORT: int = 8765`, `DRY_RUN: bool = True`, `TZ = "Asia/Ho_Chi_Minh"`. No session/postgres/backup/SMTP/domain fields.
  - Models in `app/db/models.py`: keep `Job`, `Alert`, `LlmUsage`, `Setting` exactly as before (drop `users` FKs); delete all others.
  - `init_db(engine: Engine) -> None` in `app/db/init.py`: creates `DATA_DIR`, `DATA_DIR/media`, `DATA_DIR/logs`, then `Base.metadata.create_all`.
  - `tests/conftest.py`: fixtures `engine` (in-memory SQLite, `create_all`), `db` (Session), `db_factory` (callable returning Sessions on `engine`), `frozen_clock(monkeypatch)` returning a setter that pins `app.clock.utcnow`. Drop the Postgres/`TEST_DATABASE_URL` and FastAPI-client fixtures.

- [ ] **Step 1:** Create the branch, restore and remove files as listed.
- [ ] **Step 2:** Update `pyproject.toml` dependencies to: `sqlalchemy>=2.0`, `pydantic-settings`, `fastapi`, `uvicorn`, `jinja2`, `httpx`, `tzdata`, `anthropic>=1.0`, `google-genai`, `beautifulsoup4`, `pyyaml`. Dev: `pytest`, `respx`, `ruff`, `mypy`, `types-PyYAML`, `types-beautifulsoup4`. Remove alembic, psycopg, argon2, apscheduler, feedparser, python-multipart.
- [ ] **Step 3:** Write `.gitignore` (`.env`, `.venv/`, `data/`, `.superpowers/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`) and `.env.example` (every Settings name, values empty except `DRY_RUN=true`, `MODEL_*`, `TZ`).
- [ ] **Step 4: Write the failing test** `tests/test_models.py::test_init_db_creates_tables_and_dirs`: call `init_db` on a temp-file SQLite engine with `DATA_DIR` set to `tmp_path/"data"`; assert tables `jobs`, `alerts`, `llm_usage`, `settings` exist and `tmp_path/"data"/"media"` is a directory.
- [ ] **Step 5:** Run `.venv/Scripts/python -m pytest tests/test_models.py -q` → FAIL (no `app.db.init`).
- [ ] **Step 6:** Rewrite `app/config.py`, `app/db/models.py`, `tests/conftest.py`; implement `init_db`. Fix restored modules/tests only where they import removed things (e.g. `jobs`/`notify` must not need users).
- [ ] **Step 7:** Recreate venv if missing (`py -3.12 -m venv .venv`, `.venv/Scripts/python -m pip install -e ".[dev]"`), then run full pytest, ruff, mypy → all green.
- [ ] **Step 8: Commit** — `chore: reset to desktop stack (drop VPS, auth, Postgres)`.

---

### Task 2: Post store and state machine

**Files:**
- Modify: `app/db/models.py` (add `Post`, `ResearchItem`, `PictureUse`)
- Create: `app/posts/__init__.py`, `app/posts/store.py`, `app/schedule_times.py`
- Test: `tests/test_post_store.py`

**Interfaces:**
- Produces:
  - `Slot = Literal["morning", "afternoon"]`; `PostStatus = Literal["drafting", "pending", "approved", "publishing", "published", "rejected", "expired", "failed"]`.
  - `Post` (TimestampMixin): `day: date`, `slot: Slot`, `status: PostStatus = "drafting"`, `revision: int = 1`, `title`, `body`, `hashtags: list[str]`, `cta`, `sources: list[dict[str,str]]`, `kb_refs: list[str]`, `image_paths: list[str]`, `image_note: str | None` (credit or warning), `picture_folder: str | None`, `research_url: str | None`, `guardrail_report: dict | None`, `blocking: bool = False`, `telegram_message_id: int | None`, `approved_at`, `published_at`, `fb_post_id`, `comment_id`, `error: str | None`. `UniqueConstraint("day", "slot")`.
  - `ResearchItem`: `url` (unique), `title`, `source_name`, `used_post_id: uuid | None`, `fetched_at`.
  - `PictureUse`: `path` (unique, relative to `PICTURE_DIR`, forward slashes), `used_count: int = 0`, `last_used_at`.
  - `app/schedule_times.py`: `LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")`; constants `MORNING_DRAFT = time(8, 0)`, `MORNING_PUBLISH = time(9, 0)`, `MORNING_CUTOFF = time(12, 0)`, `AFTERNOON_DRAFT = time(15, 0)`, `AFTERNOON_PUBLISH = time(16, 30)`, `DAY_END = time(20, 0)`; `local_now(utc: datetime) -> datetime`; `publish_at(day: date, slot: Slot) -> datetime` (UTC).
  - `app/posts/store.py`:
    - `claim_slot(db, day: date, slot: Slot) -> Post | None` — inserts a `drafting` row; returns `None` if the (day, slot) row already exists (IntegrityError rolled back).
    - `save_draft(db, post: Post, draft: PostDraft, report: GuardrailReport, blocking: bool) -> None` — fills content, sets `status="pending"`. (`PostDraft` defined in Task 6; until then accept any object with those attributes — define `PostDraft` here as a pydantic model so Task 6 imports it: fields `title: str`, `body: str`, `hashtags: list[str]`, `cta: str`, `sources: list[dict[str,str]]`, `kb_refs: list[str]`.)
    - `new_revision(db, post: Post, draft: PostDraft, report, blocking) -> None` — `revision += 1`, overwrite content, stays `pending`.
    - `approve(db, post_id: uuid, revision: int, now: datetime) -> Literal["ok", "stale", "blocked"]` — `ok` only if `status=="pending"` and `revision` matches and not `blocking`.
    - `reject(db, post_id: uuid, revision: int) -> Literal["ok", "stale"]`.
    - `due_for_publish(db, now: datetime) -> list[Post]` — `approved` and `publish_at(day, slot) <= now`.
    - `expire_open(db, now: datetime) -> list[Post]` — posts in `drafting|pending|approved` whose day is before today, or today when local time ≥ 20:00 → `expired`; returns them.
    - `posts_for_day(db, day: date) -> list[Post]`.

- [ ] **Step 1: Write failing tests** in `tests/test_post_store.py`:
  - `test_claim_slot_is_idempotent`: second `claim_slot(db, d, "morning")` returns `None`; one row.
  - `test_approve_requires_matching_revision`: post at revision 2 → `approve(..., revision=1)` == `"stale"`, status still `pending`; `approve(..., 2)` == `"ok"`, status `approved`, `approved_at` set.
  - `test_approve_blocked_when_guardrail_blocking`: `blocking=True` → `"blocked"`.
  - `test_reject_after_publish_is_stale`: status `published` → `"stale"`.
  - `test_due_for_publish_respects_slot_time`: approved morning post, now = 08:59 local → `[]`; 09:00 → `[post]`.
  - `test_expire_open_at_day_end`: pending today at 19:59 → not expired; at 20:00 → `expired`; pending from yesterday at 08:00 → `expired`; `published` never touched.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement models and store functions.
- [ ] **Step 4:** Run → PASS; ruff + mypy clean.
- [ ] **Step 5: Commit** — `feat: post store and daily state machine`.

---

### Task 3: Picture library and project info

**Files:**
- Create: `app/content/__init__.py`, `app/content/pictures.py`, `config/picture_exclude.txt` (comment header only, Vietnamese: one folder or file path per line, relative to `Picture`)
- Modify: `knowledge/bestone_knowledge_base.md` — add section `## 13. Công trình trong thư viện ảnh` with one `### Thư mục: <exact folder name>` subsection for each of: `Tòa nhà Kyobo`, `교보 INSURANCE COMPANY (B1-B4)`, `경주 CONVENTION CENTER`, `KOREA RESEARCH INSTITUTE OF DECOMMISSIONING`, `Warehouse - 80m of basement`, `Hoi Thao Saca 9-3`. Each body: lines `- Tên hiển thị: [GĐ BỔ SUNG]`, `- Quốc gia / địa điểm: [GĐ BỔ SUNG]`, `- Hạng mục dùng Bestone: [GĐ BỔ SUNG]`, `- Năm: [GĐ BỔ SUNG]`, `- Ghi chú được phép nêu: [GĐ BỔ SUNG]`.
- Test: `tests/test_pictures.py`

**Interfaces:**
- Produces:
  - `ProjectInfo` dataclass: `folder: str`, `verified: bool`, `text: str` (subsection body).
  - `parse_projects(kb_text: str) -> dict[str, ProjectInfo]` — keyed by folder name; `verified` = no `[GĐ BỔ SUNG` in body.
  - `list_pictures(picture_dir: Path, exclude_file: Path) -> dict[str, list[str]]` — folder (relative, `""` for root) → sorted relative paths of `.jpg/.jpeg/.png` (case-insensitive); excluded folders/files removed.
  - `PictureChoice` dataclass: `folder: str`, `paths: list[str]` (relative), `project: ProjectInfo | None` (only when verified).
  - `choose_pictures(db, picture_dir: Path, exclude_file: Path, kb_text: str, max_images: int = 3) -> PictureChoice | None` — folder with lowest total `used_count` (ties: alphabetical); within it, up to `max_images` least-used paths; does NOT record usage.
  - `record_use(db, paths: list[str], now: datetime) -> None`.

- [ ] **Step 1: Write failing tests** (build a fake `Picture` tree in `tmp_path`):
  - `test_list_pictures_filters_types_and_excludes`: `a/1.jpg`, `a/2.PNG`, `a/v.mp4`, `b/3.jpg`; exclude file contains `b` → `{"a": ["a/1.jpg", "a/2.PNG"]}`.
  - `test_parse_projects_verified_flag`: KB with one filled subsection and one containing `[GĐ BỔ SUNG]` → verified True/False.
  - `test_choose_prefers_least_used_folder_and_files`: after `record_use(["a/1.jpg"])`, choice is folder `b`; then within `a` the unused file comes first.
  - `test_choice_project_only_when_verified`.
  - `test_choose_returns_none_when_library_empty`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; edit the KB section.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: picture library rotation and project info parsing`.

---

### Task 4: Morning image sourcing (Pexels / Gemini)

**Files:**
- Create: `app/content/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Produces:
  - `ImagePlan` (pydantic): `kind: Literal["stock", "ai"]`, `stock_query: str` (English keywords), `ai_prompt: str` (English; generic construction/waterproofing illustration, no logos, no text, no real named building).
  - `ImageResult` dataclass: `paths: list[str]` (absolute, under `DATA_DIR/media`), `note: str` (Vietnamese: e.g. `"Ảnh: Pexels – <photographer>"`, `"Ảnh minh họa do AI (Gemini) tạo"`, or warning `"⚠️ Không lấy được ảnh: …"`).
  - `fetch_stock(query: str, dest_dir: Path, settings: Settings) -> ImageResult | None` — Pexels `GET https://api.pexels.com/v1/search?query=…&per_page=5&orientation=landscape`, header `Authorization: <key>`; downloads first photo's `src.large2x`; `None` if no key, no results, or HTTP error.
  - `generate_ai(prompt: str, dest_dir: Path, settings: Settings) -> ImageResult | None` — google-genai, model `GEMINI_IMAGE_MODEL`, saves PNG; `None` if no key or error.
  - `get_morning_image(plan: ImagePlan, dest_dir: Path, settings: Settings) -> ImageResult` — try the planned kind first, then the other; if both fail, `ImageResult(paths=[], note="⚠️ Không lấy được ảnh (kho ảnh và AI đều lỗi). Anh/chị có thể bấm Đăng để đăng không ảnh, hoặc góp ý.")`. Never raises. Error logs must not include keys.

- [ ] **Step 1: Write failing tests** (respx for Pexels; monkeypatch `generate_ai` for the Gemini path):
  - `test_stock_downloads_first_photo` (asserts file written, note contains photographer, request carried the key header).
  - `test_stock_none_without_key` (no HTTP call made).
  - `test_falls_back_to_ai_when_stock_empty`.
  - `test_both_fail_returns_warning_not_exception`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: morning image sourcing via Pexels and Gemini`.

---

### Task 5: News research for the morning post

**Files:**
- Create: `app/content/research.py`, `config/research_queries.txt` (one Vietnamese query per line, seeded from `agents/a1_research.md` keyword list)
- Test: `tests/test_research.py`

**Interfaces:**
- Consumes: `LLMClient.web_search(agent=..., query=..., max_uses=..., job_id=...) -> list[SearchHit]` (existing, `app/llm/client.py`).
- Produces:
  - `Article` dataclass: `url`, `title`, `source_name` (domain), `text` (plain text, max 8000 chars).
  - `fetch_article(url: str) -> Article | None` — httpx GET (timeout 15s, follow redirects, browser-like UA), BeautifulSoup text of `<article>` or `<main>` or `<body>`, scripts/styles stripped; `None` on error, non-HTML, or text < 500 chars. Never fetch `facebook.com`/`fb.com` URLs (return `None`).
  - `find_candidates(llm, db, queries: list[str], job_id, limit: int = 5) -> list[Article]` — picks 3 queries (rotating by day-of-year), web-searches each, drops URLs already in `ResearchItem`, fetches until `limit` articles; inserts a `ResearchItem` for each fetched article.

- [ ] **Step 1: Write failing tests** (FakeLLM hits + respx pages):
  - `test_skips_already_used_urls`.
  - `test_fetch_article_extracts_main_text_and_strips_scripts`.
  - `test_fetch_article_rejects_facebook_and_short_pages`.
  - `test_queries_rotate_by_day`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: news research for morning posts`.

---

### Task 6: Post writer (morning, afternoon, revise) with guardrails

**Files:**
- Create: `app/content/writer.py`
- Modify: `agents/a2_content.md` (prompt block: two-slot daily schedule; morning = rewrite one article from technical Bestone angle with source name + link, never claim Bestone solved that project; afternoon = KB/catalogue topic, optional verified project; revise = apply director feedback, keep all rules), `app/llm/prompts.py` (agent names `content`, `guardrail_judge` only), `app/guardrails/rules.py` (add project-name check)
- Test: `tests/test_writer.py`, extend `tests/test_guardrail_rules.py`

**Interfaces:**
- Consumes: `PostDraft` (Task 2), `Article` (Task 5), `PictureChoice`/`ProjectInfo` (Task 3), `ImagePlan` (Task 4), `check_post(...) -> GuardrailReport` (existing).
- Produces:
  - `MorningDraft(PostDraft)`: adds `article_url: str`, `image_plan: ImagePlan`.
  - `write_morning(llm, articles: list[Article], kb: str, recent_titles: list[str], job_id) -> MorningDraft | None` — LLM picks the most relevant article (or returns `article_url=""` meaning none fit → function returns `None`) and writes the post. `sources` must contain the chosen article.
  - `write_afternoon(llm, choice: PictureChoice | None, kb: str, recent_titles: list[str], job_id) -> PostDraft` — pillar per `knowledge/content_pillars.md`, avoiding topics of `recent_titles` (last 14 days). Names the project only when `choice.project` is set.
  - `revise(llm, previous: PostDraft, feedback: str, kb: str, source_texts: list[str], job_id) -> PostDraft`.
  - `review(llm, draft: PostDraft, kb: str, source_texts: list[str], unverified_projects: list[str], job_id) -> tuple[GuardrailReport, bool]` — runs `check_post` plus the project-name rule; if failing, asks the writer to fix once (`revise` with the flags as feedback) and re-checks; returns final report and `blocking` = any `facts` or `forbidden_terms` failure or unverified project named.
  - `rules.check_project_names(text: str, unverified: list[str]) -> list[RuleFinding]` — case-insensitive match of each folder name (and, for `Tòa nhà Kyobo` / `교보 …`, the token `Kyobo`/`교보`); finding check `"facts"`, message `"Nêu tên công trình chưa có thông tin trong tài liệu: <name>"`.

- [ ] **Step 1: Write failing tests**:
  - `test_check_project_names_flags_unverified_kyobo`: text "…công trình Kyobo…" with `["Tòa nhà Kyobo"]` → 1 finding.
  - `test_write_morning_returns_none_when_no_article_fits` (FakeLLM returns `article_url=""`).
  - `test_write_afternoon_prompt_mentions_project_only_when_verified` (inspect `FakeLLM.calls[-1]["user"]`: verified → contains project text; unverified → folder name absent).
  - `test_review_retries_once_then_reports_blocking`: first draft contains "bảo hành 10 năm", fix still contains it → `blocking True`, exactly 2 judge calls + 1 revise call.
  - `test_review_passes_clean_draft_not_blocking`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement and update the prompt file.
- [ ] **Step 4:** Run → PASS (including the restored guardrail tests).
- [ ] **Step 5: Commit** — `feat: post writer for morning/afternoon with guardrail review`.

---

### Task 7: Telegram client and review messages

**Files:**
- Create: `app/telegram/__init__.py`, `app/telegram/bot.py`, `app/telegram/review.py`
- Modify: `app/integrations/notify.py` (reuse `TelegramBot.send_message` instead of raw httpx; keep `send_alert` signature)
- Test: `tests/test_telegram_bot.py`, `tests/test_review_messages.py`

**Interfaces:**
- Produces:
  - `TelegramBot(token: str, chat_id: str, client: httpx.Client | None = None)`:
    - `send_message(text: str, buttons: list[tuple[str, str]] | None = None, reply_to: int | None = None) -> int` (message_id; buttons = (label, callback_data) in one row)
    - `send_photos(paths: list[str]) -> None` (1 → `sendPhoto`, 2–10 → `sendMediaGroup`, multipart upload)
    - `answer_callback(callback_id: str, text: str) -> None`
    - `edit_buttons_removed(message_id: int) -> None` (`editMessageReplyMarkup` with empty keyboard)
    - `get_updates(offset: int, timeout: int = 30) -> list[dict]`
    - Raises `TelegramError(description)`; the message never contains the token.
  - `FakeTelegram` in the same module with the same methods, recording `sent: list[dict]` and a queue of updates (for tests in Tasks 8–10).
  - `review.send_for_review(bot, post: Post) -> int` — sends photos (if any), then the review text with buttons `("✅ Đăng", f"ok:{post.id}:{post.revision}")`, `("❌ Không đăng", f"no:{post.id}:{post.revision}")`; if `post.blocking`, only the "Không đăng" button. Returns message_id (caller stores it in `post.telegram_message_id`).
  - `review.format_review(post: Post) -> str` — exact layout:
    ```
    📝 BÀI {SÁNG|CHIỀU} {dd/mm} — đăng lúc {09:00|16:30} (bản {revision})

    {title}

    {body}

    {cta}
    {hashtags joined by space}

    Nguồn: {source name – url, one per line}   (omit line if none)
    {image_note}                               (omit if none)
    {"⚠️ Cần xem: " + flags joined by "; "}    (omit if no flags)
    {"⛔ Bài có lỗi thông tin nên chưa thể đăng. Hãy góp ý để AI sửa." if blocking}

    💬 Muốn sửa: trả lời (reply) tin nhắn này và gõ góp ý.
    ```
    Truncate body so the whole message ≤ 4000 chars.

- [ ] **Step 1: Write failing tests**:
  - `test_send_message_posts_inline_keyboard` (respx; asserts JSON `reply_markup.inline_keyboard`).
  - `test_error_message_hides_token` (HTTP 400 → `TelegramError` whose `str` lacks the token).
  - `test_send_photos_uses_media_group_for_three`.
  - `test_format_review_blocking_has_warning_and_single_button`.
  - `test_format_review_truncates_to_4000`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: telegram client and post review messages`.

---

### Task 8: Telegram update handling (approve / reject / feedback)

**Files:**
- Create: `app/telegram/handler.py`
- Test: `tests/test_telegram_handler.py`

**Interfaces:**
- Consumes: `approve`, `reject`, `new_revision` (Task 2), `revise`, `review` (Task 6), `send_for_review` (Task 7).
- Produces:
  - `get_offset(db) -> int` / `set_offset(db, value: int) -> None` — stored in `Setting` key `TELEGRAM_OFFSET`.
  - `handle_update(db, bot, llm, update: dict, now: datetime, admin_chat_id: str) -> None`:
    - Ignore anything whose chat id ≠ `admin_chat_id`.
    - `callback_query` `ok:<id>:<rev>` → `approve`; reply via `answer_callback`: ok → `"Đã duyệt. Bài sẽ đăng lúc HH:MM."` (or `"Đã duyệt. Bài sẽ đăng ngay."` if slot time passed) and remove buttons; stale → `"Nút này đã cũ (bài đã có bản mới hoặc đã xử lý)."`; blocked → `"Bài có lỗi thông tin, chưa thể đăng. Hãy góp ý để AI sửa."`.
    - `no:<id>:<rev>` → `reject`; ok → `"Đã bỏ bài này."` + remove buttons.
    - Text message: target post = the `pending` post whose `telegram_message_id` equals `reply_to_message.message_id`; if not a reply and exactly one `pending` post today → that post; if none → send `"Hiện không có bài nào đang chờ duyệt."`; if several → send `"Có nhiều bài đang chờ. Anh/chị hãy trả lời (reply) đúng tin nhắn của bài cần sửa."`. For the target: send `"Đang sửa theo góp ý…"`, run `revise` → `review` → `new_revision` → `send_for_review`, store new message id, remove buttons from the old message.
  - `poll_once(db_factory, bot, llm, settings, now_fn) -> None` — `get_updates(offset)`, handle each in its own session, `set_offset(last_update_id + 1)` after each (so a crash never replays a handled update). Exceptions per update are logged and sent as a Telegram alert; polling continues.

- [ ] **Step 1: Write failing tests** (FakeTelegram, FakeLLM):
  - `test_ignores_other_chats`.
  - `test_approve_button_approves_and_removes_keyboard`.
  - `test_old_revision_button_is_stale` (Review Focus 4).
  - `test_button_after_published_is_stale` (Review Focus 4).
  - `test_feedback_reply_creates_new_revision_and_resends` (revision 2, new message id stored).
  - `test_free_text_with_two_pending_asks_to_reply` (Review Focus 3; no revise call).
  - `test_offset_advances_per_update_even_when_handler_fails`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: telegram approval, rejection and feedback handling`.

---

### Task 9: Graph API client and publisher

**Files:**
- Create: `app/meta/__init__.py`, `app/meta/graph.py`, `app/posts/publisher.py`
- Test: `tests/test_graph.py`, `tests/test_publisher.py`

**Interfaces:**
- Produces:
  - `GraphError(code: int, message: str)`; `GraphClient(settings: Settings, client: httpx.Client | None = None)` base URL `https://graph.facebook.com/{META_GRAPH_VERSION}`:
    - `publish(message: str, image_paths: list[str]) -> str` — 0 images: `POST /{page}/feed`; 1: `POST /{page}/photos` (multipart `source`, `message`) → return `post_id`; 2+: each `POST /{page}/photos` with `published=false` → `POST /{page}/feed` with `attached_media[i]={"media_fbid": id}`.
    - `comment(post_id: str, text: str) -> str` — `POST /{post_id}/comments`.
    - `page_name() -> str` — `GET /{page}?fields=name` (used by setup check).
    - Token sent as form field `access_token`, never in logged URLs; `GraphError` messages never include it.
  - `COMMENT_TEXT = "Bestone – phụ gia cho bê tông tự chống thấm.\n📞 Hotline: 0904834577\n🌐 Website: https://cgengvn.com"` in `app/posts/publisher.py`.
  - `compose_message(post: Post) -> str` — title, blank line, body, blank line, cta, blank line, hashtags; plus `"Nguồn: <name> – <url>"` lines for morning posts.
  - `publish_post(db, graph: GraphClient | None, bot, post: Post, now: datetime, dry_run: bool) -> None`:
    - Set `status="publishing"` and commit BEFORE calling Graph.
    - `dry_run` → no Graph calls; `fb_post_id="DRY_RUN"`, `comment_id="DRY_RUN"`; Telegram `"🧪 (Chạy thử) Đã giả lập đăng bài {sáng|chiều}."`.
    - Success → `status="published"`, `published_at`, `fb_post_id`; for afternoon posts `record_use(picture paths)`; then `comment(...)` → `comment_id`. Comment failure leaves `published` with `comment_id=None` (retried by `retry_missing_comments`). Telegram `"✅ Đã đăng bài {sáng|chiều}."`.
    - `GraphError` → `status="failed"`, `error`; code 190 → urgent alert `"Token Facebook hết hạn hoặc bị thu hồi. Cần lấy token mới (xem hướng dẫn)."`; other codes → warn alert with message.
  - `retry_missing_comments(db, graph, now) -> None` — published today with `fb_post_id` and no `comment_id` (skip `DRY_RUN`).
  - `recover_stuck(db, bot) -> None` — at startup: any `publishing` post → `status="failed"`, `error="Bị gián đoạn khi đang đăng"`, urgent alert `"Bài {sáng|chiều} {dd/mm} bị gián đoạn lúc đang đăng. Hãy mở Fanpage kiểm tra xem bài đã lên chưa — chương trình sẽ KHÔNG tự đăng lại để tránh trùng."`.

- [ ] **Step 1: Write failing tests** (respx):
  - `test_publish_single_photo_uses_photos_endpoint`.
  - `test_publish_multiple_photos_attaches_media` (asserts `published=false` uploads then feed with `attached_media`).
  - `test_graph_error_hides_token`.
  - `test_publish_post_marks_publishing_before_call` (Graph mock asserts DB status is `publishing` when called).
  - `test_publish_post_adds_comment_and_records_picture_use`.
  - `test_token_expired_sends_urgent_alert` (code 190).
  - `test_dry_run_makes_no_graph_calls`.
  - `test_recover_stuck_never_republishes` (Review Focus 2).
  - `test_comment_failure_is_retried_later`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: graph client, publisher and promo comment`.

---

### Task 10: Daily tick orchestrator

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Deps` dataclass: `db_factory`, `llm: LLMClient | None`, `bot: TelegramBot | FakeTelegram`, `graph: GraphClient | None`, `settings: Settings`, `image_fn` (defaults to `get_morning_image`), `research_fn` (defaults to `find_candidates`).
  - `draft_morning(deps, day: date, now: datetime) -> None` and `draft_afternoon(deps, day, now) -> None` — `claim_slot` first (returns if already claimed); run research/writer/images/review via `run_job` (agent `"content"`, kind `"draft_morning"`/`"draft_afternoon"`); `save_draft`; `send_for_review`; store message id. If the morning writer finds no suitable article → post `status="failed"`, `error="Không tìm được tin phù hợp"`, Telegram `"Sáng nay không tìm được tin phù hợp nên không có bài sáng."`. If `llm` is `None` or the job fails → post `failed` + alert. Afternoon: `choose_pictures`; if `None`, write without images and set `image_note="⚠️ Thư mục Picture không có ảnh dùng được."`.
  - `tick(deps, now: datetime) -> None`, in this order:
    1. `expire_open` → for each expired post that had a Telegram message, remove its buttons and send `"⏰ Bài {sáng|chiều} {dd/mm} chưa được duyệt trước 20:00 nên đã bỏ."`.
    2. If local time in [08:00, 12:00) → `draft_morning(today)`.
    3. If local time in [15:00, 20:00) → `draft_afternoon(today)`.
    4. `due_for_publish` → `publish_post` each.
    5. `retry_missing_comments`.
    Each step wrapped so one failure doesn't stop the others (log + alert).
  - `startup(deps, now) -> None` — `recover_stuck`, then `tick`.

- [ ] **Step 1: Write failing tests** (FakeLLM, FakeTelegram, `graph=None` + `DRY_RUN`, stub image/research fns, frozen times in local tz):
  - `test_0800_drafts_morning_and_sends_for_review`.
  - `test_late_start_1040_drafts_morning_and_publishes_after_approval_immediately` (Review Focus 1).
  - `test_start_after_noon_skips_morning_draft`.
  - `test_restart_does_not_redraft_or_republish` (run `tick` twice; one post, one publish).
  - `test_1500_drafts_afternoon_with_pictures`.
  - `test_2000_expires_unapproved_and_notifies`.
  - `test_no_article_found_notifies_and_marks_failed` (Review Focus 5).
  - `test_one_step_failure_does_not_block_publishing` (draft step raises; approved post still published).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: daily tick orchestrator with catch-up`.

---

### Task 11: "Hôm nay" page

**Files:**
- Create: `app/web/__init__.py`, `app/web/app.py`, `app/web/templates/today.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces:
  - `create_app(db_factory, settings) -> FastAPI`:
    - `GET /` → today's posts (local date) rendered with `today.html`; `<meta http-equiv="refresh" content="60">`.
    - `GET /media/{post_id}/{index}` → `FileResponse` for `post.image_paths[index]` (resolved from `PICTURE_DIR` if relative). 404 if the post/index doesn't exist or the resolved path is outside `PICTURE_DIR` and `DATA_DIR/media`.
  - Layout per approved mockup (spec 6.4): top bar `Bestone · {Thứ …} {dd/mm/yyyy} · Đang chạy ✅ (8h–20h)` plus `🧪 Chạy thử` badge when `DRY_RUN`; "Lịch hôm nay" — one card per slot (09:00 Bài sáng, 16:30 Bài chiều) even if not yet drafted (`Chưa đến giờ soạn`); status labels: drafting `Đang soạn…`, pending `Chờ anh/chị duyệt trên Telegram ⏳`, approved `Đã duyệt – chờ đến giờ đăng`, publishing `Đang đăng…`, published `Đã đăng ✓` (+ `Bình luận giới thiệu đã gắn ✓` when `comment_id`), rejected `Đã bỏ`, expired `Hết hạn (không duyệt trước 20:00)`, failed `Lỗi: {error}`; title, first 300 chars of body, thumbnails, source link or `Ảnh từ: Picture/{folder}`, `image_note`. "Tin nhắn hôm nay" block: `Sẽ có ở đợt 2 (sau khi Meta duyệt quyền nhắn tin).`
  - Page and responses contain no secrets (no settings values except `DRY_RUN`).

- [ ] **Step 1: Write failing tests** (FastAPI `TestClient`):
  - `test_today_shows_both_slots_before_drafting`.
  - `test_today_shows_published_with_comment_badge`.
  - `test_media_rejects_path_outside_allowed_dirs` (post with `image_paths=["../../.env"]` → 404).
  - `test_page_contains_no_secrets` (set fake token values in settings; assert none appear in HTML).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement (plain CSS inside the template; readable at 1366px width).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: read-only today page`.

---

### Task 12: Runner, single instance, autostart, setup tools

**Files:**
- Create: `app/__main__.py`, `app/runner.py`, `app/cli/__init__.py`, `app/cli/setup_tools.py`, `scripts/setup.ps1`, `scripts/install_autostart.ps1`, `scripts/uninstall_autostart.ps1`, `scripts/start.ps1`
- Test: `tests/test_runner.py`, `tests/test_setup_tools.py`

**Interfaces:**
- Produces:
  - `acquire_single_instance(lock_path: Path) -> object | None` — exclusive non-blocking lock (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere); `None` if held.
  - `run(settings) -> int` (`python -m app` calls it): configure rotating log `DATA_DIR/logs/app.log` (5 × 1 MB); single-instance check (exit 0 with log line if already running); `init_db`; build `Deps`; `startup`; thread A loops `tick` every 60 s; thread B loops `poll_once`; uvicorn on `127.0.0.1:DASHBOARD_PORT` in the main thread; open `http://127.0.0.1:{port}/` in the default browser once uvicorn starts. Telegram startup message: `"🟢 Chương trình Bestone đã chạy."` (+ `" (chạy thử – chưa đăng thật)"` when `DRY_RUN`).
  - `python -m app.cli.setup_tools <command>`:
    - `telegram-chat-id` — calls `getUpdates`, prints the chat id(s) of whoever messaged the bot (director sends "/start" first).
    - `meta-token --user-token <short-lived token>` — exchanges for a long-lived user token (`GET /oauth/access_token?grant_type=fb_exchange_token&client_id&client_secret&fb_exchange_token`), then `GET /me/accounts` → page token for `META_PAGE_ID`; writes `META_PAGE_ACCESS_TOKEN=` into `.env` (replacing the line); prints only `"Đã lưu token cho Trang: <page name>"`.
    - `check` — prints one Vietnamese line per item with ✅/❌: Anthropic (tiny `MODEL_FAST` call), Telegram (`getMe` + sends `"Kiểm tra kết nối OK"`), Meta (`page_name()`), Pexels (one search), Gemini (list models or tiny call), `Picture` image count, `Tai Lieu` file count, `DRY_RUN` value. Exit code 1 if Anthropic, Telegram, or (when `DRY_RUN=false`) Meta fails.
  - `scripts/setup.ps1`: creates `.venv` with `py -3.12`, installs `-e .`, copies `.env.example` → `.env` if absent, prints next steps in Vietnamese.
  - `scripts/install_autostart.ps1`: registers Task Scheduler task `Bestone Fanpage` — trigger At logon of the current user, action `<repo>\.venv\Scripts\pythonw.exe -m app`, working dir = repo, restart on failure 3× every 5 min, no time limit. `uninstall_autostart.ps1` removes it. `start.ps1` runs it once manually.

- [ ] **Step 1: Write failing tests**:
  - `test_second_instance_is_refused` (two `acquire_single_instance` on same path → second `None`).
  - `test_meta_token_writes_env_and_prints_no_secret` (respx; tmp `.env`; captured stdout has no token).
  - `test_check_reports_failures_with_exit_code` (respx Telegram 401 → output contains `❌ Telegram`, exit 1).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement Python parts and the PowerShell scripts.
- [ ] **Step 4:** Run tests → PASS. Manually run `.venv/Scripts/python -m app` with an empty `.env`: it must start, show the page at `http://127.0.0.1:8765/`, log missing-key warnings, and not crash; Ctrl+C stops it.
- [ ] **Step 5: Commit** — `feat: runner, single-instance lock, autostart and setup tools`.

---

### Task 13: Catalogue extraction for director review

**Files:**
- Create: `app/cli/catalogue.py`
- Test: `tests/test_catalogue.py`

**Interfaces:**
- Produces:
  - `extract_proposals(client: anthropic.Anthropic, pdf_path: Path, kb_text: str, model: str) -> str` — sends the PDF as a base64 `document` content block with the KB as system context; asks for a Vietnamese markdown list of facts in the catalogue that the KB lacks or contradicts, each with page number, grouped as `## Bổ sung mới` / `## Khác với tài liệu hiện có`; no prices or warranties unless literally in the PDF (and then flagged).
  - `python -m app.cli.catalogue` — runs over every `.pdf` in `DOCS_DIR` (recursive), writes `knowledge/catalogue_proposals.md` (header: `Bản đề xuất — CHƯA được dùng. Giám đốc duyệt mục nào thì chép mục đó vào bestone_knowledge_base.md.`). The runtime never reads this file (KB loader reads only `bestone_knowledge_base.md`, `brand_voice.md`, `content_pillars.md`, `guardrails_compliance.md`).

- [ ] **Step 1: Write failing tests**:
  - `test_extract_sends_pdf_document_block` (fake client records the request; asserts a `document` block with `media_type="application/pdf"`).
  - `test_runtime_knowledge_excludes_proposals` (`load_knowledge` result lacks `catalogue_proposals.md`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; adjust `load_knowledge` to an explicit allowlist.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** — `feat: catalogue extraction into a review file`.

---

### Task 14: Docs for the director and project memory

**Files:**
- Create: `docs/HUONG_DAN_CAI_DAT.md`, `docs/CHUAN_BI_APP_REVIEW.md`, `docs/chinh_sach_quyen_rieng_tu.html`
- Rewrite: `CLAUDE.md`, `docs/01_PROJECT_BRIEF.md`, `docs/02_ARCHITECTURE.md`, `docs/05_META_INTEGRATION.md`
- Delete: `docs/03_TECH_STACK_REPO_STRUCTURE.md`, `docs/04_DATA_SCHEMA.md`, `docs/07_BUILD_PLAN_TASKS.md`, `agents/a0_orchestrator.md`, `agents/a3_publisher.md` (superseded; still in git history). Keep `agents/a1_research.md`, `agents/a4_customer_care.md` (Đợt 2).
- Test: `tests/test_docs.py`

Content requirements:
- `HUONG_DAN_CAI_DAT.md` (Vietnamese, numbered, copy-paste commands, for a non-programmer): install Python 3.12; run `scripts/setup.ps1`; create Telegram bot with @BotFather → token → message the bot → `setup_tools telegram-chat-id`; get Anthropic key; get Pexels key; get Gemini key; create Meta App (Business type) on developers.facebook.com, note App ID/Secret, Graph API Explorer → user token with `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` → `setup_tools meta-token --user-token …`; fill `.env`; `setup_tools check`; trial with `DRY_RUN=true` for a few days; switch to `DRY_RUN=false`; `scripts/install_autostart.ps1`; fill KB section 13 project info; run `python -m app.cli.catalogue` and review proposals; how to exclude pictures; where logs live; what to do on "Token Facebook hết hạn".
- `CHUAN_BI_APP_REVIEW.md`: what Đợt 2 needs (`pages_messaging`, business verification), how to host `chinh_sach_quyen_rieng_tu.html` free (e.g. GitHub Pages or Google Sites) and paste its URL into the Meta App, demo video script outline.
- `chinh_sach_quyen_rieng_tu.html`: Vietnamese privacy policy for C.G. Engineering Việt Nam per guardrail G5 (data collected: name, phone, company, project; purpose; no third-party sharing; deletion request via hotline 0904834577 / cgengvn.com).
- `CLAUDE.md`: new mission (desktop, one director, Telegram approvals), doc map, keep invariant rules 1, 3, 4 (no secrets in HTML/logs), 5, 6, 7, 8; rule 2 becomes "everything outgoing needs Telegram approval except the fixed promo comment"; commands for Windows dev; status: Đợt 1 on `desktop-dot1`, Đợt 2 = Messenger after App Review; Kế toán note removed.

- [ ] **Step 1: Write failing test** `tests/test_docs.py::test_env_example_matches_settings` (every `Settings` field name appears in `.env.example` and vice versa) and `test_install_guide_mentions_every_setup_command` (guide contains `telegram-chat-id`, `meta-token`, `check`, `install_autostart.ps1`, `DRY_RUN`).
- [ ] **Step 2:** Run → FAIL (guide missing).
- [ ] **Step 3:** Write the docs, delete superseded files.
- [ ] **Step 4:** Full suite + ruff + mypy → green.
- [ ] **Step 5: Commit** — `docs: desktop setup guide, app review prep, updated CLAUDE.md`.

---

## Acceptance (end of Đợt 1)

On the director's PC with real keys and `DRY_RUN=true`: `setup_tools check` all ✅ for Anthropic/Telegram/Pexels/Gemini; starting the program shows the page; at 08:00 (or on a late start) a morning draft with an image arrives on Telegram; a reply with feedback produces revision 2; "Đăng" makes the page show `Đã đăng ✓` with the dry-run message; the afternoon draft at 15:00 carries photos from `Picture`. Then, with the director's confirmation, one real post with `DRY_RUN=false` appears on the Fanpage with the promo comment underneath.
