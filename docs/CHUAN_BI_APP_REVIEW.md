# Chuẩn bị App Review cho Đợt 2 (trả lời Messenger)

Đợt 1 (đăng bài) không cần Meta duyệt App. Đợt 2 (AI soạn câu trả lời tin nhắn, Giám đốc duyệt trên Telegram) cần Meta cấp quyền `pages_messaging` cho **mọi khách hàng thật**, và việc duyệt thường mất vài tuần. Vì vậy nên chuẩn bị hồ sơ sớm.

## 1. Meta yêu cầu gì
- Quyền `pages_messaging` qua **App Review** (Meta có thể đổi quy trình; luôn đối chiếu tài liệu hiện hành trên developers.facebook.com).
- Có thể phải **xác minh doanh nghiệp (Business Verification)**: chuẩn bị giấy đăng ký kinh doanh của C.G. Engineering Việt Nam.
- URL **Chính sách quyền riêng tư** công khai, dán vào Meta App.
- Mô tả use case và **video demo**.
- Trong lúc chưa được duyệt (chế độ Development), chỉ quản trị viên/tester của App nhắn thử được.

## 2. Đưa chính sách quyền riêng tư lên mạng (miễn phí)
File sẵn có: `docs/chinh_sach_quyen_rieng_tu.html` (một trang độc lập, không cần gì thêm). Trước hết mở file bằng Notepad và thay các chỗ `[GĐ BỔ SUNG: …]` (ngày hiệu lực, địa chỉ công ty). Nên nhờ luật sư xem lại nội dung nếu cần.

**Cách 1: GitHub Pages**
1. Tạo tài khoản GitHub, tạo repository **công khai** mới (ví dụ `bestone-privacy`). Không dùng repository chứa mã dự án này.
2. Upload file, **đổi tên thành `index.html`**.
3. Vào Settings > Pages > chọn nhánh `main`, thư mục `/ (root)`, Save.
4. Sau ít phút có địa chỉ dạng `https://<tên-tài-khoản>.github.io/bestone-privacy/`.

**Cách 2: Google Sites**
1. Tạo site mới tại https://sites.google.com, dán nội dung chính sách vào trang.
2. Bấm Publish, chọn địa chỉ, để chế độ ai cũng xem được.

Mở địa chỉ bằng cửa sổ ẩn danh để chắc ai cũng xem được. Sau đó vào Meta App > Settings > Basic > **Privacy Policy URL**, dán địa chỉ vào và Save.

## 3. Kịch bản video demo (khoảng 2 đến 3 phút)
Meta muốn thấy quyền được dùng đúng mục đích. Gợi ý:
1. (10 giây) Giới thiệu: Fanpage Bestone của C.G. Engineering Việt Nam; chương trình hỗ trợ trả lời khách hỏi về sản phẩm.
2. (20 giây) Dùng một tài khoản Facebook thử, nhắn tin cho Fanpage một câu hỏi về sản phẩm.
3. (30 giây) Cho thấy chương trình nhận tin và gửi bản nháp trả lời tới Telegram của Giám đốc, kèm nút duyệt.
4. (20 giây) Giám đốc bấm duyệt (hoặc gõ góp ý rồi duyệt).
5. (20 giây) Quay lại Messenger: khách nhận câu trả lời.
6. (20 giây) Cho thấy câu hỏi nhạy cảm (giá, bảo hành) không được AI trả lời mà chuyển Giám đốc.
7. (10 giây) Nêu rõ: chỉ trả lời trong 24 giờ kể từ tin cuối của khách, không gửi tin hàng loạt. Mở trang chính sách quyền riêng tư.

Quay màn hình có lời thuyết minh (tiếng Anh hoặc phụ đề tiếng Anh cho người duyệt của Meta). Không để lộ token, khóa hay App Secret trong video.

## 4. Mô tả use case (gợi ý để dán vào form)
"Page admins receive customer inquiries about our concrete waterproofing admixture on Messenger. The app drafts a reply based on our product documents and sends it to the Page owner for approval. Only after approval is the reply sent, within 24 hours of the customer's last message. Sensitive questions (price, warranty) are handed to the owner."

## 5. Việc cần làm theo thứ tự
1. Điền ngày hiệu lực và địa chỉ trong trang chính sách.
2. Đưa lên mạng, dán URL vào Meta App.
3. Kiểm tra Business Verification có bị yêu cầu không.
4. Quay video demo khi Đợt 2 chạy được ở chế độ Development.
5. Nộp App Review cho `pages_messaging` (và quyền khác nếu Meta yêu cầu).
