"""值对象。所有文本在构造时统一 strip，避免脏数据流入下游。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Word:
    """一个待听写单词。word 为空视为非法。"""

    word: str
    meaning: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "word", str(self.word).strip())
        object.__setattr__(self, "meaning", str(self.meaning).strip())
        if not self.word:
            raise ValueError("单词不能为空")

    @property
    def key(self) -> str:
        """用于勾选/去重的稳定键。"""
        return self.word.lower()

    def to_dict(self) -> dict:
        return {"word": self.word, "meaning": self.meaning}


@dataclass
class Library:
    """一个词库：名称 + 单词列表。名称合法性由 storage.validate_lib_name 校验。"""

    name: str
    words: List[Word] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
