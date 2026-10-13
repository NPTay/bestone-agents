# 01 — Project Brief

Thiết kế đầy đủ và các quyết định của Giám đốc: `docs/superpowers/specs/2026-10-13-local-fanpage-agents-design.md`. File này là bản tóm tắt.

## Công ty & sản phẩm
- Công ty TNHH C.G. Engineering Việt Nam. Website: https://cgengvn.com. Hotline: 0904834577 (Giám đốc Nguyễn Phương Tây).
- Sản phẩm: Bestone, phụ gia tự chống thấm, tự phục hồi vết nứt cho kết cấu bê tông. Chi tiết: `knowledge/bestone_knowledge_base.md`.

## Vai trò của Fanpage
Bestone là sản phẩm B2B kỹ thuật, chu kỳ chốt dài. Fanpage là kênh bảo chứng uy tín, phễu kéo kỹ sư/dự toán/thu mua tới hotline hoặc inbox, và định vị chuyên gia về chống thấm bê tông kết cấu tại Việt Nam. Đối tượng: chủ đầu tư, tổng thầu, giám đốc dự án, tư vấn thiết kế, kỹ sư hiện trường, phòng dự toán, thu mua.

## Mục tiêu
Chương trình chạy trên máy tính Windows của Giám đốc, một người dùng duy nhất. Mọi thứ đi ra ngoài đều được Giám đốc duyệt trên Telegram.

**Đợt 1 (đã xây, chờ nghiệm thu với khóa thật)**
- Bài sáng (đăng 09:00): tìm tin ngành, viết theo góc nhìn kỹ thuật Bestone, ảnh Pexels hoặc minh họa Gemini.
- Bài chiều (đăng 16:30): viết từ tài liệu trong `Tai Lieu` và kho tri thức, ảnh từ `Picture`; được nêu tên công trình khi KB mục 13 đã điền đủ.
- Duyệt bằng nút "Đăng" / "Không đăng" hoặc góp ý bằng cách Reply; AI sửa và gửi bản mới.
- Bình luận giới thiệu cố định (Bestone, hotline, website) ngay sau khi đăng.
- Trang "Hôm nay" chỉ xem; tự chạy khi Windows đăng nhập.

**Đợt 2 (chưa làm)**: AI soạn câu trả lời Messenger, Giám đốc duyệt trên Telegram; câu hỏi nhạy cảm (giá, bảo hành, chứng nhận, hợp đồng) chuyển thẳng Giám đốc. Cần Meta App Review.

## Ngoài phạm vi
Chấm điểm khách tiềm năng, trả lời bình luận của khách, đăng nhập/nhiều người dùng/phân quyền, VPS/Docker/Postgres, duyệt bài trên trang web, báo cáo tuần/insights, quảng cáo trả phí, Zalo/LinkedIn, scrape Facebook, đăng vào group người khác.

## Điều tuyệt đối tránh
Đăng khi chưa duyệt; nêu số liệu/chứng nhận/tên dự án/giá/bảo hành không có trong KB; ảnh có bản quyền hoặc ảnh AI giả làm công trình thật; đăng trùng; làm Fanpage bị Meta hạn chế; lộ khóa/token.
