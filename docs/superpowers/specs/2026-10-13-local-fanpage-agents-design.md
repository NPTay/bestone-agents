# Thiết kế: AI Agent quản lý Fanpage Bestone chạy trên máy tính

Ngày: 13/10/2026. Người quyết định: Giám đốc C.G. Engineering Việt Nam (người dùng duy nhất).
Bản này THAY THẾ hướng cũ (VPS 24/7, Docker, Postgres, trang đăng nhập, phân quyền). Những gì của hướng cũ còn dùng lại được ghi ở mục 8.

## 1. Mục đích và lý do

Fanpage Bestone cần đều đặn 2 bài/ngày và trả lời tin nhắn khách hỏi về sản phẩm, nhưng công ty không thêm người. Giám đốc muốn một chương trình chạy ngay trên máy tính văn phòng, không phải thuê VPS, không phải đăng nhập, và mọi thứ đi ra ngoài (bài đăng, câu trả lời khách) đều được Giám đốc bấm duyệt trên Telegram trước, để vừa tự động vừa không có rủi ro đăng sai.

Thành công nghĩa là: mỗi ngày Giám đốc chỉ cần mở Telegram trên điện thoại, đọc bản nháp, bấm duyệt hoặc gõ góp ý; bài lên đúng giờ, câu trả lời khách đúng tài liệu, không có lỗi thông tin kỹ thuật.

## 2. Mục tiêu

1. **Bài sáng (đăng 09:00):** tìm tin trên mạng về dự án xây dựng/hạ tầng và giải pháp chống thấm, viết thành bài theo góc nhìn kỹ thuật Bestone, kèm ảnh minh họa lấy từ kho ảnh miễn phí hoặc do Gemini tạo (tùy bài).
2. **Bài chiều (đăng 16:30):** viết từ tài liệu trong thư mục `Tai Lieu` (hiện có `Tai Lieu/Catalogue/261012_Bestone Catalogue_VN.pdf`) và kiến thức sản phẩm, kèm ảnh chọn từ thư mục `Picture` (169 file, chia thư mục theo công trình).
3. **Duyệt qua Telegram:** mỗi bài nháp gửi Telegram cho Giám đốc với nút "Đăng" / "Không đăng"; Giám đốc có thể gõ góp ý tự do (ví dụ "viết ngắn lại") → AI sửa và gửi bản mới, lặp đến khi duyệt hoặc bỏ.
4. **Bình luận tự động sau khi đăng:** ngay sau khi bài lên, chương trình bình luận dưới bài một đoạn cố định giới thiệu "Bestone - phụ gia cho bê tông tự chống thấm" kèm hotline 0904834577 và web https://cgengvn.com.
5. **Trả lời tin nhắn Messenger:** AI soạn câu trả lời cho câu hỏi về sản phẩm dựa trên tài liệu, gửi Telegram để Giám đốc duyệt (cùng cơ chế nút + góp ý như bài đăng), duyệt xong mới gửi khách.
6. **Trang "Hôm nay" trên máy tính (chỉ xem):** một trang mở trong trình duyệt hiện lịch đăng hôm nay, trạng thái từng bài (đang soạn / chờ duyệt / đã đăng / bị bỏ / lỗi), ảnh và nguồn tin, danh sách tin nhắn hôm nay và trạng thái (chờ duyệt / đã trả lời / chuyển Giám đốc). Mọi thao tác làm trên Telegram.

## 3. Không làm (lần này)

- Chấm điểm khách tiềm năng (để sau).
- Trả lời bình luận của khách dưới bài (Giám đốc chưa yêu cầu).
- Đăng nhập, nhiều người dùng, phân quyền, vai trò Kế toán.
- Chạy trên VPS / Docker / Postgres / tên miền / HTTPS.
- Duyệt hay sửa bài trên trang máy tính (hướng B đã bị loại; trang chỉ để xem).
- Lịch 7 ngày, báo cáo tuần, số liệu insights, quảng cáo trả phí, Zalo/LinkedIn.

## 4. Điều tuyệt đối tránh (thất bại dù chạy được)

- Đăng bài hoặc gửi tin cho khách khi Giám đốc chưa bấm duyệt (ngoại lệ duy nhất: bình luận cố định ở mục 2.4).
- Nêu số liệu, chứng nhận, tên dự án, tuổi thọ, bảo hành, giá không có trong kho tri thức; báo giá hoặc cam kết hiệu quả.
- Đăng ảnh có bản quyền (ảnh lấy từ báo/web). Ảnh AI giả làm công trình thật hoặc kết quả thí nghiệm thật.
- Đăng trùng bài, bình luận trùng, trả lời một tin nhắn hai lần.
- Làm Fanpage bị Meta hạn chế (scrape Facebook, spam, vượt giới hạn).
- Lộ khóa API / token ra trang web hoặc log.

## 5. Ràng buộc

- **Máy chạy 08:00–20:00** (máy văn phòng Windows 11 của Giám đốc). Ngoài giờ đó chương trình không chạy. Chương trình phải tự khởi động khi Windows bật, không cần ai thao tác, và chịu được việc máy tắt/bật giữa chừng (không mất trạng thái, không làm lại việc đã xong).
- **Không có địa chỉ công khai** → không dùng webhook Meta. Tin nhắn Messenger được lấy bằng cách hỏi định kỳ qua Graph API (khoảng 2–3 phút/lần); Telegram nhận nút bấm và góp ý bằng long-polling (`getUpdates`).
- **Cửa sổ 24 giờ của Messenger:** chỉ trả lời được trong 24 giờ kể từ tin cuối của khách. Tin quá hạn → không gửi, chỉ báo Giám đốc trên Telegram để gọi điện.
- **Chỉ dùng API chính thức** của Meta, Telegram, Anthropic, Google (Gemini), kho ảnh miễn phí. Không scrape Facebook.
- **Bí mật** (token Page, khóa Claude, khóa Gemini, khóa kho ảnh, token bot Telegram) nằm trong file `.env` cục bộ, không commit, không đưa vào trang web, không ghi log.
- **Ngôn ngữ:** bài đăng, câu trả lời, giao diện, tin Telegram bằng tiếng Việt; mã nguồn, tên biến, comment bằng tiếng Anh.
- **Người vận hành không chuyên IT:** cài đặt bằng vài lệnh copy-paste hoặc một file chạy; có hướng dẫn tiếng Việt từng bước để lấy token Meta và tạo bot Telegram.

## 6. Những gì Giám đốc đã quyết

### 6.1 Lịch một ngày
| Giờ | Việc |
|---|---|
| ~08:00 (khi máy bật) | Tìm tin + soạn bài sáng + lấy/tạo ảnh → gửi Telegram (mục tiêu trước ~08:30) |
| 09:00 | Nếu đã duyệt: đăng bài sáng → bình luận giới thiệu |
| ~15:00 | Soạn bài chiều từ `Tai Lieu` + ảnh `Picture` → gửi Telegram |
| 16:30 | Nếu đã duyệt: đăng bài chiều → bình luận giới thiệu |
| 08:00–20:00 | Kiểm tra tin nhắn mới mỗi ~2–3 phút → soạn trả lời → Telegram chờ duyệt |

### 6.2 Quy tắc duyệt
- Bài và câu trả lời tin nhắn: chỉ đi ra khi Giám đốc bấm "Đăng"/"Gửi" trên Telegram.
- Duyệt trước giờ đăng → đăng đúng giờ. Duyệt sau giờ đăng → đăng ngay lúc bấm duyệt.
- Đến 20:00 bài nào chưa duyệt thì bỏ, không dời sang hôm sau.
- Góp ý bằng chữ → AI sửa → gửi bản mới (không giới hạn số vòng do Giám đốc quyết định khi nào dừng).
- Câu hỏi nhạy cảm (giá, báo giá, bảo hành, cam kết hiệu quả, chứng nhận/TCVN, hợp đồng, khiếu nại, dự án cụ thể sắp thi công, điều không có trong tài liệu): AI KHÔNG soạn câu trả lời nội dung; chỉ báo Giám đốc trên Telegram kèm nội dung câu hỏi + tên khách. Theo quy tắc G6 có sẵn trong `knowledge/guardrails_compliance.md`.
- *(Claude quyết)* Mỗi tin nhắn trên Telegram có thêm nút "Tôi tự trả lời": Giám đốc gõ nội dung, chương trình gửi nguyên văn cho khách, không qua AI và không qua guardrail. Dùng được cả cho câu hỏi nhạy cảm đã chuyển Giám đốc. Hội thoại đã chuyển Giám đốc thì AI không soạn tiếp cho hội thoại đó; tin mới của khách trong hội thoại ấy chỉ được báo lên Telegram, cho đến khi Giám đốc bấm "Cho AI tiếp tục".
- *(Claude quyết)* Duyệt/trả lời tin nhắn sau 20:00: lần khởi động sáng hôm sau chương trình xử lý các nút bấm còn tồn trên Telegram; gửi nếu cửa sổ 24 giờ của khách còn mở, quá hạn thì báo Giám đốc gọi điện. (Bài đăng chưa duyệt trước 20:00 vẫn bị bỏ như trên.)
- *(Claude quyết)* Chỉ tin nhắn có câu hỏi/yêu cầu thật mới được soạn trả lời. Chào hỏi suông, cảm ơn, sticker, quảng cáo/spam, xin việc: không soạn, không làm phiền Telegram, nhưng vẫn hiện trên trang "Hôm nay" với trạng thái "bỏ qua".

### 6.3 Ảnh
- Bài sáng: ảnh từ kho ảnh miễn phí có giấy phép dùng thương mại (ví dụ Pexels/Unsplash) hoặc ảnh minh họa do Gemini tạo, AI chọn tùy bài. Không dùng ảnh từ bài báo. Ảnh Gemini chỉ là minh họa chung, không được giả làm công trình thật hay kết quả thí nghiệm.
- Bài chiều: ảnh từ thư mục `Picture`.
- **Giám đốc quyết: bài chiều ĐƯỢC nêu tên công trình** trong `Picture` (Tòa nhà Kyobo / Kyobo Insurance B1–B4, Convention Center Gyeongju, Korea Research Institute of Decommissioning, Warehouse tầng hầm 80m, Hội thảo SACA 9-3). Điều kiện: mỗi công trình phải có mục trong `knowledge/bestone_knowledge_base.md` trước (hạng mục, năm, thông tin Giám đốc cung cấp). Builder tạo mẫu điền sẵn để Giám đốc bổ sung; công trình chưa có thông tin thì bài chiều dùng ảnh của nó nhưng không nêu tên và không mô tả chi tiết công trình.
- *(Claude quyết)* Mặc định mọi ảnh trong `Picture` được phép đăng; có một danh sách loại trừ (thư mục/file) trong cấu hình để Giám đốc gạt bớt. Video `.mp4` bỏ qua ở bản đầu.

### 6.5 Catalogue PDF
*(Claude quyết)* Khi bắt đầu xây, trích các thông tin trong catalogue mà kho tri thức chưa có, trình Giám đốc duyệt một lần; phần được duyệt mới đưa vào `knowledge/bestone_knowledge_base.md`. Guardrail vẫn chỉ đối chiếu với kho tri thức (một nguồn sự thật). Catalogue mới thêm vào `Tai Lieu` sau này đi theo cùng quy trình.

### 6.6 Thứ tự làm (Giám đốc quyết)
Chưa có Meta App. **Làm phần đăng bài trước**:
- **Đợt 1:** bài sáng + bài chiều, ảnh, duyệt Telegram (nút + góp ý), đăng đúng giờ, bình luận giới thiệu, trang "Hôm nay" (khối tin nhắn để trống/ẩn), tự khởi động cùng Windows, hướng dẫn tạo Meta App và lấy Page Access Token. Đăng bài lên Page do chính Giám đốc quản trị chạy được khi App còn ở chế độ Development, không cần App Review (builder kiểm chứng lại với tài liệu Meta hiện hành).
- **Đợt 2:** trả lời tin nhắn Messenger (mục 2.5 và các quy tắc ở 6.2). Cần App Review cho `pages_messaging`: một trang "Chính sách quyền riêng tư" công khai (builder đề xuất cách host tĩnh miễn phí), video demo, có thể cần xác minh doanh nghiệp. Đợt 1 nên chuẩn bị sẵn hồ sơ này để nộp sớm vì Meta duyệt mất vài tuần.

### 6.4 Trang trên máy tính
Hướng A: một trang "Hôm nay", chỉ xem, không đăng nhập. Bản phác đã duyệt: thanh trên cùng (tên, ngày, trạng thái "Đang chạy"), khối "Lịch hôm nay" mỗi bài một thẻ (giờ, trạng thái, tiêu đề, ảnh thu nhỏ, nguồn tin hoặc thư mục ảnh, dấu đã gắn bình luận), khối "Tin nhắn hôm nay" (tên khách, giờ, câu hỏi tóm tắt, trạng thái).

## 7. Lựa chọn kỹ thuật (do Claude quyết, Giám đốc đã nghe và không phản đối)

- Python 3.12, như dự án cũ.
- Lưu trữ: SQLite một file trong thư mục dự án (không Postgres, không Docker).
- AI viết bài, sửa bài, soạn trả lời, kiểm tra guardrail: Claude (Anthropic API), như dự án cũ.
- Tạo ảnh minh họa: Gemini (Google API).
- Tìm tin: web search của Claude và/hoặc RSS báo xây dựng Việt Nam (builder chọn cách cụ thể).
- Facebook: Graph API chính thức (đăng ảnh + nội dung, bình luận, đọc hội thoại, gửi tin nhắn).
- Trang "Hôm nay": web server cục bộ chỉ nghe `127.0.0.1`, tự mở trình duyệt khi khởi động.

## 8. Dùng lại từ dự án cũ

Nằm trong lịch sử git (commit `a6af3e9`, nhánh `phase1-content-pipeline`), hiện bị xóa khỏi ổ đĩa nhưng phục hồi được:
- `knowledge/bestone_knowledge_base.md` — nguồn sự thật duy nhất về sản phẩm. Vẫn là quy tắc bất biến: mọi số liệu/tên/chứng nhận chỉ lấy từ đây (catalogue PDF chỉ vào được qua quy trình ở mục 6.5).
- `knowledge/brand_voice.md`, `knowledge/content_pillars.md`, `knowledge/guardrails_compliance.md`.
- `app/guardrails/rules.py`, `app/guardrails/judge.py` (kiểm tra cấm từ/số liệu bằng code + LLM judge) và test của chúng.
- `app/llm/client.py` (gọi Claude có structured output, web search, ghi chi phí), `app/integrations/notify.py` (Telegram), `app/knowledge/ingest.py`.
- Prompt agent trong `agents/a1_research.md`, `agents/a2_content.md`, `agents/a4_customer_care.md`, `agents/guardrail_judge.md` — cần chỉnh cho lịch 2 bài/ngày và luồng duyệt Telegram.
- `docs/05_META_INTEGRATION.md` cho quyền và quy tắc Meta (bỏ phần webhook).

Bỏ: toàn bộ `app/auth`, `app/cli/create_admin|reset_password`, `deploy/`, Docker, Caddy, backup S3, `docs/06`, `docs/08`. `CLAUDE.md` và các `docs/0x` phải được cập nhật theo hướng mới.

## 9. Để builder quyết

- Cấu trúc thư mục, tên module, schema bảng SQLite.
- Cách tự khởi động cùng Windows (Task Scheduler, shortcut Startup, …) và cách cài đặt đơn giản nhất cho người không chuyên.
- Cách đọc catalogue PDF và trộn với kho tri thức; cách chọn ảnh trong `Picture` để ít lặp.
- Nguồn tin cụ thể và cách chấm điểm tin cho bài sáng.
- Prompt cụ thể, định dạng tin Telegram, nút bấm.
- Giới hạn chi phí AI/ngày và cách báo lỗi (ví dụ token Meta hết hạn → báo Telegram).
