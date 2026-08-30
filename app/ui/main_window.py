"""主窗口：左侧词库管理 + 右侧单词勾选与听写入口。

状态保存在 Python 模型里（_words / _selected），界面只是投影——
旧版"从 Listbox 显示串反解析数据"的一类 bug 从设计上被移除。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..models import Word
from ..storage import LibraryError, LibraryRepository, StatsRepository, validate_lib_name
from ..tts import SpeakerService
from .dictation_dialog import DictationDialog
from .library_editor import LibraryEditorDialog
from .stats_dialog import StatsDialog


class WordRow(QFrame):
    """单词列表中的一行：勾选框 + 单词 + 释义 + 逐词播放按钮。"""

    toggled = Signal(object, bool)   # (Word, checked)
    playRequested = Signal(object)   # Word

    def __init__(self, word: Word, parent=None):
        super().__init__(parent)
        self.word = word
        self.setObjectName("wordRow")
        self.setStyleSheet(
            "#wordRow { background: #1e2026; border: 1px solid #2d313b; border-radius: 6px; }"
            "#wordRow:hover { border-color: #3a3f4b; }"
        )
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        self.checkbox = QCheckBox()
        self.checkbox.setToolTip("选择该单词")
        self.checkbox.toggled.connect(self._on_toggled)

        lbl_word = QLabel(word.word)
        font = lbl_word.font()
        font.setBold(True)
        lbl_word.setFont(font)
        lbl_word.setMinimumWidth(150)

        lbl_mean = QLabel(word.meaning)
        lbl_mean.setProperty("hint", True)
        lbl_mean.setStyleSheet("color: #9aa0a6;")

        btn_play = QPushButton("🔊")
        btn_play.setProperty("class", "icon")
        btn_play.setToolTip(f"播放 “{word.word}”")
        btn_play.clicked.connect(lambda: self.playRequested.emit(self.word))

        layout.addWidget(self.checkbox)
        layout.addWidget(lbl_word)
        layout.addWidget(lbl_mean, stretch=1)
        layout.addWidget(btn_play)

    def _on_toggled(self, checked: bool) -> None:
        self.toggled.emit(self.word, checked)


class MainWindow(QMainWindow):
    def __init__(
        self,
        libs: LibraryRepository,
        stats: StatsRepository,
        speaker: SpeakerService,
        settings: Settings,
    ):
        super().__init__()
        self._libs = libs
        self._stats = stats
        self._speaker = speaker
        self._settings = settings

        self._current_lib: Optional[str] = None
        self._words: List[Word] = []
        self._rows: List[WordRow] = []
        self._selected: Set[str] = set()

        self.setWindowTitle("English Dictation · 英语听写")
        self.resize(960, 620)
        self.setMinimumSize(840, 560)
        self._build_ui()
        self._speaker.errorOccurred.connect(
            lambda msg: self.statusBar().showMessage(msg, 8000)
        )
        self._refresh_libs()

    # ================= UI 构建 =================
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_right(), stretch=1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        sidebar.setStyleSheet(
            "#sidebar { background: #1b1d23; border-right: 1px solid #23252c; }"
            "#sidebar QPushButton { text-align: left; padding: 7px 12px; }"
        )

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        title = QLabel("English Dictation")
        title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        subtitle = QLabel("英语听写练习")
        subtitle.setProperty("hint", True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        lbl_libs = QLabel("词库")
        lbl_libs.setProperty("hint", True)
        layout.addWidget(lbl_libs)

        self.lib_list = QListWidget()
        self.lib_list.currentRowChanged.connect(self._on_lib_changed)
        layout.addWidget(self.lib_list, stretch=1)

        grid = QGridLayout()
        grid.setSpacing(6)
        buttons = [
            ("📂 导入词库", self.on_import),
            ("➕ 新建词库", self.on_create),
            ("✏️ 编辑词库", self.on_edit),
            ("💾 导出词库", self.on_export),
            ("📊 查看统计", self.on_stats),
            ("🔄 刷新列表", self.on_refresh),
        ]
        for i, (text, slot) in enumerate(buttons):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        layout.addSpacing(6)
        rate_caption = QHBoxLayout()
        lbl_rate = QLabel("语速")
        lbl_rate.setProperty("hint", True)
        self.lbl_rate_value = QLabel(f"{self._settings.tts_rate} 词/分")
        rate_caption.addWidget(lbl_rate)
        rate_caption.addStretch(1)
        rate_caption.addWidget(self.lbl_rate_value)
        layout.addLayout(rate_caption)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(60, 220)
        slider.setValue(self._settings.tts_rate)
        slider.valueChanged.connect(self._on_rate_changed)
        layout.addWidget(slider)
        self._rate_slider = slider

        hint = QLabel("语速会在下次启动时保留")
        hint.setProperty("hint", True)
        layout.addWidget(hint)
        return sidebar

    def _build_right(self) -> QFrame:
        right = QFrame()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("🔍 搜索过滤单词…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._apply_filter)
        top.addWidget(self.ed_search, stretch=1)

        btn_all = QPushButton("全选")
        btn_all.setToolTip("勾选当前筛选后可见的全部单词")
        btn_all.clicked.connect(self._select_visible)
        btn_none = QPushButton("清空")
        btn_none.clicked.connect(self._clear_selection)
        top.addWidget(btn_all)
        top.addWidget(btn_none)
        layout.addLayout(top)

        self.lbl_count = QLabel("已选 0 / 0")
        self.lbl_count.setProperty("hint", True)
        layout.addWidget(self.lbl_count)

        self.hint_empty = QLabel("← 请先在左侧选择一个词库\n\n或点击「导入词库」「新建词库」开始")
        self.hint_empty.setProperty("hint", True)
        self.hint_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_empty, stretch=1)

        self.word_list = QListWidget()
        self.word_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.word_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.word_list.hide()
        layout.addWidget(self.word_list, stretch=1)

        bottom = QHBoxLayout()
        self.lbl_tip = QLabel("勾选要听写的单词后开始")
        self.lbl_tip.setProperty("hint", True)
        self.btn_start = QPushButton("▶ 开始听写")
        self.btn_start.setProperty("class", "primary")
        self.btn_start.setFixedHeight(42)
        self.btn_start.setMinimumWidth(200)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.on_start)
        bottom.addWidget(self.lbl_tip)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_start)
        layout.addLayout(bottom)
        return right

    # ================= 词库列表 =================
    def _refresh_libs(self, select: Optional[str] = None) -> None:
        names = self._libs.scan()
        lib_list = self.lib_list
        lib_list.blockSignals(True)
        lib_list.clear()
        lib_list.addItems(names)
        lib_list.blockSignals(False)

        target = select if select in names else (names[0] if names else None)
        if target is not None:
            lib_list.setCurrentRow(names.index(target))
        else:
            self._current_lib = None
            self._clear_words()
        if names:
            self.statusBar().showMessage(f"共 {len(names)} 个词库", 4000)
        else:
            self.statusBar().showMessage("尚未发现词库，点击左侧「导入词库」或「新建词库」开始", 8000)

    def _on_lib_changed(self, row: int) -> None:
        if row < 0:
            self._current_lib = None
            self._clear_words()
            return
        name = self.lib_list.item(row).text()
        self._populate_words(name)

    def _populate_words(self, name: str) -> None:
        try:
            lib = self._libs.load(name)
        except LibraryError as e:
            QMessageBox.warning(self, "读取词库失败", str(e))
            self._current_lib = None
            self._clear_words()
            return
        self._current_lib = name
        self._words = lib.words
        self._selected = set()
        self.ed_search.clear()

        word_list = self.word_list
        word_list.blockSignals(True)
        word_list.clear()
        self._rows = []
        for w in self._words:
            row = WordRow(w)
            row.toggled.connect(self._on_word_toggled)
            row.playRequested.connect(lambda word: self._speaker.speak(word.word, 1))
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 48))
            word_list.addItem(item)
            word_list.setItemWidget(item, row)
            self._rows.append(row)
        word_list.blockSignals(False)

        has_words = bool(self._words)
        self.word_list.setVisible(has_words)
        self.hint_empty.setVisible(not has_words)
        self.lbl_tip.setText(f"词库「{name}」共 {len(self._words)} 个单词，勾选后开始")
        self._update_counts()

    def _clear_words(self) -> None:
        self._words = []
        self._rows = []
        self._selected = set()
        self.word_list.clear()
        self.word_list.hide()
        self.hint_empty.show()
        self.lbl_tip.setText("勾选要听写的单词后开始")
        self._update_counts()

    # ================= 单词勾选 / 搜索 =================
    def _on_word_toggled(self, word: Word, checked: bool) -> None:
        if checked:
            self._selected.add(word.key)
        else:
            self._selected.discard(word.key)
        self._update_counts()

    def _update_counts(self) -> None:
        self.lbl_count.setText(f"已选 {len(self._selected)} / {len(self._words)}")
        self.btn_start.setEnabled(bool(self._selected))
        self.btn_start.setText(f"▶ 开始听写（{len(self._selected)} 词）")

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()
        for i, row in enumerate(self._rows):
            w = row.word
            match = not q or q in w.word.lower() or q in w.meaning.lower()
            self.word_list.setRowHidden(i, not match)

    def _select_visible(self) -> None:
        for i, row in enumerate(self._rows):
            if not self.word_list.isRowHidden(i):
                row.checkbox.setChecked(True)

    def _clear_selection(self) -> None:
        for row in self._rows:
            row.checkbox.setChecked(False)

    # ================= 动作 =================
    def _require_lib(self) -> Optional[str]:
        if not self._current_lib:
            self.statusBar().showMessage("请先在左侧选择一个词库", 5000)
            return None
        return self._current_lib

    def on_refresh(self) -> None:
        self._refresh_libs(select=self._current_lib)

    def on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 JSON 词库", "", "JSON 词库 (*.json)")
        if not path:
            return
        try:
            name = self._libs.import_json(Path(path))
        except LibraryError as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        self._refresh_libs(select=name)
        self.statusBar().showMessage(f"已导入词库：{name}", 6000)

    def on_create(self) -> None:
        dlg = LibraryEditorDialog(self._libs, lib_name=None, parent=self)
        if dlg.exec() and dlg.lib_name:
            self._refresh_libs(select=dlg.lib_name)

    def on_edit(self) -> None:
        lib = self._require_lib()
        if not lib:
            return
        dlg = LibraryEditorDialog(self._libs, lib_name=lib, parent=self)
        if dlg.exec():
            self._populate_words(lib)
            self.statusBar().showMessage(f"词库「{lib}」已更新", 5000)

    def on_export(self) -> None:
        lib = self._require_lib()
        if not lib:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出词库", f"{lib}.json", "JSON 词库 (*.json)"
        )
        if not path:
            return
        try:
            dst = self._libs.export(lib, Path(path))
        except LibraryError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        self.statusBar().showMessage(f"已导出到 {dst}", 8000)

    def on_stats(self) -> None:
        lib = self._require_lib()
        if not lib:
            return
        StatsDialog(lib, self._stats, self._libs, self).exec()

    def on_start(self) -> None:
        if not self._current_lib or not self._selected:
            return
        selected = [w for w in self._words if w.key in self._selected]
        dlg = DictationDialog(
            self._current_lib, selected, self._speaker, self._stats, self._settings, self
        )
        dlg.exec()
        self.statusBar().showMessage("听写已结束，成绩已计入统计", 6000)

    def _on_rate_changed(self, value: int) -> None:
        self.lbl_rate_value.setText(f"{value} 词/分")
        self._speaker.set_rate(value)
        if not self._rate_slider.isSliderDown():
            self._settings.tts_rate = value
            self._settings.save()
