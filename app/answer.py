"""答案比较的规范化纯函数。

旧版用严格的 strip+lower 全等比较，输入 "apple." 会被判错。
这里统一做：弯引号归一、去首尾标点、多空白合并、忽略大小写。
"""
from __future__ import annotations

import re
import string

# 常见的中文/弯引号标点，提交时首尾出现不应影响判定
_CURLY_MAP = {
    "\u2018": "'",  # ' left single quotation
    "\u2019": "'",  # ' right single quotation
    "\u201c": '"',  # " left double quotation
    "\u201d": '"',  # " right double quotation
}
_STRIP_CHARS = string.punctuation + "、。，！？；：（）《》【】「」『』·—…．"
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    """把用户输入或标准答案归一成可比较的形式。"""
    t = (text or "").strip()
    for curly, plain in _CURLY_MAP.items():
        t = t.replace(curly, plain)
    t = t.strip(_STRIP_CHARS)          # 只去首尾标点，保留 don't / well-known 内部标点
    t = _WHITESPACE_RE.sub(" ", t)
    return t.lower()


def check_answer(user: str, truth: str) -> bool:
    """判断用户输入是否正确。空输入永远判错。"""
    normalized_user = normalize_answer(user)
    return bool(normalized_user) and normalized_user == normalize_answer(truth)
