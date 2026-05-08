"""
SUPS - Video/Audio Transcription App
=====================================

A simple Tkinter desktop app that turns the speech inside any video/audio
file into a ``.txt`` (and ``.srt``) file. Runs entirely offline using
``faster-whisper``.

Just run ``python app.py`` (or use the ``run.sh`` / ``run.bat`` launcher) and
click "Bắt đầu" to transcribe.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from tkinter import (
    Tk,
    StringVar,
    BooleanVar,
    DoubleVar,
    filedialog,
    messagebox,
    ttk,
    scrolledtext,
)
from typing import Optional

from transcriber import (
    LANGUAGE_CHOICES,
    MODEL_SIZES,
    SUPPORTED_EXTENSIONS,
    Transcriber,
    TranscriptionResult,
    segments_to_plain_text,
    segments_to_srt,
)


APP_TITLE = "SUPS - Video → Text (Multi-language transcription)"
DEFAULT_MODEL = "small"


class TranscribeApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x620")
        self.root.minsize(720, 540)

        self.input_path = StringVar()
        self.output_path = StringVar()
        self.language_label = StringVar(value=next(iter(LANGUAGE_CHOICES.keys())))
        self.model_size = StringVar(value=DEFAULT_MODEL)
        self.include_timestamps = BooleanVar(value=False)
        self.also_save_srt = BooleanVar(value=True)
        self.progress_value = DoubleVar(value=0.0)
        self.status_text = StringVar(value="Sẵn sàng.")

        self._worker: Optional[threading.Thread] = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._result: Optional[TranscriptionResult] = None
        self._transcriber: Optional[Transcriber] = None

        self._build_ui()
        self.root.after(100, self._drain_log_queue)

    # ----- UI -----
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        # Row 1: input file
        row1 = ttk.LabelFrame(outer, text="1. Chọn video/audio", padding=8)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Entry(row1, textvariable=self.input_path).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ttk.Button(row1, text="Chọn file...", command=self._pick_input).pack(side="left")

        # Row 2: options
        row2 = ttk.LabelFrame(outer, text="2. Tùy chọn", padding=8)
        row2.pack(fill="x", pady=(0, 8))

        ttk.Label(row2, text="Ngôn ngữ:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        lang_combo = ttk.Combobox(
            row2,
            textvariable=self.language_label,
            values=list(LANGUAGE_CHOICES.keys()),
            state="readonly",
            width=32,
        )
        lang_combo.grid(row=0, column=1, sticky="w", padx=(0, 18))

        ttk.Label(row2, text="Model:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Combobox(
            row2,
            textvariable=self.model_size,
            values=MODEL_SIZES,
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="w")

        ttk.Checkbutton(
            row2,
            text="Kèm timestamp trong .TXT",
            variable=self.include_timestamps,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            row2,
            text="Lưu kèm phụ đề .SRT",
            variable=self.also_save_srt,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        # Row 3: output file
        row3 = ttk.LabelFrame(outer, text="3. File .TXT đầu ra", padding=8)
        row3.pack(fill="x", pady=(0, 8))
        ttk.Entry(row3, textvariable=self.output_path).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ttk.Button(row3, text="Chọn nơi lưu...", command=self._pick_output).pack(side="left")

        # Row 4: action
        row4 = ttk.Frame(outer)
        row4.pack(fill="x", pady=(0, 8))
        self.start_btn = ttk.Button(row4, text="▶ Bắt đầu", command=self._start)
        self.start_btn.pack(side="left")
        ttk.Button(row4, text="Mở thư mục đầu ra", command=self._open_output_dir).pack(
            side="left", padx=8
        )
        ttk.Label(row4, textvariable=self.status_text, foreground="#1769aa").pack(
            side="left", padx=8
        )

        # Progress bar
        self.progress_bar = ttk.Progressbar(
            outer,
            variable=self.progress_value,
            maximum=1.0,
            mode="determinate",
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))

        # Log area
        log_frame = ttk.LabelFrame(outer, text="Nhật ký", padding=4)
        log_frame.pack(fill="both", expand=True)
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=12, wrap="word")
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.configure(state="disabled")

    # ----- File pickers -----
    def _pick_input(self) -> None:
        ext_filter = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        path = filedialog.askopenfilename(
            title="Chọn video hoặc audio",
            filetypes=[
                ("Video / Audio", ext_filter),
                ("Tất cả file", "*.*"),
            ],
        )
        if not path:
            return
        self.input_path.set(path)
        if not self.output_path.get():
            self.output_path.set(str(Path(path).with_suffix(".txt")))

    def _pick_output(self) -> None:
        initial = self.output_path.get() or "transcript.txt"
        path = filedialog.asksaveasfilename(
            title="Lưu file .TXT",
            defaultextension=".txt",
            initialfile=Path(initial).name,
            initialdir=str(Path(initial).parent) if initial else None,
            filetypes=[("Text", "*.txt"), ("Tất cả file", "*.*")],
        )
        if path:
            self.output_path.set(path)

    def _open_output_dir(self) -> None:
        out = self.output_path.get()
        if not out:
            messagebox.showinfo(APP_TITLE, "Chưa có thư mục đầu ra.")
            return
        folder = str(Path(out).parent)
        if not os.path.isdir(folder):
            messagebox.showinfo(APP_TITLE, f"Không tìm thấy thư mục: {folder}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", folder])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Không mở được thư mục: {exc}")

    # ----- Logging -----
    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                message = self._log_queue.get_nowait()
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", message + "\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    # ----- Worker -----
    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Đang xử lý, vui lòng đợi...")
            return

        media_path = self.input_path.get().strip()
        if not media_path or not os.path.isfile(media_path):
            messagebox.showerror(APP_TITLE, "Vui lòng chọn một file video/audio hợp lệ.")
            return

        out_path = self.output_path.get().strip() or str(Path(media_path).with_suffix(".txt"))
        self.output_path.set(out_path)

        language_code = LANGUAGE_CHOICES.get(self.language_label.get())
        model_size = self.model_size.get() or DEFAULT_MODEL

        self.progress_value.set(0.0)
        self.status_text.set("Đang xử lý...")
        self.start_btn.configure(state="disabled")
        self._worker = threading.Thread(
            target=self._run_transcription,
            args=(media_path, out_path, language_code, model_size),
            daemon=True,
        )
        self._worker.start()

    def _run_transcription(
        self,
        media_path: str,
        out_path: str,
        language_code: Optional[str],
        model_size: str,
    ) -> None:
        try:
            if self._transcriber is None or self._transcriber.model_size != model_size:
                self._transcriber = Transcriber(model_size=model_size)

            def progress_cb(p: float) -> None:
                self.root.after(0, self.progress_value.set, max(0.0, min(1.0, p)))

            result = self._transcriber.transcribe(
                media_path=media_path,
                language=language_code,
                log=self._log,
                progress=progress_cb,
            )
            self._result = result

            text_payload = segments_to_plain_text(
                result.segments, with_timestamps=self.include_timestamps.get()
            )
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text_payload)
            self._log(f"[ok] Đã lưu: {out_path}")

            if self.also_save_srt.get():
                srt_path = str(Path(out_path).with_suffix(".srt"))
                with open(srt_path, "w", encoding="utf-8") as fh:
                    fh.write(segments_to_srt(result.segments))
                self._log(f"[ok] Đã lưu: {srt_path}")

            self.root.after(0, self._on_finished, True, None)
        except Exception as exc:
            tb = traceback.format_exc()
            self._log(f"[lỗi] {exc}\n{tb}")
            self.root.after(0, self._on_finished, False, str(exc))

    def _on_finished(self, ok: bool, error: Optional[str]) -> None:
        self.start_btn.configure(state="normal")
        if ok:
            self.progress_value.set(1.0)
            self.status_text.set("Hoàn tất.")
            messagebox.showinfo(APP_TITLE, f"Đã xuất file:\n{self.output_path.get()}")
        else:
            self.status_text.set("Có lỗi xảy ra.")
            messagebox.showerror(APP_TITLE, f"Có lỗi xảy ra:\n{error}")


def main() -> None:
    root = Tk()
    TranscribeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
