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

## Lệnh thường dùng (Claude Code cập nhật khi tạo xong)
- Chạy local: `docker compose up --build`
- Test: `pytest -q`
- Migrate DB (Postgres trong container `db`): `alembic upgrade head` (tự chạy khi `app` khởi động)
- Seed knowledge: `python -m app.knowledge.ingest`
- Tạo tài khoản Giám đốc lần đầu: `python -m app.cli.create_admin`
- Đặt lại mật khẩu: `python -m app.cli.reset_password`
- Backup DB thủ công: `deploy/backup.sh`

## Cách làm việc với người dùng
- Người dùng (Giám đốc) không phải lập trình viên. Giải thích ngắn gọn, đưa lệnh copy-paste được.
- Trước khi làm điều không thể hoàn tác (xóa dữ liệu, đăng bài thật, gửi tin thật), phải xác nhận.
- Khi thiếu thông tin (token, ID Page, tên miền, VPS), liệt kê rõ cần gì, không tự bịa giá trị.
