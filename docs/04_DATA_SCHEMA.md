# 04 — Data Schema (PostgreSQL tự chạy trên VPS)

Tất cả bảng có `id` (uuid, pk), `created_at`, `updated_at` (timestamptz, UTC). Hiển thị theo múi giờ Asia/Ho_Chi_Minh.

DB là PostgreSQL 16 chạy trong service `db` của Docker Compose trên chính VPS (xem `docs/06`). Toàn bộ schema quản lý bằng Alembic. Chỉ ứng dụng FastAPI kết nối DB, cổng Postgres không mở ra Internet.

## Phân quyền theo `role` (áp dụng trong code, ở tầng route/dependency)
Hai vai trò cố định, định nghĩa trong bảng `users` (đặc tả đăng nhập: `docs/08_LOGIN_DASHBOARD.md`).

| Dữ liệu | `giam_doc` | `ke_toan` |
|---|---|---|
| Duyệt/sửa/đăng bài, đổi AUTONOMY_LEVEL, kill switch, quản lý tài khoản | ✅ | ❌ |
| `leads` (danh sách, tóm tắt dự án, trạng thái) | ✅ | ✅ chỉ xem, ẩn cột `name`, `phone` |
| `post_metrics`, báo cáo tuần, `llm_usage` (chi phí) | ✅ | ✅ |
| Hội thoại Messenger (nội dung chi tiết) | ✅ | ❌ |
Đây là **giả định mặc định** — Giám đốc xác nhận hoặc đổi lại trước khi code Giai đoạn 0.

## Các bảng
| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `users` | username (unique), full_name, password_hash, role (giam_doc, ke_toan), is_active, telegram_chat_id (nullable), last_login_at, failed_attempts, last_failed_at, locked_until, totp_secret (nullable, dự phòng) | Đặc tả đầy đủ: `docs/08_LOGIN_DASHBOARD.md` |
| `sessions` | user_id, token_hash (unique), remember_me, expires_at, last_seen_at, ip, user_agent | Session phía server; cookie chỉ chứa token ngẫu nhiên, DB lưu hash |
| `research_items` | source_url, source_name, title, summary, topic (enum: hạ_tầng, quy_định, sự_cố_thấm, dự_án_mới, công_nghệ, esg, khác), relevance_score 0-100, fetched_at, used_in_post_id | url unique để chống trùng |
| `posts` | pillar, title, body, hashtags[], image_brief, image_url, sources[], kb_refs[], status, sensitive (bool), guardrail_report (jsonb), scheduled_at, published_at, fb_post_id, approved_by (→ users), approved_at | status theo `docs/02` |
| `post_metrics` | post_id, reach, impressions, reactions, comments, shares, clicks, fetched_at | A3 lấy lại sau 1h, 24h, 7 ngày |
| `contacts` | fb_psid (unique), name, phone, company, role, first_seen_at | phone mã hóa hoặc che khi log |
| `conversations` | contact_id, channel (messenger, comment), status (open, waiting_human, closed), last_customer_msg_at, window_expires_at | window_expires_at = +24h |
| `messages` | conversation_id, direction (in, out), sender (customer, ai, human), text, fb_mid (unique), guardrail_report, sent_at, draft (bool) | fb_mid chống xử lý trùng webhook |
| `leads` | contact_id, conversation_id, project_type, scale, stage, timeline, score (HOT, WARM, COLD, SPAM), summary, status (new, contacted, won, lost), assigned_to (→ users), alerted_at | HOT phải có alerted_at trong 15 phút |
| `jobs` | agent, kind, payload (jsonb), status (queued, running, done, failed), attempts, error, started_at, finished_at | |
| `alerts` | level (info, warn, urgent), channel, message, delivered_at | |
| `llm_usage` | agent, model, input_tokens, output_tokens, cache_read_tokens, cost_usd, job_id | báo cáo chi phí |
| `settings` | key, value | AUTONOMY_LEVEL, KILL_SWITCH, giờ làm việc, tần suất đăng, HOT_MIN_SCALE_NOTE |
| `audit_log` | actor (→ users, nullable cho hệ thống), action, entity, entity_id, detail | mọi thao tác đăng nhập/duyệt/đổi cấu hình |

## Chỉ mục bắt buộc
`users(username)` unique; `sessions(token_hash)` unique; `research_items(source_url)` unique; `messages(fb_mid)` unique; `posts(status, scheduled_at)`; `leads(score, status)`; `conversations(window_expires_at)`.

## Bảo vệ DB
- Ứng dụng dùng 1 role Postgres riêng (`bestone_app`), không dùng superuser `postgres` trong `DATABASE_URL`.
- Service `db` chỉ nằm trong mạng nội bộ Docker, không `ports:` ra ngoài.
- Sao lưu hằng ngày bằng `pg_dump` (xem `docs/06`, mục Backup).
