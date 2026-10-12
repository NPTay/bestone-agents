# 08 — Trang đăng nhập & Xác thực Dashboard

Bổ sung cho `docs/03` (Dashboard) và Giai đoạn 0 trong `docs/07`. Đăng nhập do ứng dụng tự quản lý trên Postgres của VPS, không dùng dịch vụ auth bên ngoài. File này là đặc tả duy nhất cho việc đăng nhập — Claude Code code theo đây, không tự bổ sung cơ chế khác (không tự thêm đăng nhập Google, không tự thêm OTP nếu không được yêu cầu).

## 1. Ai đăng nhập được
Mô hình vận hành hiện tại chỉ có 2 người dùng cố định. Dùng bảng `users` thay vì 1 cặp `ADMIN_USER`/`ADMIN_PASSWORD_HASH` cứng trong `.env`, để dễ thêm/khóa tài khoản mà không phải sửa code:

| role | Quyền |
|---|---|
| `giam_doc` | Toàn quyền: duyệt/từ chối bài, xem hộp thư A4, đổi AUTONOMY_LEVEL, bật kill switch, xem báo cáo chi phí, quản lý tài khoản |
| `ke_toan` | Chỉ xem: báo cáo tuần, báo cáo chi phí LLM, danh sách lead đã ẩn tên và SĐT (không sửa được autonomy/kill switch, không duyệt bài, không xem nội dung hội thoại) |

Bảng `users` và `sessions`: định nghĩa trong `docs/04_DATA_SCHEMA.md`. Mật khẩu băm bằng `argon2`.

Tài khoản đầu tiên (`giam_doc`) được tạo bằng script `app/cli/create_admin.py` chạy 1 lần khi triển khai (đọc từ biến môi trường lúc khởi tạo, sau đó không dùng biến môi trường nữa). Không có chức năng tự đăng ký (self sign-up).

## 2. Giao diện trang đăng nhập
- Đường dẫn: `/login`. Mọi route dashboard khác redirect về đây nếu chưa đăng nhập.
- Bố cục: căn giữa màn hình, nền trắng/xám nhạt, khối form rộng khoảng 360-400px.
- Nội dung trên form từ trên xuống: logo/tên "C.G. Engineering — Bestone Console" (chữ, chưa cần ảnh logo thật), ô "Tên đăng nhập", ô "Mật khẩu" (có icon ẩn/hiện mật khẩu), checkbox "Ghi nhớ đăng nhập", nút "Đăng nhập" full width, dòng nhỏ "Quên mật khẩu? Liên hệ Giám đốc" (không có luồng tự đổi mật khẩu qua email ở giai đoạn này vì chỉ 2 người dùng).
- Thông báo lỗi: một dòng chung "Sai tên đăng nhập hoặc mật khẩu" cho mọi trường hợp sai (không tiết lộ username có tồn tại hay không).
- Không có nút "Đăng nhập bằng Google/Facebook".
- Responsive: dùng được trên điện thoại (Giám đốc duyệt bài trên điện thoại theo `docs/07`).
- Ngôn ngữ: tiếng Việt, giọng gọn theo `knowledge/brand_voice.md` (không cần văn thương hiệu ở đây vì đây là màn hình nội bộ, không phải nội dung marketing).

## 3. Luồng xử lý đăng nhập (backend)
1. `POST /login` nhận `username`, `password`, `remember_me`.
2. Nếu tài khoản có `locked_until` còn hiệu lực → từ chối, hiện "Tài khoản tạm khóa, thử lại sau [thời gian]".
3. So khớp mật khẩu bằng `bcrypt` hoặc `argon2` (không tự chọn thuật toán yếu hơn). So sai:
   - Tăng `failed_attempts`.
   - Từ 5 lần sai liên tiếp trong 15 phút → khóa 15 phút (`locked_until`), ghi `audit_log`, gửi cảnh báo Telegram mức `warn` cho `giam_doc` (nghi ngờ dò mật khẩu).
4. Đúng mật khẩu và tài khoản `is_active`:
   - Reset `failed_attempts` về 0, cập nhật `last_login_at`.
   - Tạo session (xem mục 4), ghi `audit_log` (action=`login_success`).
   - Chuyển hướng theo `role`: `giam_doc` → `/dashboard`, `ke_toan` → `/reports`.

## 4. Cơ chế phiên đăng nhập (session)
- Dùng session cookie phía server (không dùng JWT lưu localStorage — tránh rủi ro XSS đánh cắp token trong dashboard có hiển thị nội dung do AI/khách hàng tạo ra).
- Cookie: `HttpOnly`, `Secure` (bắt buộc vì chạy sau Caddy HTTPS), `SameSite=Lax`.
- Thời hạn: không tích "Ghi nhớ" → hết khi đóng trình duyệt hoặc sau 8 giờ không hoạt động. Có tích "Ghi nhớ" → 30 ngày.
- `POST /logout`: xóa session, ghi `audit_log`.
- Toàn bộ route dưới `/dashboard`, `/reports`, `/admin_api/*` đi qua middleware kiểm tra session hợp lệ + đúng `role` cho từng route. Route nào yêu cầu `giam_doc` mà tài khoản là `ke_toan` → trả 403, không hiện âm thầm.

## 5. Bảo mật bắt buộc (không tùy chọn)
- CSRF token cho form đăng nhập và mọi form ghi dữ liệu trong dashboard.
- Giới hạn tốc độ theo IP ở tầng Caddy hoặc middleware (ví dụ tối đa 10 lần thử/phút/IP) để chống dò mật khẩu hàng loạt, độc lập với khóa theo tài khoản ở mục 3.
- Không log mật khẩu dưới bất kỳ hình thức nào (kể cả log lỗi).
- Không có API đăng nhập trả JSON token cho bên ngoài — dashboard chỉ phục vụ trình duyệt nội bộ công ty, không mở API xác thực công khai.
- Đổi mật khẩu: có trang `/account/change-password` (bắt buộc nhập mật khẩu cũ), không có "quên mật khẩu" tự động qua email ở giai đoạn này — Giám đốc đổi thủ công qua CLI (`app/cli/reset_password.py`) nếu quên, vì chỉ 2 tài khoản.

## 6. Việc KHÔNG làm ở giai đoạn này (tránh Claude Code tự thêm quá tay)
- Không tự thêm đăng nhập mạng xã hội (SSO Google/Facebook).
- Không tự thêm 2FA/OTP nếu chưa được yêu cầu — có thể để trống cột `totp_secret` dự phòng trong `users` cho tương lai, không bắt buộc dùng ngay.
- Không tự cho phép tự đăng ký tài khoản mới qua giao diện web.
- Không tự đổi số vai trò (role) ngoài `giam_doc` và `ke_toan` trừ khi được yêu cầu.

## 7. Tiêu chí hoàn thành
- Đăng nhập đúng → vào được `/dashboard` hoặc `/reports` theo đúng role; sai role bị chặn 403.
- Sai mật khẩu 5 lần → khóa tài khoản, có cảnh báo Telegram; sau 15 phút hoặc đổi mật khẩu thì mở lại được.
- Sai mật khẩu không tiết lộ username có tồn tại hay không (test: thử username không tồn tại và username tồn tại nhưng sai mật khẩu phải trả về cùng một thông báo).
- Session hết hạn đúng theo mục 4 (test bằng cách giả lập thời gian).
- Test CSRF: request thiếu token bị từ chối.
- Đăng xuất xóa session, truy cập lại `/dashboard` bị redirect về `/login`.
