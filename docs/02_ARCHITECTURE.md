# 02 — Architecture (Đợt 1, chạy trên máy tính)

Một tiến trình Python duy nhất (`python -m app`, chạy ngầm bằng `pythonw`), khởi động bởi Windows Task Scheduler khi Giám đốc đăng nhập. Không VPS, Docker, Postgres hay đăng nhập. Dữ liệu trong SQLite `data/bestone.db`.

## Thành phần
| Thành phần | Mã | Việc |
|---|---|---|
| Runner | `app/runner.py` | Khóa một-tiến-trình, ghi log `data/logs/app.log`, chạy 3 luồng: vòng `tick` mỗi 60 giây, poller Telegram, web "Hôm nay" |
| Scheduler | `app/scheduler.py`, `app/schedule_times.py` | Quyết định mỗi tick: soạn bài sáng/chiều, đăng bài đã duyệt, bỏ bài quá 20:00, thử lại soạn lỗi (10 phút/lần, tối đa 3) |
| Nội dung | `app/content/` | `research.py` tìm tin (bài sáng), `pictures.py` chọn ảnh `Picture`, `images.py` Pexels/Gemini, `writer.py` viết và sửa bài |
| Guardrail | `app/guardrails/` | Luật cứng bằng code (`rules.py`) + LLM judge (`judge.py`) đối chiếu KB |
| LLM | `app/llm/` | Gọi Claude, prompt, ghi chi phí |
| Telegram | `app/telegram/` | `bot.py` (API, long-polling), `review.py` (định dạng tin duyệt), `handler.py` (nút bấm, Reply góp ý) |
| Đăng bài | `app/posts/`, `app/meta/graph.py` | `store.py` (trạng thái), `publisher.py` (đăng ảnh + bình luận cố định qua Graph API) |
| Web | `app/web/` | Trang "Hôm nay" chỉ xem, nghe `127.0.0.1:DASHBOARD_PORT` |
| CLI | `app/cli/` | `setup_tools` (chat id, token Trang, kiểm tra), `catalogue` (đề xuất từ PDF) |

## Luồng một bài
1. `tick` thấy đến giờ soạn (08:00 sáng, 15:00 chiều; bật máy muộn thì soạn ngay nếu còn trước 12:00 cho bài sáng) và chưa có bài trong ngày/khung đó.
2. Writer viết theo `knowledge/`, guardrail kiểm tra, chọn ảnh, lưu `Post` trạng thái `pending`, gửi Telegram kèm nút "Đăng" / "Không đăng".
3. Giám đốc bấm nút (`approved` hoặc `rejected`) hoặc Reply góp ý (tạo revision mới, nút cũ vô hiệu).
4. Đã duyệt và đến giờ (09:00 / 16:30) thì `tick` chuyển `publishing`, đăng lên Facebook, lưu `fb_post_id`, bình luận cố định, chuyển `published`. Duyệt sau giờ thì đăng ở tick kế tiếp.
5. Đến 20:00 bài còn `pending` chuyển `expired` và báo Telegram.

Trạng thái bài: `drafting`, `pending`, `approved`, `publishing`, `published`, `rejected`, `expired`.

## An toàn và độ bền
- `DRY_RUN=true`: không ghi gì lên Graph API, chỉ log và đánh dấu đã đăng.
- Bài kẹt `publishing` (sập giữa lúc đăng) không tự thử lại; báo Giám đốc kiểm tra Fanpage để khỏi đăng trùng.
- Lỗi token Facebook (code 190) báo Telegram để làm lại bước `meta-token`.
- Bật muộn, tắt giữa ngày, mất mạng: trạng thái nằm trong DB, việc đã xong không làm lại.
- Chỉ nhận cập nhật Telegram từ `TELEGRAM_ADMIN_CHAT_ID`. Log không chứa khóa/token.

## Đợt 2 (chưa làm)
Hỏi định kỳ Graph API để lấy tin nhắn Messenger (không có webhook vì không có địa chỉ công khai), AI soạn trả lời, Giám đốc duyệt qua Telegram. Tham chiếu: `agents/a4_customer_care.md`.
