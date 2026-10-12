# 06 — Deployment (VPS, chạy liên tục)

## Yêu cầu VPS
Ubuntu 24.04 LTS, 2 vCPU, 2-4 GB RAM, 40 GB SSD (có chạy Postgres trên cùng máy). Khuyến nghị vị trí Singapore hoặc Việt Nam để độ trễ thấp. Cần 1 tên miền (ví dụ `agent.cgengvn.com`) trỏ A record về IP VPS.

## Thành phần Docker Compose (`deploy/docker-compose.yml`)
| Service | Vai trò |
|---|---|
| `app` | FastAPI + scheduler (1 process, `restart: unless-stopped`) |
| `db` | PostgreSQL 16, dữ liệu trong volume `pgdata`, healthcheck `pg_isready`, KHÔNG mở cổng ra ngoài |
| `caddy` | reverse proxy, HTTPS tự động, cổng 80/443 |
Chỉ `caddy` mở cổng ra ngoài. `app` chờ `db` healthy rồi mới khởi động.

## Biến môi trường (`.env.example` — chỉ tên biến)
```
ANTHROPIC_API_KEY=
MODEL_QUALITY=claude-sonnet-5-5
MODEL_FAST=claude-haiku-5-5
DAILY_COST_LIMIT_USD=
META_APP_ID=
META_APP_SECRET=
META_PAGE_ID=
META_PAGE_ACCESS_TOKEN=
META_VERIFY_TOKEN=
META_GRAPH_VERSION=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL_TO=
SEARCH_API_KEY=
POSTGRES_DB=bestone
POSTGRES_USER=bestone_app
POSTGRES_PASSWORD=
# DATABASE_URL is set by docker compose (deploy/docker-compose.yml) from POSTGRES_*.
# For local non-Docker runs set it here, e.g. postgresql+psycopg://user:pass@localhost:5432/bestone
DATABASE_URL=
SESSION_SECRET_KEY=
SESSION_COOKIE_NAME=bestone_session
SESSION_MAX_AGE_SECONDS=28800
SESSION_REMEMBER_DAYS=30
INITIAL_ADMIN_USERNAME=
INITIAL_ADMIN_PASSWORD=
BACKUP_S3_ENDPOINT=
BACKUP_S3_BUCKET=
BACKUP_S3_ACCESS_KEY=
BACKUP_S3_SECRET_KEY=
APP_ENV=prod
APP_DOMAIN=
TRUSTED_PROXY_IPS=172.28.0.10
AUTONOMY_LEVEL=draft_only
TZ=Asia/Ho_Chi_Minh
```
Lưu ý: Docker Compose không nội suy `${...}` trong `env_file`, nên `DATABASE_URL` của `app` được đặt trong `environment:` của compose từ `POSTGRES_*`; chạy compose với `--env-file .env` từ thư mục gốc repo.

`INITIAL_ADMIN_*` chỉ dùng 1 lần cho `app/cli/create_admin.py`, xóa khỏi `.env` sau khi tạo tài khoản (theo `docs/08`).

## Quy trình triển khai lần đầu (Claude Code viết thành script `deploy/bootstrap.sh` và hướng dẫn người dùng chạy)
1. SSH vào VPS, tạo user không phải root, bật `ufw` (chỉ 22, 80, 443), tắt đăng nhập root bằng mật khẩu, cài `fail2ban`.
2. Cài Docker + Compose plugin.
3. `git clone` repo (private), tạo `.env` từ `.env.example`, sinh `POSTGRES_PASSWORD` và `SESSION_SECRET_KEY` ngẫu nhiên.
4. `docker compose up -d --build` (migration Alembic tự chạy khi `app` khởi động), seed knowledge.
5. Tạo tài khoản Giám đốc: `docker compose exec app python -m app.cli.create_admin`, sau đó tạo tài khoản Kế toán từ dashboard. Xóa `INITIAL_ADMIN_*` khỏi `.env`.
6. Kiểm tra `https://<domain>/health` trả 200, thử đăng nhập `https://<domain>/login` bằng tài khoản Giám đốc.
7. Đăng ký Webhook trên Meta; gửi tin thử từ tài khoản tester.

## Cập nhật
`git pull && docker compose up -d --build`. Migration chạy tự động khi khởi động. Có `deploy/rollback.md` mô tả quay lại phiên bản trước (gồm khôi phục DB từ bản backup).

## Giám sát & vận hành liên tục
- Endpoint `/health` (DB, scheduler, token Meta còn hạn) + dịch vụ ping ngoài (UptimeRobot hoặc tương đương) báo về Telegram khi sập.
- A0 gửi báo cáo hằng ngày 08:00: số bài chờ duyệt, tin chưa trả lời, lead mới, lỗi, chi phí token trong ngày.
- Cảnh báo urgent: token Meta hết hạn/lỗi 190, webhook không nhận sự kiện > 24 giờ, lead HOT chưa xử lý > 15 phút, chi phí LLM vượt ngưỡng (`DAILY_COST_LIMIT_USD`), backup thất bại hoặc quá 26 giờ chưa có bản mới, đĩa > 80%.
- Log: JSON, xoay vòng (`max-size` 10m, `max-file` 5).

## Backup (bắt buộc — DB chứa lead khách hàng)
- `deploy/backup.sh`: `pg_dump -Fc` hằng ngày 02:00 (cron của host hoặc job A0), nén, giữ 7 bản ngày + 4 bản tuần trên VPS.
- Đẩy bản sao ra object storage S3-compatible bên ngoài VPS (`BACKUP_S3_*`). Không chỉ lưu trên cùng VPS.
- Mỗi tháng thử khôi phục 1 lần vào DB tạm (`pg_restore`) và ghi kết quả vào `audit_log`.
- Thêm snapshot VPS của nhà cung cấp nếu có (tùy chọn).

## Bảo mật
Secret chỉ trong `.env` (quyền 600), không vào git. Postgres không mở cổng ra ngoài; app dùng role DB riêng, không dùng superuser. Dashboard bắt buộc đăng nhập theo `docs/08` + HTTPS. Webhook kiểm chữ ký. Cập nhật hệ điều hành tự động (`unattended-upgrades`). Xoay token Meta và mật khẩu DB định kỳ; file backup trên object storage phải ở bucket riêng tư.
