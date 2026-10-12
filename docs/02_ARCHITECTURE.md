# 02 — Architecture

## Nguyên tắc thiết kế
- Một codebase Python, một Postgres, chạy bằng Docker Compose trên 1 VPS. Không microservice.
- Agent = module Python có system prompt (từ `agents/*.md`) + công cụ (tools) + hợp đồng vào/ra JSON có schema.
- LLM chỉ quyết định nội dung và phân loại. Việc gọi API Facebook, lên lịch, retry do code xác định thực hiện.
- Mọi output của LLM đi qua bộ kiểm tra guardrail (regex + LLM-judge) trước khi đăng/gửi.

## Sơ đồ luồng
```
[Scheduler] -> A1 Research -> (research_items) -> A2 Content -> (posts: draft)
                                                        |
                                            [Guardrail check] -> [Admin duyệt qua Dashboard/Telegram]
                                                        |
                                                   A3 Publisher -> Facebook Page API -> (metrics) -> báo cáo tuần

[Facebook Webhook: messages/comments] -> A4 Customer Care -> [Guardrail check]
        -> trả lời tự động (nếu AUTONOMY cho phép) hoặc tạo nháp cho người duyệt
        -> Lead scoring -> leads -> nếu NÓNG: cảnh báo GĐ (Telegram/Email) trong 15 phút

A0 Orchestrator: giám sát job, hàng đợi lỗi, chi phí token, báo cáo hằng ngày/tuần, kill-switch.
```

## Các agent
| Agent | Kích hoạt | Đọc | Ghi |
|---|---|---|---|
| A0 Orchestrator | cron + sự kiện | jobs, logs, metrics | reports, alerts |
| A1 Research | cron (T2 và hằng ngày) | RSS, web search, cổng đấu thầu | research_items |
| A2 Content | sau A1, theo lịch | research_items, knowledge, content_pillars | posts (draft) |
| A3 Publisher | posts đã duyệt tới giờ | posts | posts.status, post_metrics |
| A4 Customer Care | webhook Messenger/comment | knowledge, conversations | messages, leads, alerts |

## Trạng thái bài đăng
`idea -> draft -> guardrail_failed | pending_approval -> approved -> scheduled -> published | failed`

## Mức tự động hóa (`AUTONOMY_LEVEL`)
- `draft_only`: mọi bài và mọi trả lời đều chờ người duyệt/gửi. (Mặc định)
- `auto_safe`: A4 tự trả lời nhóm câu hỏi an toàn (giới thiệu, quy trình, thông tin có trong knowledge). Bài đăng nhạy cảm vẫn duyệt.
- `auto_full`: bài thường tự đăng; chỉ duyệt bài chứa tên dự án, số liệu, so sánh đối thủ.
Giám đốc đổi mức trong dashboard. Có KILL SWITCH tắt toàn bộ gửi/đăng tức thì.

## Bài đăng "nhạy cảm" (luôn phải duyệt dù ở mức nào)
Chứa: tên dự án/khách hàng, số liệu kỹ thuật, so sánh đối thủ, giá, tin chính trị/pháp lý, hình ảnh người thật.

## Chọn LLM
- Soạn bài, tư vấn kỹ thuật: mô hình mạnh (`MODEL_QUALITY`, mặc định `claude-sonnet-5-5`).
- Phân loại nhanh, chấm lead, tóm tắt tin: mô hình nhẹ (`MODEL_FAST`, mặc định `claude-haiku-5-5`).
- Bật prompt caching cho knowledge base (đưa toàn văn vào system prompt vì kho tri thức nhỏ). Chỉ thêm vector DB khi kho vượt vài trăm trang.
