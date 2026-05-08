# SUPS — Video → Text (đa ngôn ngữ)

Ứng dụng desktop đơn giản giúp bạn **chuyển lời thoại trong video/audio thành file `.TXT`** (và `.SRT` phụ đề).
Hỗ trợ tiếng **Việt, Anh, Trung, Nhật, Hàn, Pháp, Đức, Tây Ban Nha, Bồ Đào Nha, Nga, Thái, Indonesia, Hindi, Ả Rập, Ý** cùng chế độ tự nhận diện.

> Engine: [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) chạy hoàn toàn **offline** trên máy của bạn.
> ffmpeg đã được tích hợp sẵn qua `imageio-ffmpeg` — **không cần cài thêm** ffmpeg riêng.

---

## 1. Cách chạy nhanh nhất (1 click)

| Hệ điều hành | Bước duy nhất |
|---|---|
| **Windows** | Cài [Python 3.9+](https://www.python.org/downloads/) (nếu chưa có), rồi double-click `run.bat` |
| **macOS / Linux** | Cài Python 3.9+, mở Terminal và chạy `./run.sh` (lần đầu chạy `chmod +x run.sh`) |

Lần đầu tiên script sẽ tự tạo `.venv` và cài thư viện. Những lần sau bấm là chạy luôn.

> Lần transcribe đầu tiên Whisper sẽ tải model về (~150 MB cho `small`, ~3 GB cho `large-v3`). Cần internet **chỉ lần đầu**.

---

## 2. Sử dụng trong app

1. Bấm **"Chọn file..."** và chọn video/audio (`.mp4`, `.mkv`, `.mov`, `.mp3`, `.wav`, ...).
2. Chọn **ngôn ngữ** (mặc định: Auto detect) và **model**:
   - `tiny` / `base`: nhanh, ít chính xác
   - `small` (mặc định): cân bằng tốt
   - `medium` / `large-v3`: chính xác nhất nhưng chậm và tốn RAM
3. (Tuỳ chọn) Tick **"Kèm timestamp"** hoặc **"Lưu kèm .SRT"**.
4. Bấm **"▶ Bắt đầu"**. App sẽ:
   - tách audio bằng ffmpeg đi kèm,
   - dùng Whisper để nhận dạng,
   - ghi kết quả ra file `.txt` (và `.srt` nếu chọn).

App hỗ trợ video **dài hay ngắn** đều được — tự bỏ phần im lặng (VAD) và xử lý theo từng segment.

---

## 3. Chạy bằng dòng lệnh (tuỳ chọn)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

---

## 4. Yêu cầu hệ thống

- Python 3.9 trở lên
- 4 GB RAM trở lên cho model `small`
- ~3 GB ổ trống cho model `large-v3`
- (Tuỳ chọn) GPU NVIDIA + CUDA để chạy nhanh hơn — chỉnh `device="cuda"` trong `transcriber.py`

---

## 5. Cấu trúc thư mục

```
sups/
├── app.py               # GUI Tkinter
├── transcriber.py       # Logic Whisper + ffmpeg
├── requirements.txt     # faster-whisper, imageio-ffmpeg
├── run.sh               # Launcher macOS/Linux
├── run.bat              # Launcher Windows
└── README.md
```

---

## 6. Giấy phép

Code trong repo này phát hành theo MIT. Whisper model và faster-whisper giữ giấy phép gốc của tác giả.
