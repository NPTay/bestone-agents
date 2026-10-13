# 05 — Meta (Facebook) Integration

> Trước khi sửa code Meta, tra cứu tài liệu Meta for Developers hiện hành (phiên bản Graph API, tên quyền, quy trình App Review có thể đã đổi). Phiên bản được ghim trong `META_GRAPH_VERSION` (`.env`), không dùng "latest" ngầm định.

Chương trình chạy trên máy tính, không có địa chỉ công khai, nên **không dùng webhook**. Tin nhắn Messenger (Đợt 2) sẽ lấy bằng cách hỏi định kỳ Graph API.

## Điều kiện tiên quyết
Hướng dẫn từng bước cho Giám đốc nằm ở `docs/HUONG_DAN_CAI_DAT.md` mục 7: tạo Meta App loại Business, lấy App ID/Secret, token người dùng từ Graph API Explorer, rồi `python -m app.cli.setup_tools meta-token --user-token ...` đổi thành token Trang dài hạn và ghi vào `.env` (`META_PAGE_ACCESS_TOKEN`). Không commit token.

## Quyền
| Mục đích | Quyền | Đợt |
|---|---|---|
| Đăng bài, bình luận lên Page | `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` | 1 |
| Nhắn tin Messenger | `pages_messaging` | 2 |
| Đọc/trả lời bình luận khách | `pages_read_user_content`, `pages_manage_engagement` | ngoài phạm vi hiện tại |

**Chế độ Development:** đăng bài lên Page do chính quản trị viên của App quản trị chạy được mà không cần App Review. Cần App Review (và có thể xác minh doanh nghiệp) khi phục vụ khách thật, tức Đợt 2: xem `docs/CHUAN_BI_APP_REVIEW.md`.

## Đăng bài (`app/meta/graph.py`, `app/posts/publisher.py`)
- Một ảnh đăng qua `/{page-id}/photos`; nhiều ảnh hoặc không ảnh qua `/{page-id}/feed`; sau đó bình luận cố định bằng `/{post-id}/comments`.
- Lưu `fb_post_id` và `comment_id` vào DB. Lịch đăng do scheduler nội bộ kiểm soát, không dùng `scheduled_publish_time`.
- Lỗi token (code 190): báo Telegram, không retry. Các lỗi Graph khác được ghi log và báo Giám đốc.
- Lỗi mơ hồ sau khi gọi đăng (không biết đã lên hay chưa): không tự thử lại; báo Giám đốc kiểm tra Fanpage.
- `DRY_RUN=true` thì không gọi các lệnh ghi.

## Quy tắc nhắn tin (Đợt 2)
- Cửa sổ 24 giờ: chỉ trả lời trong 24 giờ kể từ tin cuối của khách; quá hạn thì không gửi, báo Giám đốc gọi điện.
- Không gửi tin quảng bá hàng loạt, không gửi lại tin đã gửi.

## Ảnh
Bài sáng: Pexels hoặc minh họa Gemini, không dùng ảnh từ báo/web. Bài chiều: ảnh trong `Picture/`. Ảnh AI không được giả làm công trình hay kết quả thí nghiệm thật.

## Tuân thủ
Không scrape Facebook, không dùng tài khoản cá nhân giả, không tự động bình luận vào Page/Group người khác, không mua/bán tương tác.
