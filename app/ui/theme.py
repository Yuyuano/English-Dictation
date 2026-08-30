"""深色主题：全局 QSS 样式表。

配色体系（沿用全局设计规范）：
- 背景   #17181c    卡片/面板  #23252c    输入框 #2a2d35
- 强调   #5b8cff    成功       #34c77b    危险   #ff5f56
- 主文字 #e8eaed    次级文字   #9aa0a6
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QStyleFactory

DARK_QSS = """
* { outline: none; }

QWidget {
    background: #17181c;
    color: #e8eaed;
    font-size: 10pt;
}
QMainWindow, QDialog { background: #17181c; }
QLabel { background: transparent; }
QLabel[hint="true"] { color: #9aa0a6; }
QToolTip {
    background: #2a2d35; color: #e8eaed;
    border: 1px solid #3a3f4b; padding: 4px 8px;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: #2a2d35; color: #e8eaed;
    border: 1px solid #3a3f4b; border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #343845; border-color: #4a5160; }
QPushButton:pressed { background: #262932; }
QPushButton:disabled { color: #6b7280; background: #23252c; border-color: #2d313b; }
QPushButton[class="primary"] {
    background: #5b8cff; border-color: #5b8cff;
    color: #ffffff; font-weight: 600;
}
QPushButton[class="primary"]:hover { background: #6d99ff; }
QPushButton[class="primary"]:pressed { background: #4a7bef; }
QPushButton[class="primary"]:disabled { background: #3a4b76; border-color: #3a4b76; color: #b9c4dd; }
QPushButton[class="icon"] { padding: 4px 10px; }

/* ---------- 输入 ---------- */
QLineEdit {
    background: #2a2d35; color: #e8eaed;
    border: 1px solid #3a3f4b; border-radius: 6px; padding: 6px 10px;
    selection-background-color: #5b8cff; selection-color: #ffffff;
}
QLineEdit:focus { border-color: #5b8cff; }
QLineEdit:disabled { color: #6b7280; background: #23252c; }

/* ---------- 列表 ---------- */
QListWidget {
    background: #1e2026; border: 1px solid #2d313b; border-radius: 8px; padding: 4px;
}
QListWidget::item { border-radius: 6px; margin: 1px 2px; }
QListWidget::item:selected { background: #2f3a52; color: #e8eaed; }
QListWidget::item:hover:!selected { background: #262a33; }

/* ---------- 勾选框 ---------- */
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #4a5160; border-radius: 4px; background: #2a2d35;
}
QCheckBox::indicator:hover { border-color: #5b8cff; }
QCheckBox::indicator:checked { background: #5b8cff; border-color: #5b8cff; }
QCheckBox::indicator:disabled { border-color: #2d313b; background: #23252c; }

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a3f4b; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a5160; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3a3f4b; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #4a5160; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---------- 进度条 ---------- */
QProgressBar {
    background: #23252c; border: none; border-radius: 5px;
    height: 10px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #5b8cff; border-radius: 5px; }

/* ---------- 表格（统计） ---------- */
QTableWidget {
    background: #1e2026; border: 1px solid #2d313b; border-radius: 8px;
    gridline-color: #2d313b; selection-background-color: #2f3a52; selection-color: #e8eaed;
}
QHeaderView::section {
    background: #23252c; color: #9aa0a6;
    border: none; border-bottom: 1px solid #2d313b; padding: 6px;
}
QTableCornerButton::section { background: #23252c; border: none; }

/* ---------- 滑块（语速） ---------- */
QSlider::groove:horizontal { height: 4px; background: #3a3f4b; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #5b8cff; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; background: #e8eaed;
}
QSlider::handle:horizontal:hover { background: #ffffff; }

/* ---------- 其他 ---------- */
QStatusBar { color: #9aa0a6; background: transparent; border-top: 1px solid #23252c; }
QScrollArea { border: none; background: transparent; }
QFrame[card="true"] { background: #23252c; border: 1px solid #2d313b; border-radius: 8px; }
QMessageBox { background: #1e2026; }
QMessageBox QLabel { color: #e8eaed; }
"""


def apply_theme(app: QApplication) -> None:
    """应用全局深色主题。"""
    if "Fusion" in [QStyleFactory.keys()]:
        app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(DARK_QSS)
