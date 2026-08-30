"""仓储层：词库 JSON 文件 与 SQLite 统计。

设计要点：
- 所有可预期故障（JSON 损坏、文件缺失、磁盘 IO 失败）都转成带友好中文
  消息的 LibraryError，由 UI 层直接展示——不再出现"打包成 exe 后静默失败"
- 库名经正则白名单校验，杜绝路径分隔符注入
- 导入词库时先在源文件上完成结构与内容校验，通过后才复制
- 统计写入用单条 INSERT ... ON CONFLICT 原子 upsert
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

from .config import DB_FILE, LIBS_DIR
from .models import Library, Word


class LibraryError(Exception):
    """词库相关错误的统一异常，消息可直接展示给用户。"""


# 中文/英文/数字/空格/下划线/连字符，1~64 位，首字符不能是空格
NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff][A-Za-z0-9_\-\u4e00-\u9fff ]{0,63}$")


def validate_lib_name(name: str) -> str:
    """校验并返回 strip 后的库名；非法时抛 LibraryError。"""
    cleaned = (name or "").strip()
    if not cleaned:
        raise LibraryError("词库名称不能为空")
    if not NAME_RE.match(cleaned):
        raise LibraryError("词库名称只能包含中文、英文、数字、空格、下划线和连字符（1~64 位）")
    return cleaned


def parse_words(data: object) -> List[Word]:
    """把 JSON 数据解析为 Word 列表；结构非法时抛 LibraryError。"""
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        raise LibraryError('JSON 格式不正确：需要形如 {"words": [{"word": "apple", "meaning": "苹果"}]}')
    words: List[Word] = []
    for i, item in enumerate(data["words"], start=1):
        if not isinstance(item, dict) or "word" not in item:
            raise LibraryError(f"第 {i} 条记录缺少 word 字段")
        try:
            words.append(Word(str(item["word"]), str(item.get("meaning", ""))))
        except ValueError as e:
            raise LibraryError(f"第 {i} 条记录无效：{e}") from e
    return words


def dump_words(words: List[Word]) -> dict:
    return {"words": [w.to_dict() for w in words]}


class LibraryRepository:
    """Libraries/*.json 词库文件的读写。"""

    def __init__(self, libs_dir: Path = LIBS_DIR):
        self._dir = Path(libs_dir)

    @property
    def root(self) -> Path:
        return self._dir

    def _lib_path(self, name: str) -> Path:
        return self._dir / f"{validate_lib_name(name)}.json"

    def scan(self) -> List[str]:
        """返回全部词库名（按名称排序）。"""
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def exists(self, name: str) -> bool:
        return self._lib_path(name).exists()

    def load(self, name: str) -> Library:
        path = self._lib_path(name)
        if not path.exists():
            raise LibraryError(f"词库 '{name}' 不存在（可能已被移动或删除）")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise LibraryError(f"读取词库 '{name}' 失败：{e}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LibraryError(f"词库 '{name}' 不是有效的 JSON 文件：{e}") from e
        return Library(name, parse_words(data))

    def save(self, lib: Library, overwrite: bool = False) -> Path:
        path = self._lib_path(lib.name)
        if path.exists() and not overwrite:
            raise LibraryError(f"词库 '{lib.name}' 已存在")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(dump_words(lib.words), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise LibraryError(f"保存词库失败：{e}") from e
        return path

    def import_json(self, src: Path) -> str:
        """导入外部 JSON：先校验再复制，重名自动加 _1/_2 后缀。返回新词库名。"""
        src = Path(src)
        if src.suffix.lower() != ".json":
            raise LibraryError("仅支持导入 *.json 文件")
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except OSError as e:
            raise LibraryError(f"无法读取所选文件：{e}") from e
        except json.JSONDecodeError as e:
            raise LibraryError(f"所选文件不是有效的 JSON：{e}") from e
        parse_words(data)  # 内容校验，不通过就不复制

        stem = re.sub(r'[\\/:*?"<>|!]', "_", src.stem.strip()) or "imported"
        try:
            base = validate_lib_name(stem)
        except LibraryError:
            base = "imported"
        dst_name = base
        counter = 1
        while (self._dir / f"{dst_name}.json").exists():
            dst_name = f"{base}_{counter}"
            counter += 1
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, self._dir / f"{dst_name}.json")
        except OSError as e:
            raise LibraryError(f"导入失败：{e}") from e
        return dst_name

    def export(self, name: str, dst: Path) -> Path:
        """把指定词库导出为标准格式 JSON。"""
        lib = self.load(name)
        dst = Path(dst)
        try:
            dst.write_text(
                json.dumps(dump_words(lib.words), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise LibraryError(f"导出失败：{e}") from e
        return dst


class StatsRepository:
    """SQLite 统计：按 (库名, 单词) 记录正确数/总次数。表结构与旧版兼容。"""

    def __init__(self, db_file: Path = DB_FILE):
        self._db_file = Path(db_file)
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_file)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS record (
                lib_name TEXT,
                word     TEXT,
                correct  INTEGER DEFAULT 0,
                total    INTEGER DEFAULT 0,
                PRIMARY KEY (lib_name, word)
            )
            """
        )
        self._conn.commit()

    def record(self, lib: str, word: str, correct: bool) -> None:
        """原子累加一次作答记录。"""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO record (lib_name, word, correct, total) VALUES (?, ?, ?, ?)
                ON CONFLICT(lib_name, word) DO UPDATE SET
                    correct = correct + excluded.correct,
                    total   = total + excluded.total
                """,
                (lib, word, int(correct), 1),
            )

    def get(self, lib: str, word: str) -> Tuple[int, int]:
        """返回某单词的 (正确数, 总次数)；无记录返回 (0, 0)。"""
        row = self._conn.execute(
            "SELECT correct, total FROM record WHERE lib_name=? AND word=?",
            (lib, word),
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def lib_summary(self, lib: str) -> Dict[str, Tuple[int, int]]:
        """返回整个词库所有单词的统计 {word: (correct, total)}。"""
        rows = self._conn.execute(
            "SELECT word, correct, total FROM record WHERE lib_name=?",
            (lib,),
        ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StatsRepository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
