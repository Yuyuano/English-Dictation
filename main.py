"""English Dictation 程序入口。

装配依赖并启动 Qt 主循环：
    .venv/Scripts/python.exe main.py
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import LOG_FILE, Settings, ensure_dirs
from app.storage import LibraryRepository, StatsRepository
from app.tts import SpeakerService
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def _setup_logging() -> None:
    """windowed exe 里 stderr 不可见，异常统一落到 error.log。"""
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)


def _excepthook(etype, value, tb) -> None:
    logging.getLogger().critical("未捕获异常", exc_info=(etype, value, tb))
    try:
        QMessageBox.critical(None, "程序错误", f"{value}\n\n详细信息已写入 error.log")
    except Exception:
        pass


def main() -> int:
    ensure_dirs()
    _setup_logging()
    sys.excepthook = _excepthook

    app = QApplication(sys.argv)
    app.setApplicationName("English Dictation")
    apply_theme(app)

    settings = Settings.load()
    stats = StatsRepository()
    speaker = SpeakerService(rate=settings.tts_rate, volume=settings.tts_volume)
    libs = LibraryRepository()

    window = MainWindow(libs, stats, speaker, settings)
    window.show()
    try:
        code = app.exec()
    finally:
        speaker.shutdown()
        stats.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
