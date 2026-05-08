#!/usr/bin/env bash
# Launcher for macOS / Linux.
# Double-click (or run from terminal) to launch the SUPS transcription app.
# On first launch it creates a virtualenv and installs requirements.

set -e

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Lỗi: không tìm thấy $PYTHON. Hãy cài Python 3.9+ trước." >&2
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[setup] Tạo virtualenv tại $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if [ ! -f "$VENV_DIR/.deps_installed" ]; then
    echo "[setup] Cài đặt thư viện (chỉ chạy lần đầu)..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    touch "$VENV_DIR/.deps_installed"
fi

echo "[run] Khởi động ứng dụng..."
exec python app.py "$@"
