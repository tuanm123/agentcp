# 🚀 AgentCP – Hệ Thống Sinh Testcase & Đề Bài Tự Động Cho Lập Trình Thi Đấu

**AgentCP** là công cụ tự động hóa hoàn toàn quy trình biên soạn bài tập Competitive Programming (CP): từ trích xuất đề bài, viết lời giải C++ chuẩn, lập trình bộ sinh test thông minh, tạo dữ liệu testcase (Input/Output) đến đóng gói file `.zip` sẵn sàng nộp lên các hệ thống chấm điểm trực tuyến (Online Judge như Themis, DMOJ, VNOJ, Codeforces, PTIT, v.v.).

---

## 🌟 Tính Năng Nổi Bật

- 🤖 **Đa mô hình AI hàng đầu:**
  - **Google Gemini:** `gemini-3.8-flash` (mặc định siêu nhanh), `gemini-3.1-pro-preview`, `gemini-2.0-flash`.
  - **Anthropic Claude:** `claude-3-5-sonnet-20241022` (Claude 3.5 Sonnet v2), `claude-3-7-sonnet-20250219`.
  - **OpenAI:** `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`.
- 📸 **Multimodal Vision (Xử lý ảnh đề bài):**
  - Dán ảnh trực tiếp từ clipboard bằng phím tắt **`Ctrl + V`** hoặc **`Cmd + V`**.
  - Kéo thả hoặc tải lên nhiều ảnh (hỗ trợ đề bài dài nhiều trang).
  - Tự động nén và co tỷ lệ thông minh về **`≤ 1600px`** cả ở trình duyệt lẫn máy chủ, tối ưu tốc độ và tránh lỗi tràn token của AI.
- ⚡ **Thuật toán & Thẩm định tự động:**
  - AI tự động viết thuật toán C++17 tối ưu và đọc input/xuất output chuẩn.
  - Tự động kiểm tra tính hợp lệ của file `.out`, ngăn ngừa trường hợp file output bị rỗng.
- 📦 **Đóng gói chuẩn Online Judge:**
  - Tự động sinh file nén `.zip` với cấu trúc thư mục test chuẩn: `test01/`, `test02/`,... chứa từng cặp file `<tên_bài>.inp` và `<tên_bài>.out`.
- 🌐 **Giao diện Web hiện đại:**
  - Giao diện Dark mode tối giản, trực quan, hỗ trợ xem trước kết quả và **tải trực tiếp file `.zip` bằng 1 cú click**.
  - Kết nối tên miền riêng qua **Cloudflare Tunnel** hoặc **ngrok**.

---

## 🛠️ Cài Đặt & Khởi Động

### 1. Yêu cầu hệ thống
- **Hệ điều hành:** macOS / Linux / Windows.
- **Python:** Phiên bản `>= 3.9`.
- **Trình biên dịch C++:** `g++` hoặc `clang++` (trên Mac có sẵn qua Xcode Command Line Tools).

### 2. Cài đặt thư viện cần thiết
Mở Terminal tại thư mục dự án và chạy:
```bash
pip3 install -r requirements.txt
```
*(Nếu cài lẻ: `pip3 install fastapi "uvicorn[standard]" pillow requests google-generativeai openai`)*

### 3. Khởi động Web Server
Chạy lệnh sau trong Terminal:
```bash
python3 -m uvicorn backend:app --host 0.0.0.0 --port 8000
```

Truy cập ngay trên trình duyệt:
👉 **Local:** `http://localhost:8000`  
👉 **Tên miền riêng (nếu đã cài Cloudflare Tunnel):** `http://cp.agentcp.top`

---

## 📖 Hướng Dẫn Sử Dụng Chi Tiết

### Bước 1: Chọn Nhà Cung Cấp & Model AI
- **Google Gemini:** Dùng model `gemini-3.8-flash` (nhanh, miễn phí). Lấy API key tại [Google AI Studio](https://aistudio.google.com/app/apikey).
- **Anthropic Claude:** Dùng model `claude-3-5-sonnet-20241022` (thông minh nhất cho bài toán CP khó). Lấy API key tại [Anthropic Console](https://console.anthropic.com/).
- **OpenAI:** Dùng model `gpt-4o`. Lấy API key tại [OpenAI Platform](https://platform.openai.com/).

### Bước 2: Thiết lập thông tin bài tập
1. **Tên bài tập (bắt buộc):** Nhập mã bài hoặc tên bài ngắn gọn (ví dụ: `watermelon`, `sum_array`). Tên này sẽ dùng để đặt tên file `.inp`, `.out` và file `.zip`.
2. **Số test:** Chọn số lượng test case muốn sinh (mặc định: `20`, tối đa `100`).

### Bước 3: Cung cấp đề bài (Chọn 1 trong 2 cách hoặc kết hợp)
- **Cách 1 – Dán ảnh đề bài (Khuyên dùng):**
  - Chụp ảnh màn hình bài tập bất kỳ.
  - Bấm vào trang web và nhấn **`Cmd + V`** (hoặc `Ctrl + V`).
  - Ảnh sẽ hiện ngay lập tức trong danh sách xem trước kèm thông số độ phân giải đã được nén `≤ 1600px`.
- **Cách 2 – Nhập văn bản/Markdown:**
  - Dán nội dung đề bài dạng text vào ô *Đề bài (Markdown)*.

### Bước 4: Code C++ mẫu (Tùy chọn)
- Nếu bạn **đã có sẵn code giải bài**, hãy dán vào ô *Code C++ mẫu*. Hệ thống sẽ dùng code này để sinh output.
- Nếu bạn **chưa có code giải**, hãy để trống ô này. AI sẽ tự động phân tích đề bài và tự lập trình mã nguồn C++ giải tối ưu nhất!

### Bước 5: Bấm 🚀 Sinh test
- Bấm nút **🚀 Sinh test** và chờ hệ thống làm việc:
  1. Phân tích đề bài và trích xuất subtask/ràng buộc.
  2. Viết thuật toán giải C++ và kiểm tra biên dịch (`g++`).
  3. Lập trình script Python sinh dữ liệu đa dạng (test biên, test ngẫu nhiên, test cực đại).
  4. Chạy sinh toàn bộ testcase và đối soát output.
  5. Đóng gói bộ test thành file `.zip`.

---

## 📁 Kết Quả Đầu Ra Nằm Ở Đâu?

Sau khi hệ thống hoàn tất, bạn có thể nhận kết quả bằng 2 cách:

1. **Tải ngay trên Web:**
   - Bấm vào nút màu xanh: **`📥 Tải file ZIP bộ test (<tên_bài>.zip)`** xuất hiện ở cuối trang.
2. **Thư mục trên máy tính:**
   - Toàn bộ dữ liệu nằm tại:
     ```text
     agentCP-main/generated_problems/<tên_bài_tập>/
     ```
   - Cấu trúc thư mục gồm có:
     - 📦 `<tên_bài>.zip`: Gói nén chứa toàn bộ các testcase chuẩn.
     - 💻 `solution.cpp`: Mã nguồn C++17 giải bài toán.
     - 🐍 `generator.py`: Script Python sinh test tự động.
     - 📝 `statement.md`: Đề bài hoàn chỉnh chuẩn định dạng Markdown.
     - 📁 `test01/`, `test02/`,...: Từng thư mục test case chứa file `.inp` và `.out`.

---

## 🌐 Xuất Bản Ra Internet (Truy cập từ xa)

### Cách 1: Sử dụng Cloudflare Tunnel (Miễn phí vĩnh viễn, gắn tên miền riêng)
1. Cài đặt `cloudflared`:
   ```bash
   brew install cloudflared
   ```
2. Đăng nhập và tạo Tunnel trỏ vào máy của bạn:
   - Trong Cloudflare Zero Trust: Trỏ hostname (ví dụ: `cp.agentcp.top`) về `http://localhost:8000`.
3. Chỉ cần giữ `uvicorn` chạy trên máy, bất cứ ai cũng có thể truy cập qua địa chỉ:
   ```text
   http://cp.agentcp.top
   ```

### Cách 2: Sử dụng ngrok (Nhanh chóng để test tạm thời)
1. Chạy lệnh:
   ```bash
   ngrok http 8000
   ```
2. Dùng URL ngrok dạng `https://xxxx.ngrok-free.dev` để chia sẻ cho người khác.

---

## ❓ Câu Hỏi Thường Gặp (FAQ) & Khắc Phục Lỗi

| Lỗi gặp phải | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| **Lỗi 404: Model không khả dụng** | Google vừa khai tử model cũ (`gemini-2.5-pro/flash`). | Chọn model **`gemini-3.8-flash`** (mặc định) trong danh sách thả xuống. |
| **File output (`.out`) bị rỗng** | Code C++ chưa có logic in kết quả (`cout`). | Hệ thống hiện tại đã tích hợp bộ kiểm duyệt tự động để ép AI sinh code C++ hoàn chỉnh có lệnh in `cout`. |
| **Không mở được ảnh/ảnh quá lớn** | Ảnh chụp màn hình 4K/Retina quá lớn gây nghẽn API. | Hệ thống đã tích hợp tính năng tự động resize về `≤ 1600px` giữ nguyên tỷ lệ sắc nét. |
| **Tên miền báo `NXDOMAIN`** | DNS máy tính đang cache nameserver cũ. | Vào Cài đặt trình duyệt (Edge/Chrome) → bật **Secure DNS** chọn **Cloudflare (1.1.1.1)** hoặc chờ 5-10 phút để DNS toàn cầu cập nhật. |

---

*Phát triển bởi AgentCP Team – Chúc bạn sáng tạo được nhiều bài tập chất lượng!*
