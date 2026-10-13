# Hướng dẫn cài đặt (dành cho Giám đốc)

Làm lần lượt từng bước. Mọi lệnh đều copy-paste vào **PowerShell** (bấm Start, gõ "PowerShell", mở lên). Trước hết chuyển vào thư mục dự án:

```powershell
cd "D:\1. Claude AI\2. Quản lý Fanpage Bestone\bestone-agents"
```

Các khóa/token (chuỗi ký tự bí mật) chỉ được dán vào file `.env`. Không gửi cho ai, không đăng lên mạng.

## 1. Cài Python 3.12
1. Vào https://www.python.org/downloads/ và tải Python 3.12.
2. Khi cài, tích ô **"Add python.exe to PATH"** rồi bấm Install.
3. Kiểm tra: `py -3.12 --version` phải hiện `Python 3.12.x`.

## 2. Cài chương trình
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```
Lệnh này tạo môi trường Python và tạo file `.env` từ `.env.example`. Chạy lại lần nữa cũng an toàn (không ghi đè `.env`).

Mở `.env` bằng Notepad (`notepad .env`) để điền dần các khóa ở các bước dưới. Mỗi dòng dạng `TEN=giá trị`, không có dấu cách hay dấu ngoặc.

## 3. Tạo bot Telegram
1. Trong Telegram, tìm **@BotFather**, gửi `/newbot`, đặt tên và tên người dùng cho bot (tên người dùng phải kết thúc bằng `bot`).
2. BotFather trả về một **token**. Dán vào `.env`: `TELEGRAM_BOT_TOKEN=<token>`.
3. Mở bot vừa tạo trong Telegram, bấm **Start** (hoặc gửi `/start`).
4. Lấy chat id:
   ```powershell
   .venv\Scripts\python -m app.cli.setup_tools telegram-chat-id
   ```
5. Dòng `Chat id: 123456789` hiện ra, dán số đó vào `.env`: `TELEGRAM_ADMIN_CHAT_ID=123456789`.

Chỉ tin nhắn từ chat id này mới được chương trình nghe theo.

## 4. Lấy khóa Anthropic (AI viết bài)
1. Vào https://console.anthropic.com, đăng nhập, nạp một ít tiền (credit).
2. Mục **API Keys** > tạo khóa mới.
3. Dán vào `.env`: `ANTHROPIC_API_KEY=<khóa>`.

## 5. Lấy khóa Unsplash (ảnh bản quyền cho bài sáng)
1. Vào https://unsplash.com/developers, đăng ký, bấm **New Application** (miễn phí).
2. Trong trang ứng dụng, chép **Access Key** (không cần Secret Key).
3. Dán vào `.env`: `UNSPLASH_ACCESS_KEY=<Access Key>`.
4. Bài dùng ảnh Unsplash sẽ ghi tên tác giả ("Ảnh: <tên> / Unsplash") như Unsplash yêu cầu.

## 6. Lấy khóa Gemini (ảnh minh họa AI cho bài sáng)
1. Vào https://aistudio.google.com/apikey, tạo khóa.
2. Dán vào `.env`: `GEMINI_API_KEY=<khóa>`.
3. **Bắt buộc bật thanh toán (Billing)** cho dự án Google của khóa này: gói miễn phí không cho tạo ảnh (lỗi "429 RESOURCE_EXHAUSTED / exceeded your current quota"). Vào https://aistudio.google.com → **Billing** → liên kết tài khoản thanh toán.
4. Mẫu tạo ảnh: `GEMINI_IMAGE_MODEL=gemini-3.1-flash-lite-image` (rẻ nhất, đủ cho ảnh minh họa). Muốn ảnh đẹp hơn thì đổi thành `gemini-3.1-flash-image`.

Unsplash và Gemini không bắt buộc, nhưng thiếu cả hai thì bài sáng sẽ không có ảnh (bài vẫn gửi Telegram kèm cảnh báo).

## 7. Tạo Meta App và lấy token Trang Facebook
Bạn cần là **quản trị viên** của Fanpage.

1. Vào https://developers.facebook.com, đăng nhập, bấm **My Apps > Create App**. Chọn loại **Business**. Đặt tên tùy ý.
2. Trong App, vào **Settings > Basic**: ghi lại **App ID** và **App Secret** (bấm Show).
3. Lấy **ID của Fanpage** (một dãy số): mở Fanpage > Giới thiệu (About) > Minh bạch Trang (Page transparency), hoặc xem trong Meta Business Suite.
4. Dán vào `.env`:
   ```
   META_APP_ID=<App ID>
   META_APP_SECRET=<App Secret>
   META_PAGE_ID=<ID Fanpage>
   ```
5. Vào https://developers.facebook.com/tools/explorer (Graph API Explorer):
   - Chọn App vừa tạo ở ô **Meta App**.
   - Ở **User or Page** chọn **Get User Access Token**.
   - Tích 3 quyền: `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`.
   - Bấm **Generate Access Token**, đăng nhập và **chọn đúng Fanpage** khi Facebook hỏi.
   - Copy token hiện ra (token ngắn hạn).
6. Đổi thành token Trang dài hạn và tự ghi vào `.env`:
   ```powershell
   .venv\Scripts\python -m app.cli.setup_tools meta-token --user-token <dán token ngắn hạn>
   ```
   Thấy dòng `Đã lưu token cho Trang: <tên Trang>` là xong. Lệnh này không in token ra màn hình.

Đăng bài lên Fanpage do chính bạn quản trị chạy được khi App còn ở chế độ Development, không cần Meta duyệt App.

## 8. Kiểm tra mọi thứ
```powershell
.venv\Scripts\python -m app.cli.setup_tools check
```
Mỗi dòng bắt đầu bằng ✅ (ổn) hoặc ❌ (lỗi, kèm lý do). Anthropic và Telegram phải ✅ (Telegram sẽ nhận một tin "Kiểm tra kết nối OK"). Unsplash, Gemini, hai thư mục ảnh/tài liệu là tùy chọn. Facebook chỉ bắt buộc khi `DRY_RUN=false`. Dòng Gemini tạo thử một ảnh rất nhỏ để biết có bị giới hạn không (tốn một khoản rất nhỏ khi đã bật Billing). Nếu báo "hết hạn mức tạo ảnh (429)": bật Billing như mục 6; khi gặp lỗi này trong lúc chạy, chương trình tự bỏ qua Gemini đến hết ngày và dùng ảnh Unsplash.

## 9. Khởi động chương trình và chạy thử vài ngày với DRY_RUN=true
Trước hết chắc rằng trong `.env` có `DRY_RUN=true` (mặc định). Chế độ này nghĩa là chương trình soạn bài, gửi Telegram, bạn duyệt, nhưng **không đăng thật lên Facebook**; chỉ ghi nhận "đã đăng" để bạn xem luồng chạy.

Đăng ký tự chạy khi Windows đăng nhập, rồi chạy ngay bây giờ:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
Dòng đầu đăng ký tự chạy (gỡ bỏ bằng `scripts\uninstall_autostart.ps1`); dòng sau chạy ngay. Chương trình chạy ngầm, không hiện cửa sổ, và tự mở trang "Hôm nay" (chỉ để xem) tại http://127.0.0.1:8765/ . Telegram sẽ báo chương trình đã chạy. Chương trình làm việc khoảng 08:00 đến 20:00, nên máy cần bật trong giờ đó.

Hãy chạy thử vài ngày để làm quen và xem chất lượng bài.

## 10. Chuyển sang đăng thật
Khi hài lòng: sửa `.env` thành `DRY_RUN=false`, lưu file, rồi khởi động lại chương trình (khởi động lại máy, hoặc chạy lại `scripts\start.ps1` sau khi tắt chương trình trong Task Manager). Chạy lại `setup_tools check` để chắc dòng Meta là ✅. Bài đầu tiên nên được bạn kiểm tra kỹ trên Fanpage.

## 11. Điền thông tin công trình (mục 13 của kho tri thức)
Bài chiều dùng ảnh trong `Picture`. Chương trình chỉ **nêu tên** một công trình khi bạn đã điền đủ thông tin.

1. Mở `knowledge\bestone_knowledge_base.md` bằng Notepad, kéo xuống **mục 13**.
2. Mỗi công trình có 5 dòng: Tên hiển thị, Quốc gia / địa điểm, Hạng mục dùng Bestone, Năm, Ghi chú được phép nêu. Thay mỗi chữ `[GĐ BỔ SUNG]` bằng thông tin thật.
3. Công trình nào còn sót dù chỉ một `[GĐ BỔ SUNG]` thì **không bao giờ được nêu tên** trong bài. Ảnh của nó vẫn có thể dùng, nhưng bài không nói đó là công trình nào. Đừng điền bừa: thông tin bạn điền sẽ được coi là sự thật và đăng lên.
4. Lưu file rồi khởi động lại chương trình để nạp thông tin mới.

## 12. Trích thông tin từ catalogue
```powershell
.venv\Scripts\python -m app.cli.catalogue
```
Lệnh đọc các PDF trong `Tai Lieu` và tạo file `knowledge\catalogue_proposals.md` gồm hai nhóm "Bổ sung mới" và "Khác với tài liệu hiện có", mỗi mục kèm số trang. Chương trình **không** dùng file này. Bạn đọc, mục nào đúng thì tự chép sang `knowledge\bestone_knowledge_base.md`. Mục có dấu "cần Giám đốc xác nhận" (giá, bảo hành, tuổi thọ) chỉ chép khi bạn chắc chắn.

## 13. Loại bớt ảnh không muốn đăng
Mặc định mọi ảnh `.jpg/.jpeg/.png` trong `Picture` đều có thể được dùng (video bị bỏ qua). Để loại một thư mục hoặc một ảnh: mở `config\picture_exclude.txt`, thêm mỗi dòng một đường dẫn tính từ thư mục `Picture` (ví dụ `MAU SAN PHAM BESTONE`). Dòng bắt đầu bằng `#` là ghi chú. Khởi động lại chương trình sau khi sửa.

Muốn đổi chủ đề tìm tin cho bài sáng: sửa `config\research_queries.txt` (mỗi dòng một cụm từ tìm kiếm).

## Dùng hằng ngày trên Telegram
- Bot gửi bản nháp kèm nút **Đăng** / **Không đăng**. Bấm nút để duyệt hoặc bỏ.
- **Góp ý**: nhấn giữ vào tin nhắn bản nháp, chọn **Trả lời (Reply)**, rồi gõ góp ý (ví dụ "viết ngắn lại"). Bot sửa và gửi bản mới kèm nút mới. Nút của bản cũ không còn tác dụng.
- Khi có **hai bài đang chờ duyệt cùng lúc**, bạn **bắt buộc phải Reply đúng tin nhắn của bài** muốn sửa. Nếu gõ chữ tự do, bot sẽ hỏi lại và không sửa bài nào.
- Giờ đăng: bài sáng 09:00, bài chiều 16:30. Duyệt trước giờ thì đăng đúng giờ; duyệt sau giờ thì đăng ở lần kiểm tra kế tiếp (trong khoảng một phút). Ngay sau khi đăng, chương trình tự bình luận dưới bài một đoạn giới thiệu cố định (Bestone, hotline, website).
- Bài **chưa duyệt đến 20:00 sẽ bị bỏ**, không dời sang hôm sau. Telegram báo rõ lý do.

## Khi máy bật muộn, tắt giữa chừng hoặc mất mạng
- Bật máy muộn (ví dụ 10:40): nếu còn trước 12:00, bài sáng được soạn ngay. Bài chiều soạn từ 15:00. Việc nào đã xong thì không làm lại.
- Mất mạng lúc khởi động hoặc AI lỗi: chương trình tự thử soạn lại **mỗi 10 phút, tối đa 3 lần**. Hết 3 lần vẫn lỗi thì báo Telegram và bỏ khung giờ đó.
- Tắt máy giữa ngày rồi bật lại: chương trình đọc lại trạng thái đã lưu, tiếp tục từ chỗ dở và không đăng trùng.
- Bài chưa được duyệt đến **20:00 thì bị bỏ**, Telegram giải thích lý do.

## Chương trình không chạy hoặc im lặng
Chương trình khởi động nhờ Task Scheduler của Windows khi bạn đăng nhập. Chức năng "tự khởi động lại" của Task Scheduler chỉ áp dụng khi **không khởi động được**, **không** cứu được trường hợp chương trình bị sập khi đang chạy.

Nếu trang "Hôm nay" không mở hoặc Telegram im lặng:
1. Chạy: `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` (nếu đang chạy rồi, bản mới tự thoát, không bị chạy trùng).
2. Xem nhật ký: `notepad data\logs\app.log`. Dòng cuối thường cho biết lỗi (nhật ký không chứa khóa hay token).
3. Chạy lại `setup_tools check` để xem khóa nào hỏng.

## Các cảnh báo trên Telegram
- **"Token Facebook hết hạn hoặc bị thu hồi…"**: token Trang tuy dài hạn nhưng vẫn có thể hết hạn hoặc bị thu hồi (ví dụ đổi mật khẩu Facebook). Làm lại **mục 7, bước 5 và 6**: tạo token ngắn hạn mới trong Graph API Explorer rồi chạy `setup_tools meta-token --user-token ...`. Sau đó khởi động lại chương trình.
- **"Bài … bị gián đoạn lúc đang đăng. Hãy mở Fanpage kiểm tra xem bài đã lên chưa — chương trình sẽ KHÔNG tự đăng lại để tránh trùng."**: chương trình bị tắt hoặc sập (mất điện, tắt máy, khởi động lại) đúng lúc đang đăng bài.
- **"Bài …: không rõ đã đăng lên Facebook hay chưa (lỗi kết nối). Hãy mở Fanpage kiểm tra — chương trình sẽ KHÔNG tự đăng lại để tránh trùng."**: lúc đăng bị lỗi kết nối mạng nên không biết Facebook đã nhận bài hay chưa.
- Với cả hai cảnh báo trên: **mở Fanpage kiểm tra trước.** Nếu bài đã lên thì thôi; chỉ khi chắc chắn chưa lên mới tự đăng tay. **Không đăng lại bằng tay khi chưa kiểm tra**, kẻo trùng bài.
- **"… chưa được duyệt trước 20:00 nên đã bỏ"**: bình thường, không cần làm gì.

## Nơi lưu dữ liệu
- Nhật ký: `data\logs\app.log` (tự xoay vòng, giữ vài file cũ).
- Dữ liệu bài: `data\bestone.db`; ảnh tải về cũng nằm trong thư mục `data`.
- Muốn sao lưu: copy cả thư mục `data` và file `.env` sang chỗ an toàn.
