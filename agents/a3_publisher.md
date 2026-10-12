# A3 — Publisher Agent (Đăng bài & đo lường)

## Vai trò
Thực thi đăng bài đã duyệt lên Fanpage đúng giờ, theo dõi hiệu quả, báo cáo tuần. Phần lớn là CODE xác định; LLM chỉ dùng để viết nhận định báo cáo tuần.

## Quy trình đăng
1. Mỗi phút chọn `posts` có `status=approved`, `scheduled_at <= now`, chưa có `fb_post_id`.
2. Kiểm tra kill switch, `AUTONOMY_LEVEL`, giới hạn 6 bài/ngày, khoảng cách tối thiểu 3 giờ giữa 2 bài.
3. Kiểm tra lại guardrail lần cuối (bài có thể đã được sửa tay).
4. Gọi Meta Graph (docs/05). Lưu `fb_post_id`, `published_at`, status `published`. Lỗi tạm thời: retry backoff; lỗi token: cảnh báo urgent, dừng.
5. Lấy insights sau 1h, 24h, 7 ngày -> `post_metrics`.
6. Idempotent: khóa theo `post_id`; không đăng lại khi restart giữa chừng.

## Báo cáo tuần (Chủ nhật 18:00)
Bảng: mỗi bài (chủ đề, trụ cột, reach, tương tác, click, tin nhắn phát sinh), top 2 và bottom 2, đề xuất điều chỉnh tuần sau (khung giờ, chủ đề). Đề xuất chỉ dựa trên dữ liệu; nếu mẫu < 8 bài ghi "chưa đủ dữ liệu kết luận".

## Prompt viết nhận định
```prompt
Bạn là chuyên viên phân tích truyền thông. Từ số liệu JSON các bài đăng trong tuần, viết nhận định ngắn cho Giám đốc bằng tiếng Việt: (1) điều hiệu quả nhất, (2) điều kém nhất, (3) 3 đề xuất cho tuần tới. Chỉ dựa trên số liệu được cung cấp. Nếu dữ liệu ít, nói rõ chưa đủ kết luận. Không chào hỏi, không văn hoa.
```

## Tiêu chí hoàn thành
Đăng thành công lên Page thử; không đăng trùng khi restart; retry đúng khi mô phỏng lỗi 5xx và rate limit; báo cáo tuần đúng số liệu insights.
