# CLAUDE.md — Bestone AI Agents (C.G. Engineering Việt Nam)

Đây là file bộ nhớ chính. Claude Code đọc file này ĐẦU TIÊN, sau đó đọc theo thứ tự trong mục "Bản đồ tài liệu".

## Sứ mệnh dự án
Chương trình chạy ngay trên máy tính Windows của Giám đốc (không VPS, không Docker, không đăng nhập) để quản lý Facebook Fanpage của C.G. Engineering Việt Nam (sản phẩm: phụ gia tự chống thấm Bestone): mỗi ngày soạn 2 bài (sáng từ tin ngành, chiều từ tài liệu và ảnh công trình), gửi Telegram cho Giám đốc duyệt bằng nút bấm hoặc góp ý, đăng ngay khi Giám đốc bấm duyệt và bình luận giới thiệu cố định dưới bài. Trang "Hôm nay" trên máy (127.0.0.1) chỉ để xem. Trả lời Messenger là Đợt 2.

Bối cảnh: doanh nghiệp B2B siêu tinh gọn, một người dùng duy nhất (Giám đốc, không chuyên IT), không thêm nhân sự.

## Bản đồ tài liệu (đọc theo thứ tự)
1. `docs/superpowers/specs/2026-10-13-local-fanpage-agents-design.md` — thiết kế đã được Giám đốc duyệt (nguồn quyết định)
2. `docs/01_PROJECT_BRIEF.md` — mục tiêu, phạm vi, ngoài phạm vi
3. `docs/02_ARCHITECTURE.md` — các thành phần, luồng dữ liệu, trạng thái bài
4. `docs/05_META_INTEGRATION.md` — Graph API, quyền, giới hạn
5. `docs/HUONG_DAN_CAI_DAT.md` — hướng dẫn cài đặt và vận hành cho Giám đốc
6. `docs/CHUAN_BI_APP_REVIEW.md` và `docs/chinh_sach_quyen_rieng_tu.html` — hồ sơ cho Đợt 2
7. `knowledge/bestone_knowledge_base.md` — NGUỒN SỰ THẬT DUY NHẤT về sản phẩm
8. `knowledge/brand_voice.md`, `knowledge/guardrails_compliance.md`, `knowledge/content_pillars.md`
9. `agents/a2_content.md`, `agents/guardrail_judge.md` (đang dùng); `agents/a1_research.md`, `agents/a4_customer_care.md` (tham chiếu, a4 dành cho Đợt 2)

## Quy tắc bất biến (không được vi phạm khi viết code)
1. **Nguồn sự thật:** Mọi số liệu kỹ thuật, tên dự án, chứng nhận chỉ được lấy từ `knowledge/bestone_knowledge_base.md`. Không có thông tin thì nói không có, không suy đoán. Không tự thêm tuổi thọ, năm bảo hành, chứng nhận, giá. Một thư mục công trình trong `Picture/` chỉ được nêu tên khi mục tương ứng ở mục 13 của KB không còn `[GĐ BỔ SUNG]`.
2. **Mọi thứ đi ra ngoài cần Giám đốc duyệt trên Telegram** (bài đăng, và sau này câu trả lời khách), trừ bình luận giới thiệu cố định sau bài đã duyệt. Bài chưa duyệt đến 20:00 thì bỏ, không dời sang hôm sau. Chỉ nghe cập nhật Telegram từ `TELEGRAM_ADMIN_CHAT_ID`.
3. **Không báo giá, không cam kết bảo hành/hiệu năng** trong mọi nội dung tự động.
4. **Bí mật:** Không commit token, khóa API. Dùng `.env` (gitignored); `.env.example` chỉ chứa tên biến và phải khớp `app/config.py`. Secret không bao giờ vào HTML/JS gửi trình duyệt, log hay thông báo lỗi (URL Telegram chứa token bot, lời gọi Graph mang token Trang).
5. **Idempotent & có log:** Mỗi tác vụ ghi trạng thái vào DB, retry có giới hạn, không đăng trùng bài. Bài kẹt ở `publishing` không bao giờ tự thử lại (có thể đã đăng); báo Giám đốc kiểm tra Fanpage. Chỉ một tiến trình được chạy. `DRY_RUN=true` (mặc định) thì không ghi gì lên Facebook.
6. **Tuân thủ Meta:** Chỉ dùng API chính thức. Không scrape Facebook. Tôn trọng cửa sổ nhắn tin 24 giờ (Đợt 2).
7. **Ngôn ngữ:** Giao diện, prompt, bài đăng, tin Telegram: tiếng Việt. Mã nguồn, tên biến, comment: tiếng Anh.
8. **Kiểm thử trước khi bàn giao:** Test chạy được, không bao giờ gọi mạng thật (dùng respx và FakeLLM/FakeTelegram), không đọc `.env` thật.
9. **Ảnh:** Bài sáng chỉ dùng ảnh Unsplash hoặc minh họa Gemini, không dùng ảnh từ bài báo; ảnh Gemini không được giả làm công trình hay kết quả thí nghiệm thật. Bài chiều chỉ dùng ảnh trong `Picture/` trừ `config/picture_exclude.txt`. `Picture/` và `Tai Lieu/` là thư viện của Giám đốc, đã gitignore, không sửa, không commit.

## Lệnh thường dùng
Dev local (Windows, thư mục gốc repo; PowerShell dùng `\`, Git Bash dùng `/`):
- Tạo môi trường và cài: `scripts\setup.ps1` (hoặc `py -3.12 -m venv .venv` rồi `.venv/Scripts/python -m pip install -e ".[dev]"`)
- Test: `.venv/Scripts/python -m pytest -q`
- Lint: `.venv/Scripts/ruff check .`; kiểm tra kiểu: `.venv/Scripts/mypy app`
- Chạy chương trình: `.venv/Scripts/python -m app` (hoặc `scripts\start.ps1` sau khi đã đăng ký tự chạy)
- Đăng ký / gỡ tự chạy khi đăng nhập Windows: `scripts\install_autostart.ps1` / `scripts\uninstall_autostart.ps1`
- Công cụ cài đặt: `.venv/Scripts/python -m app.cli.setup_tools telegram-chat-id | meta-token --user-token <token> | check`
- Trích đề xuất từ catalogue PDF (ra `knowledge/catalogue_proposals.md`, chương trình không đọc file này): `.venv/Scripts/python -m app.cli.catalogue`
- Nhật ký: `data/logs/app.log`

## Trạng thái
- Đợt 1 (đăng bài: bài sáng + bài chiều, duyệt Telegram, đăng ngay khi duyệt, bình luận cố định, trang "Hôm nay", tự chạy cùng Windows, công cụ cài đặt) đã xây xong trên nhánh `desktop-dot1`; test xanh.
- CHƯA kiểm chứng với khóa thật của Giám đốc, với Task Scheduler thật, và chưa đăng bài thật. Việc còn lại: làm theo `docs/HUONG_DAN_CAI_DAT.md`, chạy `DRY_RUN=true` vài ngày, rồi mới `DRY_RUN=false`.
- Đợt 2 (trả lời tin nhắn Messenger) làm sau; cần Meta App Review cho `pages_messaging`, xem `docs/CHUAN_BI_APP_REVIEW.md`.
- Thông tin công trình ở mục 13 của KB còn `[GĐ BỔ SUNG]`: Giám đốc cần điền.

## Cách làm việc với người dùng
- Người dùng (Giám đốc) không phải lập trình viên. Giải thích ngắn gọn, đưa lệnh copy-paste được.
- Trước khi làm điều không thể hoàn tác (xóa dữ liệu, đăng bài thật, gửi tin thật), phải xác nhận.
- Khi thiếu thông tin (token, ID Page), liệt kê rõ cần gì, không tự bịa giá trị.
