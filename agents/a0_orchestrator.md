# A0 — Orchestrator (Điều phối & Giám sát)

## Vai trò
Không tự soạn nội dung. Đảm bảo hệ thống chạy đúng, an toàn, rẻ; báo cáo cho Giám đốc.

## Trách nhiệm (phần lớn là CODE, LLM chỉ để viết báo cáo)
- Đăng ký cron (`scheduler.py`): A1 hằng ngày 06:30 (+ quét sâu Thứ Hai), A2 Thứ Hai 07:30 (lịch tuần) và hằng ngày (soạn bài), A3 mỗi phút kiểm tra bài tới giờ, A3 báo cáo tuần Chủ nhật 18:00, A0 báo cáo ngày 08:00.
- Hàng đợi `jobs`: retry tối đa 3 lần (backoff), đánh dấu `failed`, cảnh báo nếu một loại job thất bại liên tiếp 3 lần.
- Kiểm soát: `AUTONOMY_LEVEL`, kill switch, giới hạn 6 bài/ngày, giới hạn chi phí `DAILY_COST_LIMIT_USD` (vượt -> chuyển `draft_only` và cảnh báo).
- SLA lead: mỗi phút quét `leads` HOT chưa `alerted_at`; quá 10 phút gửi cảnh báo urgent lặp lại.
- Sức khỏe: kiểm tra token Meta (gọi `debug_token` hằng ngày), webhook im lặng > 24 giờ, dung lượng đĩa, backup gần nhất.

## Đầu vào / Đầu ra
- Đọc: `jobs`, `llm_usage`, `posts`, `leads`, `conversations`, `alerts`.
- Ghi: `alerts`, báo cáo (Telegram + email + trang dashboard).

## Prompt viết báo cáo (LLM nhẹ)
```prompt
Bạn là trợ lý điều hành của C.G. Engineering Việt Nam. Từ dữ liệu JSON được cung cấp, viết báo cáo cho Giám đốc bằng tiếng Việt, ngắn, dữ liệu là chính, không chào hỏi.
Cấu trúc bắt buộc:
1. VIỆC CẦN BẠN LÀM NGAY (tối đa 5 dòng: bài chờ duyệt, lead HOT chưa liên hệ, hội thoại chờ người, lỗi cần xử lý)
2. SỐ LIỆU: bài đã đăng/chờ duyệt, tin nhắn nhận/trả lời, thời gian phản hồi trung bình, lead mới theo mức, chi phí LLM
3. BẤT THƯỜNG (chỉ nếu có)
Chỉ dùng số liệu trong JSON. Không suy đoán, không bịa số.
```

## Tiêu chí hoàn thành
Test mô phỏng: job lỗi 3 lần -> alert; chi phí vượt ngưỡng -> chuyển draft_only; lead HOT không xử lý 10 phút -> alert urgent.
