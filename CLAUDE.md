# CLAUDE.md — Bestone AI Agents (C.G. Engineering Việt Nam)

Đây là file bộ nhớ chính. Claude Code đọc file này ĐẦU TIÊN, sau đó đọc theo thứ tự trong mục "Bản đồ tài liệu".

## Sứ mệnh dự án
Xây hệ thống AI Agent chạy liên tục 24/7 trên VPS để quản lý Facebook Fanpage của C.G. Engineering Việt Nam (sản phẩm: phụ gia tự chống thấm Bestone): thu thập tin ngành, soạn bài, đăng bài, chăm sóc khách hàng qua Messenger/comment, chấm điểm và chuyển giao lead cho Giám đốc.

Bối cảnh: doanh nghiệp B2B siêu tinh gọn, không thêm nhân sự. Ưu tiên tự động hóa, chi phí hạ tầng thấp, dễ vận hành bởi 1 người không chuyên IT.

## Bản đồ tài liệu (đọc theo thứ tự)
1. `docs/01_PROJECT_BRIEF.md` — mục tiêu, KPI, phạm vi, ngoài phạm vi
2. `docs/02_ARCHITECTURE.md` — kiến trúc 5 agent, luồng dữ liệu, trạng thái
3. `docs/03_TECH_STACK_REPO_STRUCTURE.md` — công nghệ, cấu trúc thư mục cần tạo
4. `docs/04_DATA_SCHEMA.md` — bảng dữ liệu Postgres
5. `docs/05_META_INTEGRATION.md` — Facebook Graph API, webhook, quyền, giới hạn
6. `docs/06_DEPLOYMENT_VPS.md` — Docker Compose, Caddy, backup, giám sát
7. `docs/07_BUILD_PLAN_TASKS.md` — kế hoạch build theo giai đoạn, tiêu chí nghiệm thu
8. `docs/08_LOGIN_DASHBOARD.md` — đặc tả trang đăng nhập, phân quyền, phiên đăng nhập cho Dashboard
9. `knowledge/bestone_knowledge_base.md` — NGUỒN SỰ THẬT DUY NHẤT về sản phẩm
10. `knowledge/brand_voice.md`, `knowledge/guardrails_compliance.md`, `knowledge/content_pillars.md`
11. `agents/a0_orchestrator.md` … `agents/a4_customer_care.md` — system prompt + hợp đồng I/O từng agent

## Quy tắc bất biến (không được vi phạm khi viết code)
1. **Nguồn sự thật:** Mọi số liệu kỹ thuật, tên dự án, chứng nhận, giá chỉ được lấy từ `knowledge/bestone_knowledge_base.md`. Agent không có thông tin thì nói không có, không suy đoán. Không tự thêm tuổi thọ, năm bảo hành, chứng nhận.
2. **Human-in-the-loop mặc định:** Chế độ `AUTONOMY_LEVEL` = `draft_only` cho đến khi Giám đốc đổi sang `auto_safe`. Bài đăng và tin nhắn chỉ tự gửi khi cấu hình cho phép.
3. **Không báo giá, không cam kết bảo hành/hiệu năng** trong mọi tin nhắn tự động. Chuyển Giám đốc.
4. **Bí mật:** Không commit token, khóa API. Dùng biến môi trường (`.env.example` chỉ chứa tên biến). Secret (mật khẩu DB, `SESSION_SECRET_KEY`, token Meta, khóa API) không bao giờ được đưa vào response HTML/JS gửi cho trình duyệt. Không log mật khẩu (chi tiết `docs/08`).
5. **Idempotent & có log:** Mỗi tác vụ có `job_id`, ghi log vào DB, retry có giới hạn, không đăng trùng bài, không trả lời trùng tin nhắn.
6. **Tuân thủ Meta:** Chỉ dùng API chính thức. Không scrape Facebook. Tôn trọng cửa sổ nhắn tin 24 giờ.
7. **Ngôn ngữ:** Giao diện, prompt, bài đăng: tiếng Việt. Mã nguồn, tên biến, comment: tiếng Anh.
8. **Kiểm thử trước khi bàn giao:** Mỗi giai đoạn phải có test chạy được và nghiệm thu theo `docs/07`.

## Lệnh thường dùng
Dev local (Windows, chạy ở thư mục gốc repo):
- Tạo môi trường: `py -3.12 -m venv .venv` rồi `.venv/Scripts/python -m pip install -e ".[dev]"`
- Test: `.venv/Scripts/python -m pytest -q`
- Lint: `.venv/Scripts/ruff check .`; kiểm tra kiểu: `.venv/Scripts/mypy app`
- (PowerShell: dùng dấu `\` thay `/`, ví dụ `.venv\Scripts\python -m pytest -q`; Git Bash dùng `/`)
- Test mặc định chạy trên SQLite trong bộ nhớ. Để chạy trên Postgres thật (DB tạm riêng, không đụng DB production, không cần `.env`): `docker compose -f deploy/docker-compose.test.yml up -d db_test`, đặt `TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:5433/bestone_test` (bash: `export TEST_DATABASE_URL=...`; PowerShell: `$env:TEST_DATABASE_URL="..."`), rồi chạy pytest. Tắt: `docker compose -f deploy/docker-compose.test.yml down`. Bộ test từ chối chạy nếu tên DB không chứa "test". Test CLI/migration luôn dùng SQLite.

Docker / VPS (chạy ở thư mục gốc repo, cần file `.env` tạo từ `.env.example`):
- Cài VPS lần đầu: `sudo deploy/bootstrap.sh [ten_user_moi]`
- Chạy/cập nhật: `docker compose -f deploy/docker-compose.yml --env-file .env up -d --build` (migration `alembic upgrade head` tự chạy trong entrypoint)
- Tạo tài khoản Giám đốc lần đầu: điền `INITIAL_ADMIN_USERNAME`/`INITIAL_ADMIN_PASSWORD` trong `.env` → `docker compose -f deploy/docker-compose.yml --env-file .env up -d app` → `docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.cli.create_admin` → xóa hai biến đó khỏi `.env` → `up -d app` lại
- `APP_DOMAIN` bắt buộc trong `.env` (để trống thì compose dừng với thông báo lỗi). Chạy local: `APP_DOMAIN=localhost` (Caddy dùng CA nội bộ, mở `https://localhost`)
- Cập nhật phụ thuộc: `.venv/Scripts/python -m pip install pip-tools` rồi `.venv/Scripts/pip-compile --extra dev --output-file requirements.lock --strip-extras pyproject.toml` (Dockerfile dùng `pip install -c requirements.lock -e .`; file này là constraints nên không ép cài gói riêng Windows)
- Đặt lại mật khẩu: `docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.cli.reset_password --username <ten>`
- Kiểm tra nạp knowledge: `docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.knowledge.ingest`
- Backup DB thủ công: `deploy/backup.sh`
- Quay lại phiên bản cũ: xem `deploy/rollback.md`

## Chạy lần đầu (checklist theo thứ tự)
1. Điền `.env` (bootstrap tạo từ `.env.example`): `APP_DOMAIN` (bắt buộc), `BACKUP_S3_*` (bắt buộc cho backup ngoài VPS), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT_ID` (nhận cảnh báo backup).
2. `sudo deploy/bootstrap.sh [ten_user_moi]` (chạy lại sau khi điền `.env` nếu script dừng vì thiếu `APP_DOMAIN`).
3. Tạo Giám đốc: điền `INITIAL_ADMIN_*` → `up -d app` → `exec app python -m app.cli.create_admin` → xóa `INITIAL_ADMIN_*` → `up -d app`.
4. Chạy thử `deploy/backup.sh` (phải thấy "uploaded to S3") và thử khôi phục vào DB tạm theo `deploy/rollback.md` mục 5.

## Trạng thái
- Giai đoạn 0 (khung + đăng nhập Dashboard): code xong trên nhánh `phase0-skeleton-auth`; test xanh (128 test pass, ruff và mypy sạch).
- CHƯA kiểm chứng chạy thật bằng Docker (máy dev chưa có Docker).
- Việc còn lại: chạy thử Docker theo `docs/06`.
- Vai trò Kế toán (`ke_toan`): code có sẵn nhưng CHƯA kích hoạt — Giám đốc quyết định chưa dùng (12/10/2026). Không tạo tài khoản Kế toán, không làm thêm tính năng cho vai trò này cho đến khi Giám đốc yêu cầu.
- Giai đoạn 1 (A1 + A2 + Dashboard duyệt bài): đang làm trên nhánh `phase1-content-pipeline`.

## Cách làm việc với người dùng
- Người dùng (Giám đốc) không phải lập trình viên. Giải thích ngắn gọn, đưa lệnh copy-paste được.
- Trước khi làm điều không thể hoàn tác (xóa dữ liệu, đăng bài thật, gửi tin thật), phải xác nhận.
- Khi thiếu thông tin (token, ID Page, tên miền, VPS), liệt kê rõ cần gì, không tự bịa giá trị.
