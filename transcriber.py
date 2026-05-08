"""
Transcription core for the SUPS app.

Uses faster-whisper to convert speech in audio/video files into text.
ffmpeg is bundled via imageio-ffmpeg so users don't need to install it separately.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


# Audio + video file extensions we accept as input.
SUPPORTED_EXTENSIONS = {
    # video
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpeg", ".mpg", ".ts",
    # audio
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
}


# Map of UI labels -> Whisper language codes. ``None`` = auto-detect.
LANGUAGE_CHOICES: dict[str, Optional[str]] = {
    "Auto detect (tự nhận diện)": None,
    "Tiếng Việt (Vietnamese)": "vi",
    "English": "en",
    "中文 (Chinese)": "zh",
    "日本語 (Japanese)": "ja",
    "한국어 (Korean)": "ko",
    "Français (French)": "fr",
    "Deutsch (German)": "de",
    "Español (Spanish)": "es",
    "Português (Portuguese)": "pt",
    "Русский (Russian)": "ru",
    "ไทย (Thai)": "th",
    "Bahasa Indonesia": "id",
    "हिन्दी (Hindi)": "hi",
    "العربية (Arabic)": "ar",
    "Italiano (Italian)": "it",
}


# Whisper model sizes available out of the box.
MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict]
    language: str
    duration: float


def get_ffmpeg_executable() -> str:
    """Return path to a usable ffmpeg binary.

    Prefers the bundled imageio-ffmpeg binary (no extra install required).
    Falls back to a system ``ffmpeg`` if available.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        path = shutil.which("ffmpeg")
        if path:
            return path
        raise RuntimeError(
            "Không tìm thấy ffmpeg. Hãy cài 'imageio-ffmpeg' hoặc ffmpeg hệ thống."
        )


def extract_audio(
    media_path: str,
    out_wav: str,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extract a 16 kHz mono WAV from any audio/video file using ffmpeg."""
    ffmpeg = get_ffmpeg_executable()
    cmd = [
        ffmpeg,
        "-y",
        "-i", media_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        out_wav,
    ]
    if log:
        log(f"[ffmpeg] {' '.join(cmd)}")

    creationflags = 0
    if sys.platform == "win32":
        # Hide the extra console window on Windows.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg thất bại khi tách audio:\n" + proc.stderr.decode("utf-8", "ignore")
        )
    return out_wav


def _format_timestamp(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SRT style)."""
    if seconds < 0:
        seconds = 0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3600 * 1000)
    minutes, millis = divmod(millis, 60 * 1000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: Iterable[dict]) -> str:
    out_lines: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg["text"].strip()
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        out_lines.append(text)
        out_lines.append("")
    return "\n".join(out_lines).strip() + "\n"


def segments_to_plain_text(segments: Iterable[dict], with_timestamps: bool = False) -> str:
    lines: list[str] = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if with_timestamps:
            lines.append(f"[{_format_timestamp(seg['start'])}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


class Transcriber:
    """Wrapper around faster-whisper that streams progress to a callback."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        download_root: Optional[str] = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self._model = None

    def _resolve_compute_type(self, device: str) -> str:
        if self.compute_type != "auto":
            return self.compute_type
        if device == "cuda":
            return "float16"
        return "int8"

    def load_model(self, log: Optional[Callable[[str], None]] = None) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        device = self.device
        if device == "auto":
            try:
                import ctranslate2  # noqa: F401  (used by faster-whisper)

                # ctranslate2 doesn't expose a simple "is cuda available" check,
                # so we fall back to CPU which always works.
                device = "cpu"
            except Exception:
                device = "cpu"
        compute_type = self._resolve_compute_type(device)

        if log:
            log(
                f"[whisper] Đang tải model '{self.model_size}' "
                f"(device={device}, compute_type={compute_type})..."
            )
        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
            download_root=self.download_root,
        )
        if log:
            log("[whisper] Model đã sẵn sàng.")

    def transcribe(
        self,
        media_path: str,
        language: Optional[str] = None,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[float], None]] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        """Transcribe ``media_path`` and return text + segments.

        ``progress`` receives floats in ``[0.0, 1.0]`` based on segment end time.
        """
        if not os.path.isfile(media_path):
            raise FileNotFoundError(media_path)

        ext = Path(media_path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            if log:
                log(f"[warn] Định dạng '{ext}' không nằm trong danh sách hỗ trợ, vẫn thử xử lý.")

        self.load_model(log=log)
        assert self._model is not None

        with tempfile.TemporaryDirectory(prefix="sups_") as tmp:
            wav_path = os.path.join(tmp, "audio.wav")
            if log:
                log("[ffmpeg] Tách audio sang WAV 16kHz mono...")
            extract_audio(media_path, wav_path, log=log)

            if log:
                log("[whisper] Bắt đầu nhận dạng giọng nói...")
            segments_iter, info = self._model.transcribe(
                wav_path,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )

            duration = float(getattr(info, "duration", 0.0) or 0.0)
            detected_language = getattr(info, "language", language or "unknown")
            if log:
                log(
                    f"[whisper] Ngôn ngữ phát hiện: {detected_language} "
                    f"(độ tin cậy {getattr(info, 'language_probability', 0.0):.2f}); "
                    f"tổng thời lượng {duration:.1f}s"
                )

            collected: list[dict] = []
            for seg in segments_iter:
                collected.append(
                    {
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "text": seg.text,
                    }
                )
                if progress and duration > 0:
                    progress(min(1.0, float(seg.end) / duration))
                if log:
                    log(
                        f"  [{_format_timestamp(seg.start)} - {_format_timestamp(seg.end)}] "
                        f"{seg.text.strip()}"
                    )

            text = segments_to_plain_text(collected, with_timestamps=False)
            return TranscriptionResult(
                text=text,
                segments=collected,
                language=detected_language,
                duration=duration,
            )
