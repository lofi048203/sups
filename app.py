"""
SUPS - Video/Audio Transcription App (modern UI)
================================================

A polished CustomTkinter desktop app that turns the speech inside any
video/audio file into a ``.txt`` (and ``.srt``) file. Runs entirely
offline using ``faster-whisper``.

Just run ``python app.py`` (or use the ``run.sh`` / ``run.bat`` launcher)
and click "Bắt đầu".
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from transcriber import (
    LANGUAGE_CHOICES,
    MODEL_SIZES,
    SUPPORTED_EXTENSIONS,
    Transcriber,
    TranscriptionResult,
    segments_to_plain_text,
    segments_to_srt,
)


APP_TITLE = "SUPS"
APP_SUBTITLE = "Video → Text · Multi-language transcription"
DEFAULT_MODEL = "small"

# Tuned color palette layered on top of CustomTkinter's defaults.
PRIMARY = ("#2563eb", "#3b82f6")  # (light, dark)
PRIMARY_HOVER = ("#1d4ed8", "#60a5fa")
DANGER = ("#dc2626", "#ef4444")
MUTED = ("#64748b", "#94a3b8")
CARD_BG = ("#ffffff", "#1f2937")
CARD_BORDER = ("#e2e8f0", "#334155")
APP_BG = ("#f1f5f9", "#0f172a")


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "00:00"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class Card(ctk.CTkFrame):
    """A bordered, rounded section with a small header label."""

    def __init__(self, master, *, title: str, step: Optional[str] = None, **kwargs):
        super().__init__(
            master,
            corner_radius=14,
            fg_color=CARD_BG,
            border_color=CARD_BORDER,
            border_width=1,
            **kwargs,
        )
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 6))
        if step:
            ctk.CTkLabel(
                header,
                text=step,
                width=26,
                height=26,
                corner_radius=13,
                fg_color=PRIMARY,
                text_color="#ffffff",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 14))


class TranscribeApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(f"{APP_TITLE} — {APP_SUBTITLE}")
        self.root.geometry("980x800")
        self.root.minsize(860, 720)
        self.root.configure(fg_color=APP_BG)

        self.input_path = ctk.StringVar()
        self.output_path = ctk.StringVar()
        self.language_label = ctk.StringVar(value=next(iter(LANGUAGE_CHOICES.keys())))
        self.model_size = ctk.StringVar(value=DEFAULT_MODEL)
        self.include_timestamps = ctk.BooleanVar(value=False)
        self.also_save_srt = ctk.BooleanVar(value=True)
        self.progress_value = ctk.DoubleVar(value=0.0)
        self.status_text = ctk.StringVar(value="● Sẵn sàng")
        self.percent_text = ctk.StringVar(value="0%")
        self.elapsed_text = ctk.StringVar(value="00:00")
        self.eta_text = ctk.StringVar(value="--:--")
        self.appearance = ctk.StringVar(value="System")

        self._worker: Optional[threading.Thread] = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._result: Optional[TranscriptionResult] = None
        self._transcriber: Optional[Transcriber] = None
        self._start_ts: float = 0.0
        self._tick_job: Optional[str] = None

        self._build_ui()
        self.root.after(100, self._drain_log_queue)

    # ----- UI -----
    def _build_ui(self) -> None:
        self._build_header()

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        body.grid_columnconfigure(0, weight=1, uniform="cards")
        body.grid_columnconfigure(1, weight=1, uniform="cards")
        body.grid_rowconfigure(2, weight=1)

        self._build_input_card(body).grid(
            row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 12)
        )
        self._build_options_card(body).grid(
            row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12)
        )
        self._build_output_card(body).grid(
            row=1, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12)
        )
        self._build_action_and_log(body).grid(
            row=2, column=0, columnspan=2, sticky="nsew"
        )

        self._build_status_bar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent", height=72)
        header.pack(fill="x", padx=24, pady=(18, 12))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="🎙️",
            font=ctk.CTkFont(size=32),
        ).pack(side="left", padx=(0, 12))

        text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        text_box.pack(side="left")
        ctk.CTkLabel(
            text_box,
            text=APP_TITLE,
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_box,
            text=APP_SUBTITLE,
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            anchor="w",
        ).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")

        ctk.CTkLabel(
            right, text="Giao diện:", font=ctk.CTkFont(size=12), text_color=MUTED
        ).pack(side="left", padx=(0, 8))
        ctk.CTkSegmentedButton(
            right,
            values=["Light", "Dark", "System"],
            variable=self.appearance,
            command=self._on_appearance_change,
            corner_radius=8,
        ).pack(side="left")

    def _build_input_card(self, master) -> ctk.CTkFrame:
        card = Card(master, title="Tệp video / audio nguồn", step="1")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkEntry(
            body,
            textvariable=self.input_path,
            placeholder_text="Chưa chọn file. Bấm 'Chọn file...' bên phải để duyệt",
            height=42,
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 10))

        ctk.CTkButton(
            body,
            text="📂 Chọn file...",
            command=self._pick_input,
            height=42,
            width=160,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            body,
            text="Hỗ trợ: "
            + ", ".join(sorted({e.lstrip(".") for e in SUPPORTED_EXTENSIONS})),
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        return card

    def _build_options_card(self, master) -> ctk.CTkFrame:
        card = Card(master, title="Tùy chọn nhận dạng", step="2")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text="Ngôn ngữ", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkOptionMenu(
            body,
            variable=self.language_label,
            values=list(LANGUAGE_CHOICES.keys()),
            height=38,
            corner_radius=10,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            fg_color=CARD_BG,
            button_color=PRIMARY,
            button_hover_color=PRIMARY_HOVER,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ctk.CTkLabel(
            body, text="Model Whisper", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, sticky="w")
        ctk.CTkSegmentedButton(
            body,
            values=MODEL_SIZES,
            variable=self.model_size,
            corner_radius=10,
            height=36,
        ).grid(row=3, column=0, sticky="ew", pady=(4, 6))
        ctk.CTkLabel(
            body,
            text="tiny / base = nhanh · small = cân bằng · medium / large-v3 = chính xác nhất",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
            wraplength=400,
            justify="left",
        ).grid(row=4, column=0, sticky="ew", pady=(0, 12))

        ctk.CTkSwitch(
            body,
            text="Kèm timestamp trong .TXT",
            variable=self.include_timestamps,
            font=ctk.CTkFont(size=12),
        ).grid(row=5, column=0, sticky="w", pady=(0, 4))

        ctk.CTkSwitch(
            body,
            text="Lưu kèm phụ đề .SRT",
            variable=self.also_save_srt,
            font=ctk.CTkFont(size=12),
        ).grid(row=6, column=0, sticky="w")

        return card

    def _build_output_card(self, master) -> ctk.CTkFrame:
        card = Card(master, title="File .TXT đầu ra", step="3")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text="Đường dẫn", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ctk.CTkEntry(
            body,
            textvariable=self.output_path,
            placeholder_text="Tự động đặt cạnh file nguồn (.txt)",
            height=38,
            font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10), padx=(0, 8))

        ctk.CTkButton(
            body,
            text="💾",
            width=40,
            height=38,
            corner_radius=10,
            command=self._pick_output,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
        ).grid(row=1, column=1, pady=(4, 10))

        ctk.CTkButton(
            body,
            text="📁 Mở thư mục đầu ra",
            command=self._open_output_dir,
            height=36,
            corner_radius=10,
            fg_color="transparent",
            border_width=1,
            border_color=CARD_BORDER,
            text_color=("#1e293b", "#e2e8f0"),
            hover_color=APP_BG,
        ).grid(row=2, column=0, columnspan=2, sticky="ew")

        return card

    def _build_action_and_log(self, master) -> ctk.CTkFrame:
        wrapper = ctk.CTkFrame(master, fg_color="transparent")

        action = ctk.CTkFrame(wrapper, fg_color="transparent")
        action.pack(fill="x")

        self.start_btn = ctk.CTkButton(
            action,
            text="▶  Bắt đầu",
            command=self._start,
            height=52,
            corner_radius=14,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.cancel_btn = ctk.CTkButton(
            action,
            text="⏹  Hủy",
            command=self._cancel,
            height=52,
            width=140,
            corner_radius=14,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            border_width=1,
            border_color=CARD_BORDER,
            text_color=DANGER,
            hover_color=APP_BG,
            state="disabled",
        )
        self.cancel_btn.pack(side="left")

        prog = ctk.CTkFrame(
            wrapper,
            fg_color=CARD_BG,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=14,
        )
        prog.pack(fill="x", pady=(12, 12))

        prog_top = ctk.CTkFrame(prog, fg_color="transparent")
        prog_top.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            prog_top,
            text="Tiến độ",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            prog_top,
            textvariable=self.percent_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=PRIMARY,
        ).pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(
            prog,
            variable=self.progress_value,
            height=10,
            corner_radius=6,
            progress_color=PRIMARY,
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 8))

        prog_bot = ctk.CTkFrame(prog, fg_color="transparent")
        prog_bot.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            prog_bot, text="Đã trôi qua:", font=ctk.CTkFont(size=11), text_color=MUTED
        ).pack(side="left")
        ctk.CTkLabel(
            prog_bot,
            textvariable=self.elapsed_text,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", padx=(4, 18))
        ctk.CTkLabel(
            prog_bot, text="ETA:", font=ctk.CTkFont(size=11), text_color=MUTED
        ).pack(side="left")
        ctk.CTkLabel(
            prog_bot,
            textvariable=self.eta_text,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", padx=(4, 0))

        log_card = Card(wrapper, title="Nhật ký xử lý")
        log_card.pack(fill="both", expand=True)
        self.log_widget = ctk.CTkTextbox(
            log_card.body,
            font=ctk.CTkFont(family="Menlo", size=12),
            corner_radius=8,
            wrap="word",
        )
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.configure(state="disabled")

        return wrapper

    def _build_status_bar(self) -> None:
        status = ctk.CTkFrame(self.root, fg_color="transparent", height=28)
        status.pack(fill="x", padx=24, pady=(0, 12))
        ctk.CTkLabel(
            status,
            textvariable=self.status_text,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            status,
            text="Powered by faster-whisper · ffmpeg bundled",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="e",
        ).pack(side="right")

    # ----- Theme -----
    def _on_appearance_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)

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
        self._set_status(f"● Đã chọn: {Path(path).name}")

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
                subprocess.Popen(["open", folder])
            else:
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

    def _set_status(self, text: str) -> None:
        self.status_text.set(text)

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
        self.progress_bar.set(0.0)
        self.percent_text.set("0%")
        self.elapsed_text.set("00:00")
        self.eta_text.set("--:--")
        self._start_ts = time.time()
        self._set_status("● Đang xử lý...")
        self.start_btn.configure(state="disabled", text="⏳  Đang xử lý...")
        self.cancel_btn.configure(state="normal")

        self._tick_job = self.root.after(500, self._tick_progress)

        self._worker = threading.Thread(
            target=self._run_transcription,
            args=(media_path, out_path, language_code, model_size),
            daemon=True,
        )
        self._worker.start()

    def _cancel(self) -> None:
        # faster-whisper doesn't expose graceful cancel; we just disable the
        # button and let the daemon thread finish in the background.
        self.cancel_btn.configure(state="disabled")
        self._set_status("● Sẽ dừng sau khi segment hiện tại kết thúc...")
        self._log("[user] Yêu cầu hủy. Sẽ dừng sau khi xử lý xong segment hiện tại.")

    def _tick_progress(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            self._tick_job = None
            return
        elapsed = time.time() - self._start_ts
        self.elapsed_text.set(_format_duration(elapsed))
        p = self.progress_bar.get()
        if p > 0.01:
            total_estimate = elapsed / p
            self.eta_text.set(_format_duration(max(0, total_estimate - elapsed)))
        self._tick_job = self.root.after(500, self._tick_progress)

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
                p = max(0.0, min(1.0, p))
                self.root.after(0, self._set_progress, p)

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

    def _set_progress(self, value: float) -> None:
        self.progress_value.set(value)
        self.progress_bar.set(value)
        self.percent_text.set(f"{int(round(value * 100))}%")

    def _on_finished(self, ok: bool, error: Optional[str]) -> None:
        if self._tick_job:
            try:
                self.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

        self.start_btn.configure(state="normal", text="▶  Bắt đầu")
        self.cancel_btn.configure(state="disabled")
        if ok:
            self._set_progress(1.0)
            self._set_status("● Hoàn tất ✓")
            self.eta_text.set("00:00")
            messagebox.showinfo(APP_TITLE, f"Đã xuất file:\n{self.output_path.get()}")
        else:
            self._set_status("● Có lỗi xảy ra ✗")
            messagebox.showerror(APP_TITLE, f"Có lỗi xảy ra:\n{error}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    TranscribeApp().run()


if __name__ == "__main__":
    main()
