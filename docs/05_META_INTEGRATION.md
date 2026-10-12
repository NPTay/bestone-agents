# 05 — Meta (Facebook) Integration

> Claude Code: trước khi code, tra cứu tài liệu Meta for Developers hiện hành (phiên bản Graph API, tên quyền, quy trình App Review có thể đã đổi). Ghim phiên bản trong `config.py` (`META_GRAPH_VERSION`), không dùng "latest" ngầm định.

## Điều kiện tiên quyết (người dùng phải làm, hướng dẫn từng bước cho họ)
1. Tài khoản Meta Business + Fanpage do chính công ty quản trị.
2. Tạo Facebook App (loại Business), thêm sản phẩm Messenger và Webhooks.
3. Xác minh doanh nghiệp (Business Verification) nếu Meta yêu cầu để cấp quyền nâng cao.
4. Tạo Page Access Token dài hạn cho Page; lưu vào `.env` (`META_PAGE_ACCESS_TOKEN`), không commit.
5. Đặt Callback URL webhook = `https://<domain>/webhook/meta`, Verify Token = `META_VERIFY_TOKEN`.

## Quyền cần dùng (kiểm tra tên chính xác trong tài liệu hiện hành)
| Mục đích | Quyền thường dùng |
|---|---|
| Đăng bài lên Page | `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` |
| Nhắn tin Messenger | `pages_messaging` |
| Đọc/trả lời comment | `pages_read_user_content`, `pages_manage_engagement` |
| Số liệu | `read_insights` |
Ở chế độ Development, chỉ admin/tester của App dùng được. Cần App Review để phục vụ khách thật: chuẩn bị video demo, mô tả use case, chính sách quyền riêng tư (URL công khai).

## Webhook (`routers/webhook.py`)
- `GET /webhook/meta`: xác thực `hub.verify_token`, trả `hub.challenge`.
- `POST /webhook/meta`: BẮT BUỘC kiểm tra chữ ký `X-Hub-Signature-256` bằng App Secret; sai chữ ký trả 403.
- Trả 200 nhanh (< 5 giây), đẩy xử lý vào hàng đợi `jobs`. Chống trùng bằng `messages.fb_mid`.
- Đăng ký sự kiện: `messages`, `messaging_postbacks`, `feed` (comment).

## Quy tắc nhắn tin
- Cửa sổ 24 giờ: chỉ trả lời tự do trong 24 giờ kể từ tin cuối của khách. Ngoài cửa sổ: không gửi tự động; báo GĐ liên hệ qua điện thoại/Zalo.
- Nút "Human handover": khi khách yêu cầu gặp người, dừng AI trên hội thoại đó (`conversations.status = waiting_human`).
- Không gửi tin quảng bá hàng loạt. Không gửi lại tin đã gửi.
- Bật typing indicator và trễ ngắn tự nhiên (2-5 giây) trước khi gửi.

## Đăng bài
- Dùng Pages API `/{page-id}/feed` (text/link) và `/{page-id}/photos` (ảnh). Hỗ trợ lên lịch bằng `scheduled_publish_time` hoặc scheduler nội bộ (ưu tiên nội bộ để kiểm soát).
- Sau khi đăng: lưu `fb_post_id`; lấy insights sau 1h, 24h, 7 ngày.
- Tôn trọng giới hạn tốc độ: xử lý lỗi 4/17/32/613 (rate limit) bằng backoff; lỗi token (code 190) gửi cảnh báo urgent cho GĐ.

## Ảnh cho bài đăng
Giai đoạn 1: A2 tạo `image_brief` (mô tả ảnh cần dùng); người dùng cung cấp ảnh thật từ thư viện công ty (`assets/`). Không tự sinh ảnh giả về công trình thật hoặc kết quả thí nghiệm. Ảnh/biểu đồ từ brochure chỉ dùng khi có quyền sử dụng của công ty.

## Tuân thủ
Không scrape Facebook, không dùng tài khoản cá nhân giả, không tự động bình luận vào Page/Group người khác, không mua/bán tương tác.
