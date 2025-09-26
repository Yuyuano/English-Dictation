#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
English Dictation GUI - 多词库管理版
功能：
1. 主界面：选择词库 / 导入 JSON / 自选单词 / 开始听写
2. 词库以 JSON 文件名作为类别名，统一存放于 data/words/
3. 支持动态导入新 JSON（自动复制、重名检测）
4. 听写前可勾选“全部”或“自选”单词（Listbox 多选）
5. 统计仍用 SQLite，按 库名+单词 两级记录
用法：python main_gui.py
"""

from __future__ import annotations
import sys
import json
import os
import random
import sqlite3
import shutil
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pyttsx3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# -------------------- 路径配置 --------------------
# ① 打包后 exe 所在目录 = 词库根目录（源码运行则用脚本所在目录）
if getattr(sys, 'frozen', False):          # PyInstaller 打包后 sys.frozen 为 True
    BASE_DIR = Path(sys.executable).parent # exe 所在文件夹
else:                                      # 直接运行 .py 源码
    BASE_DIR = Path(__file__).resolve().parent # 脚本所在文件夹

LIBS_DIR = BASE_DIR / "Libraries"          # 存放所有词库的文件夹
LIBS_DIR.mkdir(exist_ok=True)              # 若不存在则自动创建

DB_FILE = BASE_DIR / "stats.db"            # SQLite 统计数据库路径（与 exe 同级）
# ------------------------------------------------


# ==================== 数据层 ====================
@dataclass
class Word:
    word: str
    meaning: str



class Stats:
    """SQLite 统计：按 库名+单词 记录"""
    def __init__(self, db: Path = DB_FILE):
        self.conn = sqlite3.connect(db, check_same_thread=False)
        self._init_table()

    def _init_table(self):
        # 建表：库名、单词、正确数、总次数
        self.conn.execute(
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
        self.conn.commit()

    def update(self, lib: str, word: str, correct: bool):
        with self.conn:
            cur = self.conn.execute(
                "SELECT correct, total FROM record WHERE lib_name=? AND word=?",
                (lib, word),
            )
            row = cur.fetchone()
            if row:
                c, t = row
                self.conn.execute(
                    "UPDATE record SET correct=?, total=? WHERE lib_name=? AND word=?",
                    (c + int(correct), t + 1, lib, word),
                )
            else:
                self.conn.execute(
                    "INSERT INTO record (lib_name, word, correct, total) VALUES (?, ?, ?, ?)",
                    (lib, word, int(correct), 1),
                )

    def get(self, lib: str, word: str) -> Tuple[int, int]:
        cur = self.conn.execute(
            "SELECT correct, total FROM record WHERE lib_name=? AND word=?",
            (lib, word),
        )
        row = cur.fetchone()
        return row if row else (0, 0)

    def get_lib_stats(self, lib: str) -> Dict[str, Tuple[int, int]]:
        """返回整个库的所有单词统计"""
        cur = self.conn.execute(
            "SELECT word, correct, total FROM record WHERE lib_name=?", (lib,)
        )
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    def close(self):
        self.conn.close()


# ==================== 业务层 ====================
class DictationCore:
    """与界面解耦的核心逻辑"""
    def __init__(self):
        self.stats = Stats()
        self.engine = self._init_tts()

    def _init_tts(self) -> pyttsx3.Engine:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 130)
            engine.setProperty("volume", 0.9)
            return engine
        except Exception as e:
            messagebox.showerror("TTS 错误", f"语音引擎初始化失败:\n{e}")
            raise

    def speak(self, word: str, repeat: int = 2):
        for i in range(repeat):
            self.engine.say(word)
            self.engine.runAndWait()
            if i < repeat - 1:
                time.sleep(0.3)

    # 工具：扫描本地词库
    def scan_local_libs(self) -> List[str]:
        """返回本地 JSON 文件名列表（不含扩展名）"""
        return [p.stem for p in LIBS_DIR.glob("*.json")]

    def load_lib(self, lib_name: str) -> List[Word]:
        """根据库名加载单词列表"""
        path = LIBS_DIR / f"{lib_name}.json"
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return [Word(**w) for w in data["words"]]

    def import_external_json(self, src: Path) -> str:
        """
        用户选择外部 JSON -> 复制到 data/words/
        返回 库名（文件名）
        """
        if not src.suffix.lower() == ".json":
            raise ValueError("仅支持 *.json 文件")

        dst_name = src.stem
        dst = LIBS_DIR / f"{dst_name}.json"

        # 简单重名校验
        counter = 1
        while dst.exists():
            dst_name = f"{src.stem}_{counter}"
            dst = LIBS_DIR / f"{dst_name}.json"
            counter += 1

        shutil.copy(src, dst)
        return dst_name


# ==================== GUI 层 ====================
class MainApp:
    def __init__(self):
        self.core = DictationCore()
        self.root = tk.Tk()
        self.root.title("English Dictation 多词库版")
        self.root.geometry("700x500")
        self.root.minsize(600, 400)
        self._build_ui()
        self.refresh_lib_list()

    # ---------- 界面构建 ----------
    def _build_ui(self):
        # ===== 顶部按钮栏 =====
        frm_top = ttk.Frame(self.root)
        frm_top.pack(fill="x", padx=10, pady=10)

        ttk.Button(frm_top, text="📂 导入 JSON 词库", command=self.on_import).pack(side="left", padx=5)
        ttk.Button(frm_top, text="➕ 新建词库", command=self.on_create).pack(side="left", padx=5)
        ttk.Button(frm_top, text="💾 导出词库", command=self.on_export).pack(side="left", padx=5)
        ttk.Button(frm_top, text="✏️ 编辑词库", command=self.on_edit).pack(side="left", padx=5)  # ←新增
        ttk.Button(frm_top, text="🔄 刷新列表", command=self.refresh_lib_list).pack(side="left", padx=5)
        ttk.Button(frm_top, text="📊 查看统计", command=self.show_stats).pack(side="left", padx=5)

        # 左：词库选择
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        frm_left = ttk.Frame(paned)
        paned.add(frm_left, weight=1)

        ttk.Label(frm_left, text="📚 词库列表").pack(anchor="w")
        self.lib_listbox = tk.Listbox(frm_left, selectmode="single", exportselection=False)
        self.lib_listbox.pack(fill="both", expand=True)
        self.lib_listbox.bind("<<ListboxSelect>>", self.on_lib_select)

        # 右：单词多选 + 操作
        frm_right = ttk.Frame(paned)
        paned.add(frm_right, weight=2)

        ttk.Label(frm_right, text="✏️ 选择要听写的单词（Ctrl/Shift 多选）").pack(anchor="w")
        self.word_listbox = tk.Listbox(frm_right, selectmode="extended", exportselection=False)
        self.word_listbox.pack(fill="both", expand=True)

        frm_btn = ttk.Frame(frm_right)
        frm_btn.pack(fill="x", pady=5)
        ttk.Button(frm_btn, text="🔊 播放所选", command=self.play_selected).pack(side="left", padx=5)
        ttk.Button(frm_btn, text="▶ 开始听写", command=self.start_dictation).pack(side="left", padx=5)

        # 底部状态
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, relief="sunken").pack(side="bottom", fill="x")

    # ---------- 事件处理 ----------
    def refresh_lib_list(self):
        """扫描本地词库并刷新 Listbox"""
        self.lib_listbox.delete(0, tk.END)
        libs = self.core.scan_local_libs()
        for lib in libs:
            self.lib_listbox.insert(tk.END, lib)
        self.status.set(f"共发现 {len(libs)} 个词库")

    # ========== 新增：查看统计 ==========
    def show_stats(self):
        """弹出窗口显示当前库整体正确率"""
        selection = self.lib_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个词库")
            return
        lib = self.lib_listbox.get(selection[0])
        stats_dict = self.core.stats.get_lib_stats(lib)
        if not stats_dict:
            messagebox.showinfo("统计", f"词库 '{lib}' 暂无答题记录")
            return

        total_correct = sum(c for c, t in stats_dict.values())
        total_times   = sum(t for c, t in stats_dict.values())
        rate = total_correct / total_times * 100 if total_times else 0
        msg = f"词库：{lib}\n总题次：{total_times}\n正确数：{total_correct}\n正确率：{rate:.1f}%"
        messagebox.showinfo("统计", msg)
    # ==================== 新建词库 ====================
    def on_create(self):
        """弹出对话框，当场录入单词→自动生成标准 JSON"""
        top = tk.Toplevel(self.root)
        top.title("新建词库")
        top.geometry("600x400")
        top.grab_set()  # 模态

        # 顶部：库名
        frm_name = ttk.Frame(top)
        frm_name.pack(fill="x", padx=10, pady=5)
        ttk.Label(frm_name, text="词库名称:").pack(side="left")
        var_name = tk.StringVar()
        ttk.Entry(frm_name, textvariable=var_name, width=30).pack(side="left", padx=5)

        # 中部：Treeview 展示单词
        cols = ("word", "meaning")
        tree = ttk.Treeview(top, columns=cols, show="headings", height=12)
        for c in cols:
            tree.heading(c, text=c.title())
            tree.column(c, width=120, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=5)

        # 底部：录入区
        frm_add = ttk.Frame(top)
        frm_add.pack(fill="x", padx=10, pady=5)
        ents = {}
        for col in cols:
            ttk.Label(frm_add, text=f"{col.title()}:").pack(side="left")
            ents[col] = tk.StringVar()
            ttk.Entry(frm_add, textvariable=ents[col], width=15).pack(side="left", padx=5)
        # 添加按钮
        def add_to_tree():
            if not all(ents[col].get() for col in cols):
                messagebox.showerror("缺项", "请填写全部字段", parent=top)
                return
            tree.insert("", tk.END, values=[ents[col].get() for col in cols])
            for col in cols:
                ents[col].set("")
        ttk.Button(frm_add, text="添加", command=add_to_tree).pack(side="left", padx=5)

        # 确认 & 取消
        frm_ok = ttk.Frame(top)
        frm_ok.pack(fill="x", padx=10, pady=10)
        ttk.Button(frm_ok, text="保存词库", command=lambda: save_and_close()).pack(side="right", padx=5)
        ttk.Button(frm_ok, text="取消", command=top.destroy).pack(side="right", padx=5)

        def save_and_close():
            name = var_name.get().strip()
            if not name:
                messagebox.showerror("无名称", "请输入词库名称", parent=top)
                return
            if not tree.get_children():
                messagebox.showerror("空库", "请至少添加一个单词", parent=top)
                return
            # 构造标准格式
            words = []
            for item in tree.get_children():
                vals = tree.item(item, "values")
                {"word": vals[0], "meaning": vals[1]}
            data = {"words": words}
            dst = LIBS_DIR / f"{name}.json"
            if dst.exists():
                if not messagebox.askyesno("覆盖", f"词库 '{name}' 已存在，是否覆盖？", parent=top):
                    return
            dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("成功", f"词库已保存: {dst}", parent=top)
            top.destroy()
            self.refresh_lib_list()  # 立即刷新主列表

    # ==================== 导出词库 ====================
    def on_export(self):
        """把当前选中的词库另存为 JSON（标准格式）"""
        selection = self.lib_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要导出的词库")
            return
        lib_name = self.lib_listbox.get(selection[0])
        words = self.core.load_lib(lib_name)
        data = {"words": [asdict(w) for w in words]}  # Word -> dict

        file = filedialog.asksaveasfilename(
            title="导出词库",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{lib_name}.json",
        )
        if not file:
            return
        Path(file).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("成功", f"词库已导出至:\n{file}")
    def on_import(self):
        """弹出文件选择框，导入外部 JSON"""
        file = filedialog.askopenfilename(title="选择 JSON 词库", filetypes=[("JSON", "*.json")])
        if not file:
            return
        try:
            lib_name = self.core.import_external_json(Path(file))
            self.refresh_lib_list()
            # 自动选中新导入的库
            idx = list(self.lib_listbox.get(0, tk.END)).index(lib_name)
            self.lib_listbox.selection_set(idx)
            self.on_lib_select()
            messagebox.showinfo("成功", f"已导入词库: {lib_name}")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def on_lib_select(self, event=None):
        """选中词库后，加载单词并填充右侧列表"""
        selection = self.lib_listbox.curselection()
        if not selection:
            return
        lib_name = self.lib_listbox.get(selection[0])
        words = self.core.load_lib(lib_name)
        self.word_listbox.delete(0, tk.END)
        for w in words:
            self.word_listbox.insert(tk.END, f"{w.word}  ({w.meaning})")
        self.status.set(f"词库 '{lib_name}' 共 {len(words)} 个单词")

    def play_selected(self):
        """播放用户选中的单词（多选则顺序播放）"""
        selection = self.word_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要播放的单词")
            return
        # 提取单词文本（去掉括号释义）
        for idx in selection:
            text = self.word_listbox.get(idx).split()[0]
            self.core.speak(text, repeat=1)

    def start_dictation(self):
        """进入听写窗口"""
        selection = self.word_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要听写的单词（可 Ctrl+A 全选）")
            return
        lib_name = self.lib_listbox.get(self.lib_listbox.curselection()[0])
        words_all = self.core.load_lib(lib_name)
        # 根据索引过滤
        selected_words = [words_all[i] for i in selection]
        DictationWindow(self.core, lib_name, selected_words)

    # ==================== 编辑词库 ====================
    def on_edit(self):
        """弹出 TreeView 窗口，可对当前库：增/删/改单词"""
        selection = self.lib_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要编辑的词库")
            return
        lib_name = self.lib_listbox.get(selection[0])
        words = self.core.load_lib(lib_name)  # List[Word]

        # ---------- 编辑窗口 ----------
        top = tk.Toplevel(self.root)
        top.title(f"编辑词库 - {lib_name}")
        top.geometry("700x500")
        top.grab_set()

        # 顶部按钮栏
        frm_top = ttk.Frame(top)
        frm_top.pack(fill="x", padx=10, pady=5)
        ttk.Button(frm_top, text="➕ 添加单词", command=lambda: add_word()).pack(side="left", padx=5)
        ttk.Button(frm_top, text="🗑 删除选中", command=lambda: del_selected()).pack(side="left", padx=5)
        ttk.Button(frm_top, text="💾 保存修改", command=lambda: save()).pack(side="right", padx=5)
        ttk.Button(frm_top, text="取消", command=top.destroy).pack(side="right", padx=5)

        # TreeView 展示
        cols = ("word", "meaning")
        tree = ttk.Treeview(top, columns=cols, show="headings", height=15)
        for c in cols:
            tree.heading(c, text=c.title())
            tree.column(c, width=200, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=5)

        # 填充现有单词
        for w in words:
            tree.insert("", tk.END, values=(w.word, w.meaning))

        # ---------- 功能函数 ----------
        def add_word():
            """小弹窗录入新单词"""
                # 弹窗
            top_add = tk.Toplevel(top)
            top_add.title("添加单词")
            top_add.grab_set()
            tk.Label(top_add, text="单词:").grid(row=0, column=0, padx=5, pady=5)
            tk.Label(top_add, text="释义:").grid(row=1, column=0, padx=5, pady=5)
            var_w = tk.StringVar()
            var_m = tk.StringVar()
            tk.Entry(top_add, textvariable=var_w, width=25).grid(row=0, column=1)
            tk.Entry(top_add, textvariable=var_m, width=25).grid(row=1, column=1)
            ttk.Button(top_add, text="确定", command=lambda: (
                tree.insert("", tk.END, values=(var_w.get(), var_m.get())),
                top_add.destroy()
            )).grid(row=2, column=0, columnspan=2, pady=5)

        def del_selected():
            for item in tree.selection():
                tree.delete(item)

        def save():
            """把 TreeView 当前内容写回 JSON"""
            new_words = []
            for item in tree.get_children():
                vals = tree.item(item, "values")
                new_words.append({"word": vals[0], "meaning": vals[1]})
            data = {"words": new_words}
            dst = LIBS_DIR / f"{lib_name}.json"
            dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("成功", f"已保存到:\n{dst}", parent=top)
            top.destroy()
            self.refresh_lib_list()  # 刷新主列表
# ==================== 听写子窗口 ====================
class DictationWindow(tk.Toplevel):
    def __init__(self, core: DictationCore, lib_name: str, words: List[Word]):
        super().__init__()
        self.core = core
        self.lib_name = lib_name
        self.words = words
        self.used: set[str] = set()
        self.score = 0
        self.total = 0

        self.current: Optional[Word] = None

        self.title(f"听写 - {lib_name}")
        self.geometry("600x400")
        self._build_ui()
        self.next_word()

    def _build_ui(self):
        # 顶部信息
        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", padx=10, pady=10)


        ttk.Label(frm_top, text="释义:", font=("YaHei", 12)).pack(side="left", padx=(20, 5))
        self.lbl_mean = ttk.Label(frm_top, text="", font=("YaHei", 12), foreground="green")
        self.lbl_mean.pack(side="left")

        # 播放 + 输入
        frm_mid = ttk.Frame(self)
        frm_mid.pack(fill="x", padx=10, pady=10)

        ttk.Button(frm_mid, text="🔊 播放", command=self.play_current).pack(side="left")
        ttk.Label(frm_mid, text=" 拼写:", font=("YaHei", 14)).pack(side="left")

        self.var_input = tk.StringVar()
        ent = ttk.Entry(frm_mid, textvariable=self.var_input, font=("YaHei", 14), width=15)
        ent.pack(side="left", padx=5)
        ent.bind("<Return>", lambda e: self.check())

        ttk.Button(frm_mid, text="提交", command=self.check).pack(side="left", padx=5)

        # 进度
        self.lbl_stat = ttk.Label(self, text="", font=("YaHei", 12), anchor="center")
        self.lbl_stat.pack(pady=10)

        # 按钮栏
        frm_btn = ttk.Frame(self)
        frm_btn.pack(pady=5)
        ttk.Button(frm_btn, text="下一题", command=self.next_word).pack(side="left", padx=5)
        ttk.Button(frm_btn, text="结束", command=self.destroy).pack(side="left", padx=5)

    # ---------- 听写逻辑 ----------
    def next_word(self):
        """换题并刷新界面"""
        if len(self.used) == len(self.words):
            messagebox.showinfo("完成", f"本轮结束！正确率: {self.score}/{self.total}")
            self.destroy()
            return
        self.current = random.choice([w for w in self.words if w.word not in self.used])
        self.used.add(self.current.word)


        self.lbl_mean.config(text=self.current.meaning)
        self.var_input.set("")
        self.lbl_stat.config(text="")
        self.play_current()

    def play_current(self):
        if self.current:
            threading.Thread(target=self.core.speak, args=(self.current.word, 2), daemon=True).start()

    def check(self):
        if not self.current:
            return
        user = self.var_input.get().strip().lower()
        if not user:
            messagebox.showinfo("提示", "请输入拼写！")
            return

        correct = user == self.current.word.lower()
        self.core.stats.update(self.lib_name, self.current.word, correct)
        c, t = self.core.stats.get(self.lib_name, self.current.word)
        rate = c / t * 100 if t else 0
        self.total += 1
        if correct:
            self.score += 1
            self.lbl_stat.config(text=f"✅ 正确！（对该词正确率 {rate:.0f}%）", foreground="green")
            # 2 秒后自动下一题
            self.after(2000, self.next_word)
        else:
            messagebox.showerror("错误", f"正确答案：{self.current.word}")
            self.lbl_stat.config(text=f"❌ 错误（对该词正确率 {rate:.0f}%）", foreground="red")


# ==================== 入口 ====================
def main():
    app = MainApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()