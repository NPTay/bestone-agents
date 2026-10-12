# 03 — Tech Stack & Repo Structure

## Stack (đã chốt, đừng đổi nếu không có lý do)
| Lớp | Công nghệ | Lý do |
|---|---|---|
| Ngôn ngữ | Python 3.12 | Hệ sinh thái AI, 1 người dễ bảo trì |
| Web/API | FastAPI + Uvicorn | Webhook Meta, dashboard, API nội bộ |
| Dashboard | Jinja2 + HTMX + Tailwind (CDN) | Duyệt bài trên web/điện thoại, không cần build frontend |
| DB | PostgreSQL 16 (container `db` trong Docker Compose trên VPS) | Một chỗ chứa dữ liệu, không phụ thuộc dịch vụ ngoài, chi phí 0 |
| Auth | Tự làm theo `docs/08`: bảng `users` + `sessions`, mật khẩu băm `argon2` (thư viện `argon2-cffi`), cookie session phía server | Chỉ 2 tài khoản cố định, không cần dịch vụ auth bên ngoài |
| Queue/Scheduler | APScheduler (in-process) + bảng `jobs` trong Postgres | Đủ cho quy mô này, không cần Redis |
| ORM/Migrate | SQLAlchemy 2 + Alembic | Quản lý toàn bộ schema |
| LLM | Anthropic Python SDK | Prompt caching, tool use |
| Tìm kiếm tin | feedparser (RSS) + Anthropic web search tool hoặc Brave/Serper API (cấu hình được) | |
| Cảnh báo | Telegram Bot API (mặc định) + Email SMTP | Tức thì, miễn phí |
| Reverse proxy | Caddy | HTTPS tự động (Let's Encrypt) |
| Đóng gói | Docker Compose | Một lệnh chạy, dễ khôi phục |
| Kiểm thử | pytest, respx (mock HTTP), Postgres thật trong Docker cho test tích hợp | |

## Cấu trúc thư mục cần tạo
```
bestone-agents/
├── CLAUDE.md
├── docs/  knowledge/  agents/          # tài liệu đầu vào (đã có)
├── app/
│   ├── main.py                         # FastAPI app, mount routers
│   ├── config.py                       # pydantic-settings đọc .env
│   ├── db/ (models.py, session.py)     # SQLAlchemy models
│   ├── llm/ (client.py, prompts.py)    # nạp agents/*.md, knowledge, caching, retry, đo token
│   ├── agents/
│   │   ├── orchestrator.py  research.py  content.py  publisher.py  care.py
│   ├── integrations/
│   │   ├── meta_graph.py               # đăng bài, gửi tin, đọc comment, insights
│   │   ├── rss.py  websearch.py
│   │   └── notify.py                   # Telegram/Email
│   ├── guardrails/ (rules.py, judge.py)# kiểm tra output trước khi đăng/gửi
│   ├── auth/
│   │   ├── passwords.py                 # băm/kiểm tra mật khẩu argon2
│   │   ├── session.py                   # tạo/đọc/xóa session (bảng sessions), cookie httpOnly
│   │   ├── csrf.py                      # CSRF token cho mọi form
│   │   └── dependencies.py              # FastAPI dependency: require_login, require_role("giam_doc")
│   ├── cli/ (create_admin.py, reset_password.py)
│   ├── routers/ (auth.py, webhook.py, dashboard.py, reports.py, admin_api.py, health.py)
│   ├── scheduler.py                    # đăng ký cron jobs
│   ├── templates/ (Jinja2: login.html, dashboard/...)  static/
│   └── knowledge/ingest.py             # nạp knowledge/*.md vào bộ nhớ/DB
├── migrations/                         # Alembic
├── tests/
├── deploy/ (docker-compose.yml, Dockerfile, Caddyfile, backup.sh, bootstrap.sh, rollback.md)
├── .env.example
└── pyproject.toml
```

`deploy/docker-compose.yml` gồm 3 service: `app`, `db`, `caddy` (chi tiết `docs/06`).

## Quy ước code
- Type hints đầy đủ, `ruff` + `mypy` sạch.
- Mọi lời gọi LLM và Meta API qua wrapper có timeout, retry (exponential backoff), log có `job_id`.
- Không hard-code prompt trong code: nạp từ `agents/*.md` (phần trong khối ```` ```prompt ````).
- Output LLM có cấu trúc: dùng JSON schema/tool use, validate bằng Pydantic, lỗi thì retry 1 lần rồi đánh dấu `failed`.
- Không log nội dung tin nhắn khách ở mức INFO (che số điện thoại khi log). Không log mật khẩu dưới mọi hình thức.
- Secret (`SESSION_SECRET_KEY`, mật khẩu DB, token Meta, khóa API) chỉ tồn tại trong biến môi trường phía server, không bao giờ đưa vào template/response gửi cho trình duyệt.
