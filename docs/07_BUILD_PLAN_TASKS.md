# 07 — Build Plan & Acceptance Criteria

Claude Code làm TUẦN TỰ theo giai đoạn. Kết thúc mỗi giai đoạn: chạy test, cập nhật `CLAUDE.md` (lệnh, trạng thái), báo người dùng những gì cần họ cung cấp/duyệt.

## Giai đoạn 0 — Khung dự án (1-2 ngày)
- Tạo cấu trúc `docs/03`, `pyproject.toml`, Dockerfile, docker-compose (`app` + `db` + `caddy`), `/health`, config, Alembic + toàn bộ bảng `docs/04`.
- Nạp `knowledge/*.md` và `agents/*.md` bằng `llm/prompts.py`.
- Đăng nhập theo `docs/08`: bảng `users` + `sessions`, trang `/login`, cookie session, CSRF, khóa tài khoản, `require_login`, `require_role("giam_doc")`, CLI `create_admin`/`reset_password`.
- `deploy/backup.sh` + job backup hằng ngày.
- **Nghiệm thu:** `docker compose up` chạy local, `/health` = 200, `pytest` xanh, đăng nhập được bằng 2 tài khoản và đúng phân quyền theo bảng ở `docs/04`, đạt toàn bộ tiêu chí mục 7 của `docs/08`, chạy backup + khôi phục thử thành công.

## Giai đoạn 1 — Content pipeline (A1 + A2 + Dashboard duyệt)
- A1: RSS + web search, khử trùng, chấm relevance, lưu `research_items`.
- A2: sinh lịch 5 bài/tuần theo `content_pillars.md`, soạn bài theo `brand_voice.md`, chạy guardrail, lưu `posts` ở `pending_approval`.
- Dashboard (dùng đăng nhập đã làm ở Giai đoạn 0): danh sách bài, xem/sửa/duyệt/từ chối, xem báo cáo guardrail, đổi `AUTONOMY_LEVEL`, kill switch.
- Thông báo Telegram khi có bài chờ duyệt (kèm link duyệt nhanh).
- **Nghiệm thu:** chạy khô sinh 5 bài; 100% bài có nguồn hoặc trích từ knowledge; 0 bài chứa số liệu ngoài knowledge (test tự động bằng bộ kiểm tra số liệu); GĐ duyệt được trên điện thoại.

## Giai đoạn 2 — Publisher (A3)
- Kết nối Meta Graph (đăng text/ảnh, lên lịch nội bộ, lấy insights). Idempotent (không đăng trùng).
- Báo cáo tuần Chủ nhật 18:00 gửi Telegram/Email.
- **Nghiệm thu:** đăng thành công 1 bài lên Page thử (test page), retry đúng khi lỗi giả lập, báo cáo tuần đúng số liệu.

## Giai đoạn 3 — Customer Care (A4) chế độ nháp
- Webhook Meta (kiểm chữ ký, chống trùng), hội thoại, A4 soạn nháp, chấm lead, phiếu lead, cảnh báo lead HOT.
- Dashboard hộp thư: GĐ xem nháp, bấm gửi/sửa.
- **Nghiệm thu:** bộ 30 hội thoại kiểm thử (`tests/care_scenarios.yaml`, gồm cả câu hỏi bẫy: hỏi giá, đòi cam kết bảo hành, hỏi ngoài kho tri thức, chửi/khiếu nại, tin rác) đạt: 0 báo giá, 0 cam kết, 100% chuyển người đúng tiêu chí, lead HOT cảnh báo < 15 phút.

## Giai đoạn 4 — Tự động hóa có kiểm soát
- `auto_safe` cho A4 (nhóm câu hỏi an toàn), `auto_full` cho bài không nhạy cảm. Trả lời comment công khai.
- A0 báo cáo hằng ngày, giới hạn chi phí, cảnh báo sức khỏe hệ thống.
- **Nghiệm thu:** chạy 7 ngày liên tục không can thiệp, 0 lỗi nghiêm trọng, kill switch tắt gửi/đăng trong < 5 giây.

## Giai đoạn 5 — Tối ưu & mở rộng
A/B khung giờ/chủ đề theo `post_metrics`; kho tri thức mở rộng khi có hồ sơ dự án Việt Nam; nhật ký lead sang CRM; LinkedIn, Zalo OA.

## Việc người dùng phải cung cấp (Claude Code nhắc khi tới lúc)
Khóa Anthropic API; Page ID + quyền admin Page; tài khoản Meta Developer; tên miền + VPS; Telegram bot token; danh sách ảnh/tài liệu được phép dùng; hồ sơ dự án Việt Nam đã xác thực; ngưỡng "dự án đủ lớn" để xếp lead HOT; tài khoản object storage S3-compatible cho backup; xác nhận phân quyền Kế toán đúng như đề xuất ở `docs/04`.
