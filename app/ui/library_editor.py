"""词库新建/编辑共用对话框：行内编辑，代替旧版的弹窗逐个录入。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import Library, Word
from ..storage import LibraryError, LibraryRepository, validate_lib_name


class WordEditRow(QFrame):
    """一行可编辑的 单词 + 释义。"""

    removed = Signal(object)

    def __init__(self, word: str = "", meaning: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("wordRow")
        self.setStyleSheet(
            "#wordRow { background: #1e2026; border: 1px solid #2d313b; border-radius: 6px; }"
            "#wordRow QLineEdit { background: #23252c; border: none; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.ed_word = QLineEdit(word)
        self.ed_word.setPlaceholderText("单词")
        self.ed_word.setFrame(False)
        self.ed_word.setMinimumWidth(140)
        self.ed_word.returnPressed.connect(lambda: self.ed_meaning.setFocus())

        self.ed_meaning = QLineEdit(meaning)
        self.ed_meaning.setPlaceholderText("释义（可留空）")
        self.ed_meaning.setFrame(False)
        self.ed_meaning.returnPressed.connect(self._on_meaning_enter)

        self.btn_del = QPushButton("✕")
        self.btn_del.setProperty("class", "icon")
        self.btn_del.setFixedWidth(34)
        self.btn_del.setToolTip("删除该行")
        self.btn_del.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self.ed_word)
        layout.addWidget(self.ed_meaning, stretch=1)
        layout.addWidget(self.btn_del)

    def values(self) -> tuple[str, str]:
        return self.ed_word.text().strip(), self.ed_meaning.text().strip()

    def _on_meaning_enter(self) -> None:
        # 回车在释义栏 → 便捷新增下一行
        win = self.window()
        if isinstance(win, LibraryEditorDialog):
            win.add_row()


class LibraryEditorDialog(QDialog):
    """mode=create 新建词库；mode=edit 编辑现有词库（名称锁定）。"""

    def __init__(self, repo: LibraryRepository, lib_name: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = "edit" if lib_name else "create"
        self._original_name = lib_name
        self.lib_name: Optional[str] = None  # 保存成功后回填，供主窗口刷新定位
        self._rows: List[WordEditRow] = []

        self.setWindowTitle("编辑词库" if self._mode == "edit" else "新建词库")
        self.resize(560, 560)
        self._build_ui()

        if self._mode == "edit":
            lib = repo.load(lib_name)
            self.ed_name.setText(lib.name)
            self.ed_name.setEnabled(False)
            for w in lib.words:
                self.add_row(w.word, w.meaning)
            if not self._rows:
                self.add_row()
        else:
            self.add_row()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("词库名称:"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("例如：CET4 核心词 / 日常词汇")
        name_row.addWidget(self.ed_name, stretch=1)
        root.addLayout(name_row)

        self.lbl_error = QLabel("")
        self.lbl_error.setProperty("hint", True)
        self.lbl_error.setStyleSheet("color: #ff5f56;")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.hide()
        root.addWidget(self.lbl_error)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.rows_layout = QVBoxLayout(body)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        btn_add = QPushButton("＋ 添加单词")
        btn_add.clicked.connect(self.add_row)
        root.addWidget(btn_add)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存词库")
        self.btn_save.setProperty("class", "primary")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    # ---------- 行操作 ----------
    def add_row(self, word: str = "", meaning: str = "") -> None:
        row = WordEditRow(word, meaning)
        row.removed.connect(self._remove_row)
        self._rows.append(row)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        if not word:
            row.ed_word.setFocus()

    def _remove_row(self, row: WordEditRow) -> None:
        if len(self._rows) <= 1 and all(r.values() == ("", "") for r in self._rows):
            return  # 至少保留一行空行，避免界面空荡
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    # ---------- 保存 ----------
    def _show_error(self, msg: str) -> None:
        self.lbl_error.setText(msg)
        self.lbl_error.show()

    def _on_save(self) -> None:
        self.lbl_error.hide()
        try:
            name = validate_lib_name(self.ed_name.text())
        except LibraryError as e:
            self._show_error(str(e))
            self.ed_name.setFocus()
            return

        words: List[Word] = []
        seen: set[str] = set()
        dupes: List[str] = []
        for i, row in enumerate(self._rows, start=1):
            w, m = row.values()
            if not w and not m:
                continue  # 整行空白，忽略
            if not w:
                self._show_error(f"第 {i} 行填了释义但缺少单词，请补上或删除该行")
                row.ed_word.setFocus()
                return
            key = w.lower()
            if key in seen:
                dupes.append(w)
                continue
            seen.add(key)
            words.append(Word(w, m))

        if not words:
            self._show_error("请至少录入一个单词")
            return
        if dupes and QMessageBox.question(
            self,
            "发现重复单词",
            "以下单词重复出现，保存时将只保留第一条：\n" + "、".join(dupes) + "\n\n仍要保存吗？",
        ) != QMessageBox.StandardButton.Yes:
            return

        overwrite = False
        if self._mode == "create" and self._repo.exists(name):
            answer = QMessageBox.question(
                self, "覆盖词库", f"词库 '{name}' 已存在，是否覆盖？"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True

        try:
            self._repo.save(Library(name, words), overwrite=overwrite)
        except LibraryError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.lib_name = name
        self.accept()
