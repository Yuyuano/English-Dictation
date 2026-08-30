"""听写对话框：答题页 + 结果页（QStackedWidget 切换）。

交互逻辑全部由 app.dictation.DictationRound 状态机驱动：
- 每题只有首次提交计分；答错后可继续练习性重答（不再计分）
- 答对后延迟自动进入下一题，期间「提交/下一题」都不会造成重复推进
- 未作答点「下一题」= 跳过，记一次错误
- 全部完成或提前结束时进入结果页，支持错词重练 / 再来一轮
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, TTS_DEFAULT_REPEAT
from ..dictation import DictationRound, Question, RoundError, RoundResult
from ..models import Word
from ..storage import StatsRepository
from ..tts import SpeakerService

_GREEN = "#34c77b"
_RED = "#ff5f56"
_GRAY = "#9aa0a6"


class _WrongWordRow(QFrame):
    """结果页里的一行错词。"""

    playRequested = Signal(object)

    def __init__(self, word: Word, parent=None):
        super().__init__(parent)
        self.word = word
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        lbl_word = QLabel(word.word)
        lbl_word.setStyleSheet("font-weight: 600;")
        lbl_mean = QLabel(word.meaning)
        lbl_mean.setProperty("hint", True)
        lbl_mean.setStyleSheet(f"color: {_GRAY};")
        btn = QPushButton("🔊")
        btn.setProperty("class", "icon")
        btn.setToolTip("播放该词发音")
        btn.clicked.connect(lambda: self.playRequested.emit(self.word))
        layout.addWidget(lbl_word)
        layout.addWidget(lbl_mean, stretch=1)
        layout.addWidget(btn)


class DictationDialog(QDialog):
    def __init__(
        self,
        lib_name: str,
        words: List[Word],
        speaker: SpeakerService,
        stats: StatsRepository,
        settings: Settings,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"听写 — {lib_name}")
        self.resize(640, 540)

        self._lib_name = lib_name
        self._words = list(words)
        self._speaker = speaker
        self._stats = stats
        self._settings = settings
        self._round: Optional[DictationRound] = None
        self._last_wrong: List[Word] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_next)

        self._build_ui()
        self._new_round(self._words)

    # ================= UI 构建 =================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget(self)
        root.addWidget(self._stack)
        self._stack.addWidget(self._build_quiz_page())
        self._stack.addWidget(self._build_result_page())

    def _build_quiz_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 顶部：词库 + 进度
        header = QHBoxLayout()
        self.lbl_lib = QLabel(self._lib_name)
        self.lbl_lib.setProperty("hint", True)
        self.lbl_pos = QLabel("")
        self.lbl_pos.setStyleSheet("font-weight: 600;")
        header.addWidget(self.lbl_lib)
        header.addStretch(1)
        header.addWidget(self.lbl_pos)
        layout.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        layout.addWidget(self.progress)

        # 中部：释义 + 播放
        layout.addStretch(1)
        caption = QLabel("听到并拼出这个单词")
        caption.setProperty("hint", True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)

        self.lbl_meaning = QLabel("")
        self.lbl_meaning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_meaning.setWordWrap(True)
        self.lbl_meaning.setStyleSheet("font-size: 22pt; font-weight: 700;")
        layout.addWidget(self.lbl_meaning)

        row_play = QHBoxLayout()
        row_play.addStretch(1)
        self.btn_play = QPushButton("🔊 再听一遍 (Ctrl+R)")
        self.btn_play.clicked.connect(self._replay)
        row_play.addWidget(self.btn_play)
        row_play.addStretch(1)
        layout.addLayout(row_play)
        layout.addStretch(1)

        # 输入区
        self.ed_input = QLineEdit()
        self.ed_input.setPlaceholderText("输入你听到的单词，回车提交")
        self.ed_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ed_input.setStyleSheet("font-size: 14pt; padding: 10px;")
        self.ed_input.returnPressed.connect(self._on_submit)
        layout.addWidget(self.ed_input)

        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setMinimumHeight(44)
        layout.addWidget(self.lbl_feedback)

        # 按钮行
        row_btn = QHBoxLayout()
        self.btn_submit = QPushButton("提交")
        self.btn_submit.setProperty("class", "primary")
        self.btn_submit.clicked.connect(self._on_submit)
        self.btn_next = QPushButton("下一题")
        self.btn_next.setToolTip("未作答时点击视为跳过（记一次错误）")
        self.btn_next.clicked.connect(self._on_next)
        self.btn_finish = QPushButton("结束")
        self.btn_finish.clicked.connect(self._on_finish)
        row_btn.addWidget(self.btn_finish)
        row_btn.addStretch(1)
        row_btn.addWidget(self.btn_next)
        row_btn.addWidget(self.btn_submit)
        layout.addLayout(row_btn)

        replay_shortcut = QShortcut(QKeySequence("Ctrl+R"), page)
        replay_shortcut.activated.connect(self._replay)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(12)

        self.lbl_score = QLabel("")
        self.lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_score.setStyleSheet("font-size: 30pt; font-weight: 700;")
        layout.addWidget(self.lbl_score)

        self.lbl_score_caption = QLabel("")
        self.lbl_score_caption.setProperty("hint", True)
        self.lbl_score_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_score_caption)

        self.lbl_wrong_title = QLabel("答错的单词")
        self.lbl_wrong_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.lbl_wrong_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self._wrong_layout = QVBoxLayout(body)
        self._wrong_layout.setContentsMargins(0, 0, 4, 0)
        self._wrong_layout.setSpacing(6)
        self._wrong_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        row = QHBoxLayout()
        self.btn_repractice = QPushButton("🔁 错词重练")
        self.btn_repractice.setProperty("class", "primary")
        self.btn_repractice.clicked.connect(self._on_repractice)
        self.btn_restart = QPushButton("再来一轮")
        self.btn_restart.clicked.connect(self._on_restart)
        btn_close = QPushButton("返回主页")
        btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_restart)
        row.addWidget(self.btn_repractice)
        row.addStretch(1)
        row.addWidget(btn_close)
        layout.addLayout(row)
        return page

    # ================= 轮次控制 =================
    def _new_round(self, words: List[Word]) -> None:
        self._round = DictationRound(words)
        q = self._round.question
        if q is None:  # 空牌堆不该发生（主窗口已拦截），保险处理
            self.reject()
            return
        self._stack.setCurrentIndex(0)
        self.progress.setMaximum(q.total)
        self._show_question(q)

    def _show_question(self, q: Question) -> None:
        self._timer.stop()
        self.lbl_pos.setText(f"第 {q.index} / {q.total} 题")
        self.progress.setValue(q.index)
        self.lbl_meaning.setText(q.word.meaning or "（该词没有释义）")
        self.ed_input.clear()
        self.ed_input.setEnabled(True)
        self.btn_submit.setEnabled(True)
        self._set_feedback("", _GRAY)
        self.ed_input.setFocus()
        # 出题自动朗读两遍（词组较长时便于听清）
        self._speaker.speak(q.word.word, repeat=TTS_DEFAULT_REPEAT)

    def _set_feedback(self, text: str, color: str) -> None:
        self.lbl_feedback.setText(text)
        self.lbl_feedback.setStyleSheet(f"color: {color}; font-size: 11pt;")

    # ================= 动作 =================
    def _replay(self) -> None:
        q = self._round.question if self._round else None
        if q is not None and self._stack.currentIndex() == 0:
            self._speaker.speak(q.word.word, repeat=1)

    def _on_submit(self) -> None:
        if self._round is None or self._stack.currentIndex() != 0:
            return
        text = self.ed_input.text()
        if not text.strip():
            self._set_feedback("请先输入拼写", _GRAY)
            return
        try:
            outcome = self._round.submit(text)
        except RoundError:
            return
        if outcome.scored:
            self._stats.record(self._lib_name, outcome.word.word, outcome.correct)

        if outcome.correct:
            if outcome.scored:
                c, t = self._stats.get(self._lib_name, outcome.word.word)
                rate = c / t * 100 if t else 0.0
                self._set_feedback(f"✅ 正确！（该词历史正确率 {rate:.0f}%）", _GREEN)
            else:
                self._set_feedback("✅ 已写对！点击「下一题」继续", _GREEN)
            self.ed_input.setEnabled(False)
            self.btn_submit.setEnabled(False)
            self.btn_next.setFocus()
            self._timer.start(self._settings.auto_next_delay_ms)  # 稍后自动进入下一题
        else:
            if outcome.scored:
                self._set_feedback(f"❌ 正确答案：{outcome.expected}（可重写练习，不再计分）", _RED)
            else:
                self._set_feedback(f"❌ 还不对哦，正确答案：{outcome.expected}", _RED)
            self.ed_input.selectAll()
            self.ed_input.setFocus()

    def _on_next(self) -> None:
        if self._round is None or self._stack.currentIndex() != 0:
            return
        if self._timer.isActive():
            self._timer.stop()
        try:
            q = self._round.advance()
        except RoundError:
            return
        if q is None:
            self._show_result()
        else:
            self._show_question(q)

    def _on_finish(self) -> None:
        """结束按钮：无任何作答直接关闭；已作答则查看当前结果。"""
        if self._round is None:
            self.reject()
            return
        if self._round.result.answered == 0:
            self.reject()
            return
        self._show_result()

    # ================= 结果页 =================
    def _show_result(self) -> None:
        self._timer.stop()
        result: RoundResult = self._round.result
        self._last_wrong = result.wrong_words()
        score, answered = result.score, result.answered
        rate = score / answered * 100 if answered else 0.0

        color = _GREEN if rate >= 80 else ("#e5c07b" if rate >= 50 else _RED)
        self.lbl_score.setText(f"{score} / {answered}")
        self.lbl_score.setStyleSheet(f"font-size: 30pt; font-weight: 700; color: {color};")
        finished_all = answered == self.progress.maximum()
        caption = "本轮全部完成" if finished_all else f"提前结束（本轮共 {self.progress.maximum()} 题）"
        self.lbl_score_caption.setText(f"{caption} · 正确率 {rate:.0f}%")

        # 重建错词列表
        while self._wrong_layout.count() > 1:
            item = self._wrong_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for w in self._last_wrong:
            row = _WrongWordRow(w)
            row.playRequested.connect(lambda word: self._speaker.speak(word.word, 1))
            self._wrong_layout.insertWidget(self._wrong_layout.count() - 1, row)
        self.lbl_wrong_title.setVisible(bool(self._last_wrong))
        self.btn_repractice.setEnabled(bool(self._last_wrong))
        self.btn_repractice.setText(f"🔁 错词重练（{len(self._last_wrong)} 词）")

        self._stack.setCurrentIndex(1)

    def _on_repractice(self) -> None:
        if self._last_wrong:
            self._new_round(self._last_wrong)

    def _on_restart(self) -> None:
        self._new_round(self._words)

    # ================= 关闭保护 =================
    def reject(self) -> None:  # noqa: D102 — 覆盖 Esc / 关闭按钮
        if (
            self._round is not None
            and self._stack.currentIndex() == 0
            and 0 < self._round.result.answered < self.progress.maximum()
        ):
            answer = QMessageBox.question(
                self,
                "结束听写",
                "本轮听写还没做完，确定要结束并查看当前结果吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().reject()
