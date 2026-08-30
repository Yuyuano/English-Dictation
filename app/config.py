"""路径解析与用户设置。

注意：本模块在导入时**不做任何文件系统副作用**（目录创建移到 ensure_dirs()），
以便测试可以安全导入。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 打包成 exe 后以 exe 所在目录为根；源码运行则以项目根目录为根
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

LIBS_DIR = BASE_DIR / "Libraries"          # 词库 JSON 根目录
DB_FILE = BASE_DIR / "stats.db"            # SQLite 统计库（沿用旧版表结构）
SETTINGS_FILE = BASE_DIR / "settings.json" # 用户设置
LOG_FILE = BASE_DIR / "error.log"          # 异常日志

# ---- 默认参数 ----
TTS_DEFAULT_RATE = 130        # 语速（词/分钟），pyttsx3 rate
TTS_DEFAULT_VOLUME = 0.9      # 音量 0.0 ~ 1.0
TTS_DEFAULT_REPEAT = 2        # 出题时自动朗读次数
AUTO_NEXT_DELAY_MS = 2000     # 答对后自动进入下一题的延迟


def ensure_dirs() -> None:
    """创建运行所需目录。仅在 main() 启动时调用。"""
    LIBS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    """持久化到 settings.json 的用户设置，字段越界值在加载时被钳制。"""

    tts_rate: int = TTS_DEFAULT_RATE
    tts_volume: float = TTS_DEFAULT_VOLUME
    auto_next_delay_ms: int = AUTO_NEXT_DELAY_MS

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        s = cls()
        if isinstance(raw, dict):
            if isinstance(raw.get("tts_rate"), int):
                s.tts_rate = max(60, min(260, raw["tts_rate"]))
            if isinstance(raw.get("tts_volume"), (int, float)):
                s.tts_volume = max(0.0, min(1.0, float(raw["tts_volume"])))
            if isinstance(raw.get("auto_next_delay_ms"), int):
                s.auto_next_delay_ms = max(500, min(10000, raw["auto_next_delay_ms"]))
        return s

    def save(self) -> None:
        try:
            SETTINGS_FILE.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # 设置写不进去不影响主流程
