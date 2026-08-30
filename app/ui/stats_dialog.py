"""统计对话框：总体概览 + 逐词正确率表格（薄弱词排最前）。"""
from __future__ import annotations

from typing import Dict, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..storage import LibraryRepository, StatsRepository

_RATE_BAD = "#ff5f56"
_RATE_MID = "#e5c07b"
_RATE_GOOD = "#34c77b"


def _rate_color(rate: float) -> QColor:
    if rate >= 80:
        return QColor(_RATE_GOOD)
    if rate >= 50:
        return QColor(_RATE_MID)
    return QColor(_RATE_BAD)


class _SummaryCard(QFrame):
    def __init__(self, caption: str, value: str, color: str = "#e8eaed", parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        lbl_value = QLabel(value)
        lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_value.setStyleSheet(f"font-size: 18pt; font-weight: 700; color: {color};")
        lbl_caption = QLabel(caption)
        lbl_caption.setProperty("hint", True)
        lbl_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_value)
        layout.addWidget(lbl_caption)


class StatsDialog(QDialog):
    def __init__(self, lib_name: str, stats: StatsRepository, libs: LibraryRepository, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"统计 — {lib_name}")
        self.resize(580, 520)

        summary = stats.lib_summary(lib_name)
        total = sum(t for _, t in summary.values())
        correct = sum(c for c, _ in summary.values())
        rate = correct / total * 100 if total else 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        cards = QHBoxLayout()
        cards.addWidget(_SummaryCard("总题次", str(total)))
        cards.addWidget(_SummaryCard("正确", str(correct), _RATE_GOOD))
        cards.addWidget(_SummaryCard("正确率", f"{rate:.1f}%", _rate_color(rate)))
        root.addLayout(cards)

        if not summary:
            empty = QLabel("该词库暂无答题记录\n\n去完成一轮听写后再来看统计吧")
            empty.setProperty("hint", True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(empty, stretch=1)
            return

        # 词 -> 释义 的映射（词库可能已被编辑，取不到就留空）
        meanings: Dict[str, str] = {}
        try:
            meanings = {w.word: w.meaning for w in libs.load(lib_name).words}
        except Exception:
            pass

        table = QTableWidget(len(summary), 4, self)
        table.setHorizontalHeaderLabels(["单词", "释义", "正确 / 总次", "正确率"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setSortingEnabled(False)
        table.verticalHeader().setDefaultSectionSize(34)

        # 薄弱词优先：正确率升序，同率按练习次数降序
        ordered = sorted(
            summary.items(),
            key=lambda kv: (kv[1][0] / kv[1][1] if kv[1][1] else 0.0, -kv[1][1]),
        )
        for row, (word, (c, t)) in enumerate(ordered):
            word_rate = c / t * 100 if t else 0.0
            item_word = QTableWidgetItem(word)
            item_meaning = QTableWidgetItem(meanings.get(word, ""))
            item_count = QTableWidgetItem(f"{c} / {t}")
            item_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_rate = QTableWidgetItem(f"{word_rate:.0f}%")
            item_rate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_rate.setForeground(_rate_color(word_rate))
            for col, item in enumerate((item_word, item_meaning, item_count, item_rate)):
                table.setItem(row, col, item)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(table, stretch=1)

        hint = QLabel("已按正确率升序排列，最薄弱的单词排在最前面")
        hint.setProperty("hint", True)
        root.addWidget(hint)
