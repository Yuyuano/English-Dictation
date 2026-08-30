"""听写轮次状态机——纯 Python，不依赖 GUI 与磁盘 IO，可独立单元测试。

牌堆制设计：把所选单词洗牌成一副牌逐张弹出，因此：
- 旧版 "set 计数 vs 词数比较" 的终止判断 bug 从结构上不可能再发生
- 词库里有重复单词时，每次出现都算一道独立的题，轮次总能正常结束

计分规则（由状态机保证，UI 无法绕过）：
- 每道题只有**首次提交**计分（scored=True）
- 答错后继续输入属于练习性重答，永远不再计分
- 在未作答的题上点"下一题"视为跳过，记一次错误
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .answer import check_answer
from .models import Word


class RoundError(Exception):
    """在非法状态下调用状态机（例如轮次已结束后提交）。"""


@dataclass(frozen=True)
class Question:
    index: int      # 从 1 开始
    total: int
    word: Word


@dataclass(frozen=True)
class SubmitOutcome:
    word: Word
    user_answer: str
    expected: str   # 标准答案原文（未规范化，用于展示）
    correct: bool
    scored: bool    # False = 练习性重答，未计分


@dataclass(frozen=True)
class Attempt:
    word: Word
    correct: bool


@dataclass
class RoundResult:
    """本轮（或提前结束时已作答部分）的完整记录。"""

    attempts: List[Attempt]

    @property
    def answered(self) -> int:
        return len(self.attempts)

    @property
    def score(self) -> int:
        return sum(1 for a in self.attempts if a.correct)

    def wrong_words(self) -> List[Word]:
        """答错的单词，按出现顺序去重（供"错词重练"使用）。"""
        seen: set[str] = set()
        out: List[Word] = []
        for a in self.attempts:
            if not a.correct and a.word.key not in seen:
                seen.add(a.word.key)
                out.append(a.word)
        return out


class DictationRound:
    """一轮听写。创建即自动开始第一题（空牌堆时 is_finished 为 True）。"""

    def __init__(self, words: Sequence[Word], rng: Optional[random.Random] = None):
        self._deck: List[Word] = list(words)
        (rng or random.Random()).shuffle(self._deck)
        self._total = len(self._deck)
        self._pos = 0                                        # 当前题下标（0-based）
        self._current: Optional[Word] = self._deck[0] if self._deck else None
        self._answered = False                               # 当前题是否已计分
        self._attempts: List[Attempt] = []

    # ---------- 查询 ----------
    @property
    def question(self) -> Optional[Question]:
        """当前题目；轮次已结束返回 None。"""
        if self._current is None:
            return None
        return Question(self._pos + 1, self._total, self._current)

    @property
    def is_finished(self) -> bool:
        return self._current is None

    @property
    def result(self) -> RoundResult:
        return RoundResult(list(self._attempts))

    # ---------- 动作 ----------
    def submit(self, text: str) -> SubmitOutcome:
        """提交当前题答案。首次提交计分，之后的提交只做练习性判对错。"""
        if self._current is None:
            raise RoundError("本轮已经结束，不能再提交")
        correct = check_answer(text, self._current.word)
        if not self._answered:
            self._answered = True
            self._attempts.append(Attempt(self._current, correct))
            return SubmitOutcome(self._current, text, self._current.word, correct, scored=True)
        return SubmitOutcome(self._current, text, self._current.word, correct, scored=False)

    def advance(self) -> Optional[Question]:
        """进入下一题。

        若当前题尚未作答，按跳过处理并记一次错误。
        返回下一题；全部完成时返回 None 并结束本轮。
        """
        if self._current is None:
            return None
        if not self._answered:
            self._answered = True
            self._attempts.append(Attempt(self._current, False))
        self._pos += 1
        if self._pos >= self._total:
            self._current = None
            return None
        self._current = self._deck[self._pos]
        self._answered = False
        return self.question
